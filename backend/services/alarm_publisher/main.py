"""
Alarm Publisher 微服务
负责：告警管理、MQTT推送、消息状态查询、死信队列管理
端口：8004
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import logging
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime

from common.config import settings, channels
from common.database import get_db, init_db
from common.models import AlertRecord, WaterHeritageSite
from common.redis_client import pubsub

from .mqtt_service import mqtt_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("alarm_publisher")

app = FastAPI(
    title="古代水利工程遗迹-告警推送服务",
    description="负责告警管理、MQTT推送、消息状态查询、死信队列管理",
    version="3.0.0"
)


# ==============================================
# 事件订阅
# ==============================================

def _on_alert_triggered(message: Dict[str, Any]):
    """处理告警触发事件"""
    data = message.get('data', {})
    site_id = message.get('site_id')
    if not site_id:
        return

    logger.info(f"收到告警触发事件: site_id={site_id}, type={data.get('alert_type')}")

    site_name = data.get('site_name', f'遗迹#{site_id}')
    alert_type = data.get('alert_type', '文物保护预警')
    alert_level = data.get('alert_level', '中')
    coordinates = {
        'longitude': data.get('longitude'),
        'latitude': data.get('latitude'),
    }

    # 推送MQTT
    result = mqtt_service.publish_alert(
        site_id=site_id,
        site_name=site_name,
        alert_type=alert_type,
        alert_level=alert_level,
        coordinates=coordinates,
    )

    # 保存告警记录
    try:
        from common.database import SessionLocal
        db = SessionLocal()

        alert = AlertRecord(
            site_id=site_id,
            alert_type=alert_type,
            alert_level=alert_level,
            message=f"{site_name}: {alert_type} - 状态已恶化",
            mqtt_topic=result.get('topic'),
            mqtt_message_id=result.get('message_id'),
            mqtt_status=result.get('status'),
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        db.close()

        # 发布告警已发布事件
        pubsub.publish(channels.ALERT_PUBLISHED, {
            "event_type": "alert_published",
            "site_id": site_id,
            "alert_id": alert.id,
            "data": {
                "alert_type": alert_type,
                "alert_level": alert_level,
                "mqtt_status": result.get('status'),
            }
        })

        logger.warning(f"告警已记录: {site_name} (id={alert.id})")
    except Exception as e:
        logger.error(f"保存告警记录失败: {e}")


def _on_heritage_updated(message: Dict[str, Any]):
    """检查遗迹更新是否触发告警"""
    data = message.get('data', {})
    site_id = message.get('site_id')
    if not data.get('preservation_changed'):
        return

    old_status = data.get('old_status')
    new_status = data.get('new_status')
    if old_status != '完全废弃' and new_status == '完全废弃':
        # 已在 heritage_loader 中直接触发 ALERT_TRIGGERED
        logger.info(f"状态恶化为完全废弃，告警已在上游触发: site_id={site_id}")


@app.on_event("startup")
async def startup_event():
    logger.info("Alarm Publisher 服务启动...")
    try:
        init_db()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.warning(f"数据库初始化异常: {e}")

    # MQTT服务已单例化
    logger.info(f"MQTT服务状态: 连接={mqtt_service.is_connected}")

    # 订阅事件
    pubsub.subscribe(channels.ALERT_TRIGGERED, _on_alert_triggered)
    pubsub.subscribe(channels.HERITAGE_UPDATED, _on_heritage_updated)
    logger.info("Redis Pub/Sub 订阅完成")


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "alarm_publisher",
        "mqtt_connected": mqtt_service.is_connected,
    }


# ==============================================
# MQTT 状态
# ==============================================

@app.get("/mqtt/status")
def get_mqtt_status():
    """获取MQTT连接状态"""
    return {
        "connected": mqtt_service.is_connected,
        "client_id": mqtt_service._client_id if hasattr(mqtt_service, '_client_id') else None,
        "pending_messages": mqtt_service.pending_count,
        "dead_letter_count": mqtt_service.dead_letter_count,
        "reconnect_attempts": mqtt_service._reconnect_attempts if hasattr(mqtt_service, '_reconnect_attempts') else 0,
    }


@app.post("/mqtt/reconnect")
def mqtt_reconnect():
    """手动触发MQTT重连"""
    result = mqtt_service.reconnect()
    return result


@app.get("/mqtt/pending-count")
def get_pending_count():
    """待发送消息统计"""
    return {
        "pending": mqtt_service.pending_count,
        "dead_letter": mqtt_service.dead_letter_count,
    }


@app.get("/mqtt/messages/{message_id}/status")
def get_message_status(message_id: str):
    """查询单条消息状态"""
    status = mqtt_service.get_message_status(message_id)
    if not status:
        raise HTTPException(status_code=404, detail="消息不存在")
    return status


@app.get("/mqtt/dead-letter")
def get_dead_letter(limit: int = Query(100, le=500)):
    """获取死信队列"""
    messages = mqtt_service.get_dead_letter_queue(limit)
    return {"count": len(messages), "messages": messages}


@app.delete("/mqtt/dead-letter")
def clear_dead_letter():
    """清空死信队列"""
    result = mqtt_service.clear_dead_letter()
    return result


# ==============================================
# 告警记录 CRUD
# ==============================================

@app.get("/alerts")
def list_alerts(
    site_id: Optional[int] = None,
    alert_level: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """告警记录列表"""
    from sqlalchemy import desc

    query = db.query(AlertRecord)

    if site_id:
        query = query.filter(AlertRecord.site_id == site_id)
    if alert_level:
        query = query.filter(AlertRecord.alert_level == alert_level)
    if acknowledged is not None:
        query = query.filter(AlertRecord.acknowledged == acknowledged)
    if start_time:
        query = query.filter(AlertRecord.created_at >= start_time)
    if end_time:
        query = query.filter(AlertRecord.created_at <= end_time)

    alerts = query.order_by(desc(AlertRecord.created_at)).offset(skip).limit(limit).all()
    results = []
    for a in alerts:
        site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == a.site_id).first()
        results.append({
            "id": a.id,
            "site_id": a.site_id,
            "site_name": site.name if site else "",
            "alert_type": a.alert_type,
            "alert_level": a.alert_level,
            "message": a.message,
            "mqtt_topic": a.mqtt_topic,
            "mqtt_message_id": a.mqtt_message_id,
            "mqtt_status": a.mqtt_status,
            "acknowledged": a.acknowledged,
            "created_at": a.created_at,
        })
    return results


@app.get("/alerts/{alert_id}")
def get_alert(alert_id: int, db: Session = Depends(get_db)):
    """获取单条告警"""
    alert = db.query(AlertRecord).filter(AlertRecord.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")

    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == alert.site_id).first()
    return {
        "id": alert.id,
        "site_id": alert.site_id,
        "site_name": site.name if site else "",
        "alert_type": alert.alert_type,
        "alert_level": alert.alert_level,
        "message": alert.message,
        "mqtt_topic": alert.mqtt_topic,
        "mqtt_message_id": alert.mqtt_message_id,
        "mqtt_status": alert.mqtt_status,
        "acknowledged": alert.acknowledged,
        "created_at": alert.created_at,
    }


@app.put("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int, db: Session = Depends(get_db)):
    """确认告警"""
    alert = db.query(AlertRecord).filter(AlertRecord.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")

    alert.acknowledged = True
    db.commit()
    db.refresh(alert)
    return {"status": "ok", "acknowledged": True, "alert_id": alert_id}


# ==============================================
# 手动触发告警（测试用）
# ==============================================

@app.post("/alerts/test")
def test_alert(site_id: int, alert_type: str = "测试告警",
               alert_level: str = "中", db: Session = Depends(get_db)):
    """手动触发告警（测试用）"""
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹不存在")

    # 通过事件总线触发
    pubsub.publish(channels.ALERT_TRIGGERED, {
        "event_type": "manual_test_alert",
        "site_id": site_id,
        "data": {
            "site_name": site.name,
            "alert_type": alert_type,
            "alert_level": alert_level,
            "longitude": site.longitude,
            "latitude": site.latitude,
        }
    })

    return {"status": "triggered", "site_id": site_id, "message": f"测试告警已触发: {site.name}"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.ALARM_PUBLISHER_PORT)
