"""
Hydro Reconstructor 微服务
负责：水力计算、灌溉区复原、蒙特卡洛分析、结构剖面生成
端口：8002
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import json
import logging
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from geoalchemy2.shape import to_shape, from_shape
from shapely.geometry import mapping

from common.config import settings, channels
from common.database import get_db, init_db
from common.models import WaterHeritageSite, PaleoHydrologyData, FunctionalRestoration, DynastyDict
from common.redis_client import pubsub
from common.params.hydraulic_params import REGIONS

from .restoration_model import (
    restore_site,
    monte_carlo_analysis,
    ParameterEstimator,
    generate_supply_polygon,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hydro_reconstructor")

app = FastAPI(
    title="古代水利工程遗迹-水力复原服务",
    description="负责水力计算、灌溉区复原、蒙特卡洛分析、结构剖面",
    version="3.0.0"
)


# ==============================================
# 事件订阅
# ==============================================

def _on_restoration_requested(message: Dict[str, Any]):
    """处理复原请求事件"""
    site_id = message.get('site_id')
    if not site_id:
        return
    logger.info(f"收到复原请求: site_id={site_id}")
    try:
        from common.database import SessionLocal
        db = SessionLocal()
        result = _do_restore(db, site_id)
        db.close()
        if result:
            pubsub.publish(channels.RESTORATION_COMPLETED, {
                "event_type": "restoration_completed",
                "site_id": site_id,
                "data": {"actual_capacity": result.actual_irrigation_capacity}
            })
    except Exception as e:
        logger.error(f"复原计算失败 site_id={site_id}: {e}")
        pubsub.publish(channels.RESTORATION_FAILED, {
            "event_type": "restoration_failed",
            "site_id": site_id,
            "data": {"error": str(e)}
        })


def _on_heritage_imported(message: Dict[str, Any]):
    """新遗迹导入时自动计算"""
    site_id = message.get('site_id')
    if not site_id:
        return
    logger.info(f"新遗迹导入，自动计算复原: site_id={site_id}")
    try:
        from common.database import SessionLocal
        db = SessionLocal()
        _do_restore(db, site_id)
        db.close()
    except Exception as e:
        logger.error(f"自动复原计算失败 site_id={site_id}: {e}")


def _on_batch_restore(message: Dict[str, Any]):
    """批量复原请求"""
    logger.info("收到批量复原请求")
    try:
        from common.database import SessionLocal
        db = SessionLocal()
        sites = db.query(WaterHeritageSite).all()
        count = 0
        for site in sites:
            try:
                _do_restore(db, site.id)
                count += 1
            except Exception:
                pass
        db.close()
        logger.info(f"批量复原完成: {count}/{len(sites)}")
    except Exception as e:
        logger.error(f"批量复原失败: {e}")


@app.on_event("startup")
async def startup_event():
    logger.info("Hydro Reconstructor 服务启动...")
    try:
        init_db()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.warning(f"数据库初始化异常: {e}")

    # 订阅事件
    pubsub.subscribe(channels.RESTORATION_REQUESTED, _on_restoration_requested)
    pubsub.subscribe(channels.HERITAGE_IMPORTED, _on_heritage_imported)
    pubsub.subscribe(channels.BATCH_RESTORE_REQUESTED, _on_batch_restore)
    logger.info("Redis Pub/Sub 订阅完成")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "hydro_reconstructor"}


# ==============================================
# 核心：功能复原
# ==============================================

def _do_restore(db: Session, site_id: int) -> Optional[FunctionalRestoration]:
    """执行复原计算（内部函数，供同步和异步调用）"""
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        return None

    # 水文数据
    import hashlib
    idx = int(hashlib.md5(site.name.encode()).hexdigest(), 16) % len(REGIONS)
    region = REGIONS[idx]

    dynasty = db.query(DynastyDict).filter(DynastyDict.order == site.dynasty_order).first()
    hydro_query = db.query(PaleoHydrologyData).filter(PaleoHydrologyData.region == region)
    if dynasty:
        hydro_query = hydro_query.filter(
            PaleoHydrologyData.year >= dynasty.start_year,
            PaleoHydrologyData.year <= dynasty.end_year
        )
    hydro_list = hydro_query.order_by(PaleoHydrologyData.year).all()
    hydro_data = [{"rainfall": h.rainfall, "runoff": h.runoff, "year": h.year} for h in hydro_list]

    # 复原计算
    site_dict = {
        'id': site.id,
        'name': site.name,
        'site_type': site.site_type,
        'dynasty_order': site.dynasty_order,
        'preservation_status': site.preservation_status,
        'irrigation_area': site.irrigation_area,
        'dam_height': site.dam_height,
        'canal_length': site.canal_length,
        'longitude': site.longitude,
        'latitude': site.latitude,
    }
    result = restore_site(site_dict, hydro_data)

    # 保存结果
    existing = db.query(FunctionalRestoration).filter(FunctionalRestoration.site_id == site_id).first()

    poly_geom = from_shape(result['supply_polygon'], srid=4326)

    if existing:
        existing.original_irrigation_capacity = result['original_irrigation_capacity']
        existing.actual_irrigation_capacity = result['actual_irrigation_capacity']
        existing.water_supply_range_geom = poly_geom
        existing.supply_population = result['supply_population']
        existing.restoration_notes = result['restoration_notes']
        existing.parameter_estimation = result['parameter_estimation']
        existing.uncertainty_analysis = result['uncertainty_analysis']
        restoration = existing
    else:
        restoration = FunctionalRestoration(
            site_id=site_id,
            original_irrigation_capacity=result['original_irrigation_capacity'],
            actual_irrigation_capacity=result['actual_irrigation_capacity'],
            water_supply_range_geom=poly_geom,
            supply_population=result['supply_population'],
            restoration_notes=result['restoration_notes'],
            parameter_estimation=result['parameter_estimation'],
            uncertainty_analysis=result['uncertainty_analysis'],
        )
        db.add(restoration)

    db.commit()
    db.refresh(restoration)

    logger.info(f"复原计算完成: {site.name} (id={site_id})")
    return restoration


@app.post("/restore/{site_id}")
def restore_site_endpoint(site_id: int, background_tasks: BackgroundTasks,
                          async_mode: bool = True, db: Session = Depends(get_db)):
    """触发功能复原计算"""
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹不存在")

    if async_mode:
        # 异步模式：发布事件，由订阅者处理
        pubsub.publish(channels.RESTORATION_REQUESTED, {
            "event_type": "restoration_request",
            "site_id": site_id,
        })
        return {"status": "accepted", "site_id": site_id, "message": "复原计算已提交"}
    else:
        # 同步模式
        restoration = _do_restore(db, site_id)
        if not restoration:
            raise HTTPException(status_code=500, detail="复原计算失败")
        return _format_restoration_response(restoration)


def _format_restoration_response(restoration: FunctionalRestoration) -> Dict:
    poly = to_shape(restoration.water_supply_range_geom) if restoration.water_supply_range_geom else None
    return {
        "id": restoration.id,
        "site_id": restoration.site_id,
        "original_irrigation_capacity": restoration.original_irrigation_capacity,
        "actual_irrigation_capacity": restoration.actual_irrigation_capacity,
        "water_supply_range_geom": mapping(poly) if poly else None,
        "supply_population": restoration.supply_population,
        "restoration_notes": restoration.restoration_notes,
        "parameter_estimation": restoration.parameter_estimation,
        "uncertainty_analysis": restoration.uncertainty_analysis,
        "calculated_at": restoration.calculated_at,
    }


@app.get("/restore/{site_id}")
def get_restoration(site_id: int, db: Session = Depends(get_db)):
    """获取复原结果"""
    restoration = db.query(FunctionalRestoration).filter(FunctionalRestoration.site_id == site_id).first()
    if not restoration:
        raise HTTPException(status_code=404, detail="未找到复原结果")
    return _format_restoration_response(restoration)


# ==============================================
# 蒙特卡洛分析
# ==============================================

@app.post("/monte-carlo/{site_id}")
def monte_carlo_site(site_id: int, n_samples: int = 1000, seed: int = 42,
                     db: Session = Depends(get_db)):
    """对单个遗迹做蒙特卡洛不确定性分析"""
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹不存在")

    import hashlib
    idx = int(hashlib.md5(site.name.encode()).hexdigest(), 16) % len(REGIONS)
    region = REGIONS[idx]

    hydro_list = db.query(PaleoHydrologyData).filter(
        PaleoHydrologyData.region == region
    ).limit(20).all()

    avg_rainfall = sum(h.rainfall for h in hydro_list) / len(hydro_list) if hydro_list else 800.0
    avg_runoff = sum(h.runoff for h in hydro_list) / len(hydro_list) if hydro_list else 300.0

    estimator = ParameterEstimator()
    params, _ = estimator.estimate_parameters(
        site.site_type, site.dynasty_order,
        irrigation_area=site.irrigation_area,
        dam_height=site.dam_height,
        canal_length=site.canal_length
    )

    result = monte_carlo_analysis(site.site_type, params, avg_rainfall, avg_runoff, n_samples, seed)
    return {"site_id": site_id, "monte_carlo": result}


# ==============================================
# 参数估计
# ==============================================

@app.post("/parameter-estimation/{site_id}")
def estimate_parameters(site_id: int, db: Session = Depends(get_db)):
    """参数估计接口"""
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹不存在")

    estimator = ParameterEstimator()
    params, reliability = estimator.estimate_parameters(
        site.site_type, site.dynasty_order,
        irrigation_area=site.irrigation_area,
        dam_height=site.dam_height,
        canal_length=site.canal_length
    )

    return {
        "site_id": site_id,
        "parameters": params,
        "reliability": reliability,
    }


# ==============================================
# 灌溉区 GeoJSON
# ==============================================

@app.get("/supply-ranges")
def get_supply_ranges(
    min_longitude: Optional[float] = None,
    max_longitude: Optional[float] = None,
    min_latitude: Optional[float] = None,
    max_latitude: Optional[float] = None,
    simplified: bool = False,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """获取灌溉区多边形（GeoJSON FeatureCollection）"""
    query = db.query(FunctionalRestoration).filter(
        FunctionalRestoration.water_supply_range_geom.isnot(None)
    )

    if min_longitude and max_longitude and min_latitude and max_latitude:
        from geoalchemy2 import func
        bbox = func.ST_MakeEnvelope(min_longitude, min_latitude, max_longitude, max_latitude, 4326)
        query = query.filter(func.ST_Intersects(FunctionalRestoration.water_supply_range_geom, bbox))

    restorations = query.offset(skip).limit(limit).all()

    features = []
    for r in restorations:
        if r.water_supply_range_geom:
            poly = to_shape(r.water_supply_range_geom)
            site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == r.site_id).first()
            features.append({
                "type": "Feature",
                "geometry": mapping(poly),
                "properties": {
                    "site_id": r.site_id,
                    "site_name": site.name if site else "",
                    "site_type": site.site_type if site else "",
                    "actual_capacity": r.actual_irrigation_capacity,
                    "preservation_status": site.preservation_status if site else "",
                }
            })

    return {
        "type": "FeatureCollection",
        "features": features,
    }


# ==============================================
# 结构剖面图
# ==============================================

@app.get("/cross-section/{site_id}")
def get_cross_section(site_id: int, db: Session = Depends(get_db)):
    """生成结构剖面图数据"""
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹不存在")

    restoration = db.query(FunctionalRestoration).filter(
        FunctionalRestoration.site_id == site_id
    ).first()

    result = _generate_cross_section(site, restoration)
    return result


def _generate_cross_section(site, restoration) -> Dict[str, Any]:
    """生成5类工程剖面图数据"""
    n_points = 50
    site_type = site.site_type

    dam_h = site.dam_height or 5.0
    if restoration and restoration.parameter_estimation:
        params = restoration.parameter_estimation.get('parameters', {})
        dam_h = params.get('dam_height', dam_h)

    x = list(range(n_points))

    if site_type == '渠':
        top_w = dam_h * 4
        bottom_w = dam_h * 2
        mid = n_points // 2
        ground_y = [0.0] * n_points
        structure_y = [0.0] * n_points
        water_y = [0.0] * n_points

        for i in range(n_points):
            rel = (i - mid) / (n_points / 2) * top_w
            if abs(rel) <= bottom_w / 2:
                structure_y[i] = dam_h
            elif abs(rel) <= top_w / 2:
                slope_dist = abs(rel) - bottom_w / 2
                structure_y[i] = dam_h - slope_dist * (dam_h / ((top_w - bottom_w) / 2))
            else:
                structure_y[i] = 0
            water_y[i] = min(dam_h * 0.7, max(0, structure_y[i] - 0.3))

    elif site_type in ('堰', '陂'):
        base_w = dam_h * 8
        top_w = dam_h * 1.5
        mid = n_points // 2
        ground_y = [0.0] * n_points
        structure_y = [0.0] * n_points
        water_y = [0.0] * n_points

        upstream_slope = 1.0 if site_type == '堰' else 2.5
        downstream_slope = 1.5 if site_type == '堰' else 2.0

        for i in range(n_points):
            rel = (i - mid) / (n_points / 2) * base_w / 2
            if abs(rel) <= top_w / 2:
                structure_y[i] = dam_h
            elif rel < 0:
                d = abs(rel) - top_w / 2
                structure_y[i] = max(0, dam_h - d / upstream_slope)
            else:
                d = abs(rel) - top_w / 2
                structure_y[i] = max(0, dam_h - d / downstream_slope)

            if i < mid and rel > -base_w / 2:
                water_y[i] = min(dam_h * 0.8, structure_y[i] + 0.5)
            else:
                water_y[i] = 0

    elif site_type == '塘':
        base_w = dam_h * 10
        max_depth = dam_h * 0.6
        mid = n_points // 2
        ground_y = [0.0] * n_points
        structure_y = [0.0] * n_points
        water_y = [0.0] * n_points

        for i in range(n_points):
            rel = (i - mid) / (n_points / 2) * base_w / 2
            dist_factor = abs(rel) / (base_w / 2)
            depth = max_depth * (1 - dist_factor ** 1.5)
            ground_y[i] = -depth
            structure_y[i] = -depth + 0.5
            water_y[i] = 0

    elif site_type == '井':
        well_depth = dam_h
        well_r = 0.5
        mid = n_points // 2
        ground_y = [0.0] * n_points
        structure_y = [0.0] * n_points
        water_y = [0.0] * n_points

        for i in range(n_points):
            rel = (i - mid) / (n_points / 2) * 3
            if abs(rel) <= well_r + 0.3:
                ground_y[i] = -well_depth
                structure_y[i] = -well_depth + 0.3
                water_y[i] = -well_depth * 0.6
            else:
                ground_y[i] = 0
                structure_y[i] = 0
                water_y[i] = 0

    else:
        ground_y = [0.0] * n_points
        structure_y = [dam_h * 0.5] * n_points
        water_y = [0.0] * n_points

    return {
        "site_id": site.id,
        "site_type": site_type,
        "x_axis": x,
        "ground_profile": ground_y,
        "structure_profile": structure_y,
        "water_profile": water_y,
        "max_height": dam_h * 1.2,
        "min_height": -dam_h if site_type in ('井', '塘') else 0,
        "dam_height": dam_h,
    }


# ==============================================
# 批量操作
# ==============================================

@app.post("/batch/restore")
def batch_restore(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """批量触发复原计算"""
    pubsub.publish(channels.BATCH_RESTORE_REQUESTED, {
        "event_type": "batch_restore_request",
    })
    total = db.query(WaterHeritageSite).count()
    return {"status": "accepted", "total_sites": total, "message": "批量复原已提交"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.HYDRO_RECONSTRUCTOR_PORT)
