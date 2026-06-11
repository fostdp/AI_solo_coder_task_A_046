"""
Sustainability Evaluator 微服务
负责：AHP可持续性评估、群决策、一致性检验、修复潜力评分
端口：8003
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import logging
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from common.config import settings, channels
from common.database import get_db, init_db
from common.models import (
    WaterHeritageSite,
    PaleoHydrologyData,
    SustainabilityAssessment,
    FunctionalRestoration,
    DynastyDict,
)
from common.redis_client import pubsub
from common.params.hydraulic_params import REGIONS

from .ahp_assessment import get_assessment, AHPSustainabilityAssessment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sustainability_evaluator")

app = FastAPI(
    title="古代水利工程遗迹-可持续性评估服务",
    description="负责AHP评估、群决策、一致性检验、修复潜力评分",
    version="3.0.0"
)


# ==============================================
# 事件订阅
# ==============================================

def _on_assessment_requested(message: Dict[str, Any]):
    """处理评估请求事件"""
    site_id = message.get('site_id')
    if not site_id:
        return
    logger.info(f"收到评估请求: site_id={site_id}")
    try:
        from common.database import SessionLocal
        db = SessionLocal()
        result = _do_assess(db, site_id)
        db.close()
        if result:
            pubsub.publish(channels.ASSESSMENT_COMPLETED, {
                "event_type": "assessment_completed",
                "site_id": site_id,
                "data": {
                    "total_score": result.total_score,
                    "grade": result.grade,
                    "restoration_potential": result.restoration_potential
                }
            })
    except Exception as e:
        logger.error(f"评估失败 site_id={site_id}: {e}")
        pubsub.publish(channels.ASSESSMENT_FAILED, {
            "event_type": "assessment_failed",
            "site_id": site_id,
            "data": {"error": str(e)}
        })


def _on_restoration_completed(message: Dict[str, Any]):
    """复原完成后自动评估"""
    site_id = message.get('site_id')
    if not site_id:
        return
    logger.info(f"复原完成，自动评估: site_id={site_id}")
    try:
        from common.database import SessionLocal
        db = SessionLocal()
        _do_assess(db, site_id)
        db.close()
    except Exception as e:
        logger.error(f"自动评估失败 site_id={site_id}: {e}")


def _on_batch_assess(message: Dict[str, Any]):
    """批量评估"""
    logger.info("收到批量评估请求")
    try:
        from common.database import SessionLocal
        db = SessionLocal()
        sites = db.query(WaterHeritageSite).all()
        count = 0
        for site in sites:
            try:
                _do_assess(db, site.id)
                count += 1
            except Exception:
                pass
        db.close()
        logger.info(f"批量评估完成: {count}/{len(sites)}")
    except Exception as e:
        logger.error(f"批量评估失败: {e}")


@app.on_event("startup")
async def startup_event():
    logger.info("Sustainability Evaluator 服务启动...")
    try:
        init_db()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.warning(f"数据库初始化异常: {e}")

    # 初始化评估实例
    _ = get_assessment()
    logger.info("AHP评估器初始化完成")

    # 订阅事件
    pubsub.subscribe(channels.ASSESSMENT_REQUESTED, _on_assessment_requested)
    pubsub.subscribe(channels.RESTORATION_COMPLETED, _on_restoration_completed)
    pubsub.subscribe(channels.BATCH_ASSESS_REQUESTED, _on_batch_assess)
    logger.info("Redis Pub/Sub 订阅完成")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "sustainability_evaluator"}


# ==============================================
# 核心：可持续性评估
# ==============================================

def _do_assess(db: Session, site_id: int) -> Optional[SustainabilityAssessment]:
    """执行评估计算"""
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
    hydro_list = hydro_query.all()

    # 复原数据
    restoration = db.query(FunctionalRestoration).filter(
        FunctionalRestoration.site_id == site_id
    ).first()

    # 评估
    assessment = get_assessment()
    result = assessment.assess_site(site, hydro_list, restoration)

    # 保存
    existing = db.query(SustainabilityAssessment).filter(
        SustainabilityAssessment.site_id == site_id
    ).first()

    if existing:
        existing.structural_score = result["structural_score"]
        existing.hydrological_score = result["hydrological_score"]
        existing.economic_score = result["economic_score"]
        existing.cultural_score = result["cultural_score"]
        existing.environmental_score = result["environmental_score"]
        existing.total_score = result["total_score"]
        existing.grade = result["grade"]
        existing.restoration_potential = result["restoration_potential"]
        existing.assessment_details = result["assessment_details"]
        existing.group_decision_info = result["group_decision_info"]
        record = existing
    else:
        record = SustainabilityAssessment(
            site_id=site_id,
            structural_score=result["structural_score"],
            hydrological_score=result["hydrological_score"],
            economic_score=result["economic_score"],
            cultural_score=result["cultural_score"],
            environmental_score=result["environmental_score"],
            total_score=result["total_score"],
            grade=result["grade"],
            restoration_potential=result["restoration_potential"],
            assessment_details=result["assessment_details"],
            group_decision_info=result["group_decision_info"],
        )
        db.add(record)

    db.commit()
    db.refresh(record)

    logger.info(f"评估完成: {site.name} (id={site_id}) 得分={result['total_score']:.1f} 等级={result['grade']}")
    return record


@app.post("/assess/{site_id}")
def assess_site(site_id: int, background_tasks: BackgroundTasks,
                async_mode: bool = True, db: Session = Depends(get_db)):
    """触发可持续性评估"""
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹不存在")

    if async_mode:
        pubsub.publish(channels.ASSESSMENT_REQUESTED, {
            "event_type": "assessment_request",
            "site_id": site_id,
        })
        return {"status": "accepted", "site_id": site_id, "message": "评估计算已提交"}
    else:
        record = _do_assess(db, site_id)
        if not record:
            raise HTTPException(status_code=500, detail="评估失败")
        return _format_assessment_response(record)


def _format_assessment_response(record: SustainabilityAssessment) -> Dict:
    return {
        "id": record.id,
        "site_id": record.site_id,
        "structural_score": record.structural_score,
        "hydrological_score": record.hydrological_score,
        "economic_score": record.economic_score,
        "cultural_score": record.cultural_score,
        "environmental_score": record.environmental_score,
        "total_score": record.total_score,
        "grade": record.grade,
        "restoration_potential": record.restoration_potential,
        "assessment_details": record.assessment_details,
        "group_decision_info": record.group_decision_info,
        "assessed_at": record.assessed_at,
    }


@app.get("/assess/{site_id}")
def get_assessment_result(site_id: int, db: Session = Depends(get_db)):
    """获取评估结果"""
    record = db.query(SustainabilityAssessment).filter(
        SustainabilityAssessment.site_id == site_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="未找到评估结果")
    return _format_assessment_response(record)


# ==============================================
# AHP 专家权重管理
# ==============================================

@app.get("/experts")
def get_experts():
    """获取所有专家配置"""
    assessment = get_assessment()
    return {"experts": assessment.group_decision.experts}


@app.get("/aggregated-weights")
def get_aggregated_weights():
    """获取聚合后的权重"""
    assessment = get_assessment()
    return {
        "weights": assessment.aggregated_weights,
        "group_info": assessment.group_info,
    }


@app.post("/check-consistency")
def check_consistency(weights: Dict[str, float]):
    """检查权重一致性"""
    assessment = get_assessment()
    return assessment.check_matrix_consistency(weights)


@app.post("/correct-consistency")
def correct_consistency(weights: Dict[str, float]):
    """迭代修正一致性"""
    assessment = get_assessment()
    return assessment.correct_matrix(weights)


@app.get("/criteria")
def get_criteria():
    """获取评价准则列表"""
    return {"criteria": CRITERIA}


# ==============================================
# 统计与排行
# ==============================================

@app.get("/rankings")
def get_rankings(by: str = "total", limit: int = 20,
                 min_grade: Optional[str] = None,
                 db: Session = Depends(get_db)):
    """评估排行榜"""
    from sqlalchemy import desc

    query = db.query(SustainabilityAssessment).join(
        WaterHeritageSite, SustainabilityAssessment.site_id == WaterHeritageSite.id
    )

    if min_grade:
        grade_order = ['S', 'A', 'B', 'C', 'D', 'E']
        min_idx = grade_order.index(min_grade) if min_grade in grade_order else 5
        valid_grades = grade_order[:min_idx + 1]
        query = query.filter(SustainabilityAssessment.grade.in_(valid_grades))

    sort_field = {
        "total": SustainabilityAssessment.total_score,
        "structural": SustainabilityAssessment.structural_score,
        "hydrological": SustainabilityAssessment.hydrological_score,
        "economic": SustainabilityAssessment.economic_score,
        "cultural": SustainabilityAssessment.cultural_score,
        "environmental": SustainabilityAssessment.environmental_score,
    }.get(by, SustainabilityAssessment.total_score)

    records = query.order_by(desc(sort_field)).limit(limit).all()
    results = []
    for r in records:
        site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == r.site_id).first()
        results.append({
            "site_id": r.site_id,
            "site_name": site.name if site else "",
            "site_type": site.site_type if site else "",
            "dynasty": site.dynasty if site else "",
            "total_score": r.total_score,
            "grade": r.grade,
            "preservation_status": site.preservation_status if site else "",
        })

    return {"rank_by": by, "count": len(results), "results": results}


# ==============================================
# 批量操作
# ==============================================

@app.post("/batch/assess")
def batch_assess(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """批量评估"""
    pubsub.publish(channels.BATCH_ASSESS_REQUESTED, {
        "event_type": "batch_assess_request",
    })
    total = db.query(WaterHeritageSite).count()
    return {"status": "accepted", "total_sites": total, "message": "批量评估已提交"}


# 导入 CRITERIA
from common.params.ahp_params import CRITERIA

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.SUSTAINABILITY_EVALUATOR_PORT)
