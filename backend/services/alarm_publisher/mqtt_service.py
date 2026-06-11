"""
MQTT告警推送服务 v3.0
告警推送专用微服务，通过Redis Pub/Sub接收告警事件，通过MQTT推送
特性：持久会话、离线队列、指数退避重连、死信队列、QoS 1
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import time
import uuid
import json
import logging
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Any
from datetime import datetime

import paho.mqtt.client as mqtt

from common.config import settings

logger = logging.getLogger("mqtt_service")


class MessageStatus(Enum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class MQTTMessage:
    message_id: str
    topic: str
    payload: Dict[str, Any]
    qos: int = 1
    status: MessageStatus = MessageStatus.PENDING
    retry_count: int = 0
    created_at: float = field(default_factory=time.time)
    published_at: Optional[float] = None
    ttl: int = 3600  # 1小时过期


class MQTTService:
    """MQTT告警推送服务（单例）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._client = None
        self._connected = False
        self._client_id = f"heritage-alarm-publisher-{uuid.uuid4().hex[:8]}"

        # 消息管理
        self._pending_messages: Dict[str, MQTTMessage] = {}
        self._dead_letter_queue: List[MQTTMessage] = []
        self._max_pending = 1000
        self._max_dead_letter = 500
        self._max_retry = 5

        # 重连管理
        self._reconnect_delay = 2
        self._max_reconnect_delay = 120
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 50
        self._reconnect_timer = None
        self._stop = False

        # 回调
        self._on_published_callbacks = []

        self._init_client()

    def _init_client(self):
        """初始化MQTT客户端（持久会话）"""
        self._client = mqtt.Client(
            client_id=self._client_id,
            clean_session=False,
            protocol=mqtt.MQTTv311
        )

        if settings.MQTT_USERNAME:
            self._client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)

        # 遗嘱消息
        self._client.will_set(
            topic=f"{settings.MQTT_TOPIC_PREFIX}/status",
            payload=json.dumps({"status": "offline", "service": "alarm_publisher"}),
            qos=1,
            retain=True
        )

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_publish = self._on_publish

        self._start()

    def _start(self):
        """启动连接"""
        try:
            self._client.connect_async(
                settings.MQTT_HOST,
                settings.MQTT_PORT,
                keepalive=60
            )
            self._client.loop_start()
            logger.info(f"MQTT客户端启动，client_id={self._client_id}")
        except Exception as e:
            logger.error(f"MQTT连接启动失败: {e}")
            self._schedule_reconnect()

    def _on_connect(self, client, userdata, flags, rc):
        """连接成功回调"""
        if rc == 0:
            self._connected = True
            self._reconnect_attempts = 0
            self._reconnect_delay = 2
            logger.info("MQTT连接成功")

            # 上线通知
            client.publish(
                topic=f"{settings.MQTT_TOPIC_PREFIX}/status",
                payload=json.dumps({"status": "online", "service": "alarm_publisher"}),
                qos=1,
                retain=True
            )

            # 补发离线消息
            self._flush_pending_messages()
        else:
            logger.error(f"MQTT连接失败，返回码={rc}")
            self._schedule_reconnect()

    def _on_disconnect(self, client, userdata, rc):
        """断开连接回调"""
        self._connected = False
        logger.warning(f"MQTT连接断开，返回码={rc}")
        if not self._stop:
            self._schedule_reconnect()

    def _on_publish(self, client, userdata, mid):
        """发布成功回调（QoS>0时触发）"""
        # 查找对应消息并标记为已发布
        for msg_id, msg in list(self._pending_messages.items()):
            if msg.status == MessageStatus.PUBLISHING:
                msg.status = MessageStatus.PUBLISHED
                msg.published_at = time.time()
                logger.debug(f"消息发布成功: {msg.topic}")

                for callback in self._on_published_callbacks:
                    try:
                        callback(msg)
                    except Exception as e:
                        logger.error(f"发布回调异常: {e}")

                del self._pending_messages[msg_id]
                break

    def _schedule_reconnect(self):
        """指数退避重连"""
        if self._stop:
            return

        self._reconnect_attempts += 1
        if self._reconnect_attempts > self._max_reconnect_attempts:
            logger.error("达到最大重连次数，放弃重连")
            return

        delay = min(self._reconnect_delay * (2 ** (self._reconnect_attempts - 1)),
                    self._max_reconnect_delay)
        # 随机抖动
        import random
        delay = delay * (0.8 + random.random() * 0.4)

        logger.info(f"计划重连 (第{self._reconnect_attempts}次)，延迟={delay:.1f}s")

        if self._reconnect_timer:
            self._reconnect_timer.cancel()

        self._reconnect_timer = threading.Timer(delay, self._do_reconnect)
        self._reconnect_timer.daemon = True
        self._reconnect_timer.start()

    def _do_reconnect(self):
        """执行重连"""
        try:
            logger.info("正在重连MQTT...")
            self._client.reconnect()
        except Exception as e:
            logger.error(f"重连失败: {e}")
            self._schedule_reconnect()

    def _flush_pending_messages(self):
        """重连后补发待发送消息"""
        if not self._pending_messages:
            return

        expired_count = 0
        count = 0
        now = time.time()

        for msg_id, msg in list(self._pending_messages.items()):
            # 检查过期
            if now - msg.created_at > msg.ttl:
                msg.status = MessageStatus.EXPIRED
                self._move_to_dead_letter(msg)
                del self._pending_messages[msg_id]
                expired_count += 1
                continue

            try:
                self._publish_message(msg)
                count += 1
            except Exception as e:
                logger.error(f"补发消息失败 {msg_id}: {e}")
                msg.retry_count += 1
                if msg.retry_count >= self._max_retry:
                    msg.status = MessageStatus.FAILED
                    self._move_to_dead_letter(msg)
                    del self._pending_messages[msg_id]

        logger.info(f"补发消息 {count} 条，过期 {expired_count} 条")

    def _move_to_dead_letter(self, msg: MQTTMessage):
        """移入死信队列"""
        self._dead_letter_queue.append(msg)
        if len(self._dead_letter_queue) > self._max_dead_letter:
            self._dead_letter_queue.pop(0)
        logger.warning(f"消息移入死信队列: {msg.topic} (reason={msg.status.value})")

    def _publish_message(self, msg: MQTTMessage):
        """实际发布消息"""
        msg.status = MessageStatus.PUBLISHING
        payload_str = json.dumps(msg.payload, ensure_ascii=False)
        self._client.publish(msg.topic, payload_str, qos=msg.qos)

    def publish_alert(self, site_id: int, site_name: str, alert_type: str,
                      alert_level: str, coordinates: Dict[str, float] = None,
                      extra_data: Dict = None) -> Dict[str, Any]:
        """
        发布告警消息
        Returns: 消息状态信息
        """
        msg_id = str(uuid.uuid4())
        topic = f"{settings.MQTT_TOPIC_PREFIX}/{site_id}"

        payload = {
            "message_id": msg_id,
            "site_id": site_id,
            "site_name": site_name,
            "alert_type": alert_type,
            "alert_level": alert_level,
            "timestamp": datetime.now().isoformat(),
            "coordinates": coordinates or {},
            "extra": extra_data or {},
        }

        msg = MQTTMessage(
            message_id=msg_id,
            topic=topic,
            payload=payload,
            qos=1,
        )

        # 队列超限检查
        if len(self._pending_messages) >= self._max_pending:
            msg.status = MessageStatus.FAILED
            self._move_to_dead_letter(msg)
            return {
                "message_id": msg_id,
                "status": "failed",
                "reason": "pending_queue_full",
                "topic": topic,
            }

        self._pending_messages[msg_id] = msg

        # 已连接则立即发送
        if self._connected:
            try:
                self._publish_message(msg)
            except Exception as e:
                logger.error(f"发送告警失败: {e}")
                msg.status = MessageStatus.PENDING  # 留在队列等重连
        else:
            logger.warning(f"MQTT未连接，告警已加入待发送队列: {site_name}")

        return {
            "message_id": msg_id,
            "status": msg.status.value,
            "topic": topic,
            "pending_count": len(self._pending_messages),
        }

    def get_message_status(self, message_id: str) -> Optional[Dict]:
        """查询消息状态"""
        msg = self._pending_messages.get(message_id)
        if msg:
            return {
                "message_id": message_id,
                "topic": msg.topic,
                "status": msg.status.value,
                "retry_count": msg.retry_count,
                "created_at": datetime.fromtimestamp(msg.created_at).isoformat(),
                "age": time.time() - msg.created_at,
            }

        # 死信队列里找
        for dm in self._dead_letter_queue:
            if dm.message_id == message_id:
                return {
                    "message_id": message_id,
                    "topic": dm.topic,
                    "status": dm.status.value,
                    "in_dead_letter": True,
                    "created_at": datetime.fromtimestamp(dm.created_at).isoformat(),
                }

        return None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def pending_count(self) -> int:
        return len(self._pending_messages)

    @property
    def dead_letter_count(self) -> int:
        return len(self._dead_letter_queue)

    def get_dead_letter_queue(self, limit: int = 100) -> List[Dict]:
        """获取死信队列"""
        msgs = self._dead_letter_queue[-limit:]
        return [
            {
                "message_id": m.message_id,
                "topic": m.topic,
                "status": m.status.value,
                "retry_count": m.retry_count,
                "created_at": datetime.fromtimestamp(m.created_at).isoformat(),
                "payload": m.payload,
            }
            for m in reversed(msgs)
        ]

    def clear_dead_letter(self):
        """清空死信队列"""
        count = len(self._dead_letter_queue)
        self._dead_letter_queue.clear()
        return {"cleared": count}

    def reconnect(self):
        """手动触发重连"""
        if self._connected:
            self._client.disconnect()
        else:
            self._schedule_reconnect()
        return {"status": "reconnecting"}

    def close(self):
        self._stop = True
        if self._reconnect_timer:
            self._reconnect_timer.cancel()
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
        logger.info("MQTT服务已关闭")


mqtt_service = MQTTService()
