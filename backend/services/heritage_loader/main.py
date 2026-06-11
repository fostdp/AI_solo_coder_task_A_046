"""
Heritage Loader 微服务
负责：遗迹数据管理、水文数据查询、数据导入
端口：8001
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import logging
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping

from common.config import settings
from common.database import get_db, init_db
from common.models import WaterHeritageSite, PaleoHydrologyData, DynastyDict
from common.schemas import (
    WaterHeritageSiteCreate,
    WaterHeritageSiteUpdate,
    WaterHeritageSiteResponse,
    PaleoHydrologyDataResponse,
    StatisticsResponse,
)
from common.redis_client import pubsub
from common.config import channels
from common.params.hydraulic_params import REGIONS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("heritage_loader")

app = FastAPI(
    title="古代水利工程遗迹-数据管理服务",
    description="负责遗迹数据CRUD、水文数据查询、数据导入",
    version="3.0.0"
)


@app.on_event("startup")
async def startup_event():
    logger.info("Heritage Loader 服务启动...")
    try:
        init_db()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.warning(f"数据库初始化异常（可能已有表）: {e}")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "heritage_loader"}


# ==============================================
# 遗迹 CRUD
# ==============================================

@app.get("/sites", response_model=List[WaterHeritageSiteResponse])
def list_sites(
    skip: int = 0,
    limit: int = 100,
    site_type: Optional[str] = None,
    dynasty: Optional[str] = None,
    preservation_status: Optional[str] = None,
    min_irrigation_area: Optional[float] = None,
    max_irrigation_area: Optional[float] = None,
    min_longitude: Optional[float] = None,
    max_longitude: Optional[float] = None,
    min_latitude: Optional[float] = None,
    max_latitude: Optional[float] = None,
    db: Session = Depends(get_db)
):
    """遗迹列表，支持多条件筛选"""
    query = db.query(WaterHeritageSite)

    if site_type:
        query = query.filter(WaterHeritageSite.site_type == site_type)
    if dynasty:
        query = query.filter(WaterHeritageSite.dynasty == dynasty)
    if preservation_status:
        query = query.filter(WaterHeritageSite.preservation_status == preservation_status)
    if min_irrigation_area:
        query = query.filter(WaterHeritageSite.irrigation_area >= min_irrigation_area)
    if max_irrigation_area:
        query = query.filter(WaterHeritageSite.irrigation_area <= max_irrigation_area)
    if min_longitude:
        query = query.filter(WaterHeritageSite.longitude >= min_longitude)
    if max_longitude:
        query = query.filter(WaterHeritageSite.longitude <= max_longitude)
    if min_latitude:
        query = query.filter(WaterHeritageSite.latitude >= min_latitude)
    if max_latitude:
        query = query.filter(WaterHeritageSite.latitude <= max_latitude)

    sites = query.order_by(WaterHeritageSite.dynasty_order).offset(skip).limit(limit).all()
    return sites


@app.get("/sites/{site_id}", response_model=WaterHeritageSiteResponse)
def get_site(site_id: int, db: Session = Depends(get_db)):
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹不存在")
    return site


@app.post("/sites", response_model=WaterHeritageSiteResponse)
def create_site(site_data: WaterHeritageSiteCreate, db: Session = Depends(get_db)):
    """新增遗迹，发布 imported 事件"""
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point

    point = Point(site_data.longitude, site_data.latitude)
    geom = from_shape(point, srid=4326)

    site = WaterHeritageSite(
        **site_data.model_dump(),
        geom=geom
    )
    db.add(site)
    db.flush()

    try:
        db.commit()
        db.refresh(site)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"创建失败: {str(e)}")

    # 发布事件
    pubsub.publish(channels.HERITAGE_IMPORTED, {
        "event_type": "site_created",
        "site_id": site.id,
        "data": {"name": site.name, "site_type": site.site_type}
    })

    logger.info(f"新增遗迹: {site.name} (id={site.id})")
    return site


@app.put("/sites/{site_id}", response_model=WaterHeritageSiteResponse)
def update_site(site_id: int, update_data: WaterHeritageSiteUpdate, db: Session = Depends(get_db)):
    """更新遗迹，发布 updated 事件，检查告警"""
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹不存在")

    old_status = site.preservation_status
    update_dict = update_data.model_dump(exclude_unset=True)

    if 'longitude' in update_dict or 'latitude' in update_dict:
        from geoalchemy2.shape import from_shape
        from shapely.geometry import Point
        lon = update_dict.get('longitude', site.longitude)
        lat = update_dict.get('latitude', site.latitude)
        site.geom = from_shape(Point(lon, lat), srid=4326)

    for key, value in update_dict.items():
        if key not in ('longitude', 'latitude') and hasattr(site, key):
            setattr(site, key, value)

    try:
        db.commit()
        db.refresh(site)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"更新失败: {str(e)}")

    # 发布更新事件
    pubsub.publish(channels.HERITAGE_UPDATED, {
        "event_type": "site_updated",
        "site_id": site.id,
        "data": {
            "old_status": old_status,
            "new_status": site.preservation_status,
            "preservation_changed": old_status != site.preservation_status
        }
    })

    # 状态恶化为完全废弃，触发告警
    if old_status != '完全废弃' and site.preservation_status == '完全废弃':
        pubsub.publish(channels.ALERT_TRIGGERED, {
            "event_type": "preservation_worsened",
            "site_id": site.id,
            "data": {
                "site_name": site.name,
                "old_status": old_status,
                "new_status": '完全废弃',
                "alert_type": "文物保护预警",
                "alert_level": "高",
                "longitude": site.longitude,
                "latitude": site.latitude,
            }
        })
        logger.warning(f"告警触发: {site.name} 状态恶化为完全废弃")

    logger.info(f"更新遗迹: {site.name} (id={site.id})")
    return site


@app.delete("/sites/{site_id}")
def delete_site(site_id: int, db: Session = Depends(get_db)):
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹不存在")

    site_name = site.name
    db.delete(site)
    db.commit()

    pubsub.publish(channels.HERITAGE_DELETED, {
        "event_type": "site_deleted",
        "site_id": site_id,
        "data": {"name": site_name}
    })

    logger.info(f"删除遗迹: {site_name} (id={site_id})")
    return {"status": "ok", "message": f"遗迹 {site_name} 已删除"}


# ==============================================
# 水文数据
# ==============================================

@app.get("/hydrology", response_model=List[PaleoHydrologyDataResponse])
def list_hydrology(
    region: Optional[str] = None,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    query = db.query(PaleoHydrologyData)
    if region:
        query = query.filter(PaleoHydrologyData.region == region)
    if start_year:
        query = query.filter(PaleoHydrologyData.year >= start_year)
    if end_year:
        query = query.filter(PaleoHydrologyData.year <= end_year)
    data = query.order_by(PaleoHydrologyData.year, PaleoHydrologyData.region).offset(skip).limit(limit).all()
    return data


@app.get("/hydrology/by-site/{site_id}", response_model=List[PaleoHydrologyDataResponse])
def get_hydrology_for_site(
    site_id: int,
    period: Optional[str] = Query("contemporary", description="contemporary同期/historical历史/all全部"),
    db: Session = Depends(get_db)
):
    """获取遗迹对应区域的水文数据"""
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹不存在")

    import hashlib
    idx = int(hashlib.md5(site.name.encode()).hexdigest(), 16) % len(REGIONS)
    region = REGIONS[idx]

    query = db.query(PaleoHydrologyData).filter(PaleoHydrologyData.region == region)

    if period == "contemporary":
        dynasty = db.query(DynastyDict).filter(DynastyDict.order == site.dynasty_order).first()
        if dynasty:
            query = query.filter(
                PaleoHydrologyData.year >= dynasty.start_year,
                PaleoHydrologyData.year <= dynasty.end_year
            )
    elif period == "historical":
        query = query.filter(PaleoHydrologyData.year < 1912)

    data = query.order_by(PaleoHydrologyData.year).all()
    return data


# ==============================================
# 统计信息
# ==============================================

@app.get("/statistics", response_model=StatisticsResponse)
def get_statistics(db: Session = Depends(get_db)):
    from sqlalchemy import func

    total = db.query(func.count(WaterHeritageSite.id)).scalar()

    by_type = dict(db.query(WaterHeritageSite.site_type, func.count(WaterHeritageSite.id))
                   .group_by(WaterHeritageSite.site_type).all())

    by_dynasty = dict(db.query(WaterHeritageSite.dynasty, func.count(WaterHeritageSite.id))
                      .group_by(WaterHeritageSite.dynasty_order, WaterHeritageSite.dynasty)
                      .order_by(WaterHeritageSite.dynasty_order).all())

    by_status = dict(db.query(WaterHeritageSite.preservation_status, func.count(WaterHeritageSite.id))
                     .group_by(WaterHeritageSite.preservation_status).all())

    avg_area = db.query(func.avg(WaterHeritageSite.irrigation_area)).scalar() or 0

    return {
        "total_sites": total,
        "by_type": by_type,
        "by_dynasty": by_dynasty,
        "by_status": by_status,
        "avg_irrigation_area": float(avg_area),
        "alerts_count": 0,
        "high_potential_count": 0,
    }


# ==============================================
# 朝代字典
# ==============================================

@app.get("/dynasties")
def get_dynasties(db: Session = Depends(get_db)):
    dynasties = db.query(DynastyDict).order_by(DynastyDict.order).all()
    return [{"id": d.id, "name": d.name, "start_year": d.start_year,
             "end_year": d.end_year, "order": d.order} for d in dynasties]


# ==============================================
# 区域列表
# ==============================================

@app.get("/regions")
def get_regions():
    return {"regions": REGIONS}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.HERITAGE_LOADER_PORT)
