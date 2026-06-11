import json
import logging
import time
import threading
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum
import paho.mqtt.client as mqtt
from app.config import settings

logger = logging.getLogger(__name__)


class MessageStatus(Enum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class MQTTMessage:
    """待发送MQTT消息"""
    id: str
    topic: str
    payload: str
    qos: int = 1
    retain: bool = False
    status: MessageStatus = MessageStatus.PENDING
    created_at: float = field(default_factory=time.time)
    published_at: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 10
    ttl: int = 3600  # 消息存活时间（秒）
    mid: Optional[int] = None
    on_success: Optional[Callable] = None
    on_failure: Optional[Callable] = None


class MQTTService:
    """
    MQTT消息服务 v2.0
    - 持久会话 (clean_session=False)：断连后Broker保存订阅状态
    - 离线消息缓存：本地队列，断连期间消息缓存，重连后自动补发
    - 指数退避重连：断线自动重连，避免频繁冲击
    - 消息状态追踪：可查询每条消息的发送状态
    - QoS 1支持：至少一次送达
    - 死信队列：重试失败的消息转入死信
    """

    _instance: Optional['MQTTService'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        self._initialized = True

        self._client: Optional[mqtt.Client] = None
        self._connected: bool = False
        self._connecting: bool = False

        self._pending_messages: Dict[str, MQTTMessage] = {}
        self._dead_letter_queue: List[MQTTMessage] = []
        self._message_counter: int = 0

        self._reconnect_attempts: int = 0
        self._max_reconnect_attempts: int = 50
        self._base_reconnect_delay: float = 2.0
        self._max_reconnect_delay: float = 120.0

        self._lock = threading.RLock()
        self._message_id_lock = threading.Lock()

        self._callbacks: Dict[str, Callable] = {}

        self._init_client()

    def _init_client(self):
        try:
            client_id = f"water_heritage_backend_{settings.POSTGRES_DB}"
            self._client = mqtt.Client(
                client_id=client_id,
                clean_session=False,
                protocol=mqtt.MQTTv311
            )

            self._client.max_inflight_messages_set(50)
            self._client.message_retry_set(5)

            if settings.MQTT_USERNAME and settings.MQTT_PASSWORD:
                self._client.username_pw_set(
                    settings.MQTT_USERNAME,
                    settings.MQTT_PASSWORD
                )

            will_topic = f"{settings.MQTT_TOPIC_PREFIX}/status"
            will_payload = json.dumps({
                "status": "offline",
                "service": "water_heritage_backend",
                "timestamp": time.time()
            }, ensure_ascii=False)
            self._client.will_set(
                will_topic,
                payload=will_payload,
                qos=1,
                retain=True
            )

            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_publish = self._on_publish
            self._client.on_message = self._on_message

            self._connect()
        except Exception as e:
            logger.error(f"MQTT客户端初始化失败: {e}")
            self._connected = False

    def _connect(self):
        if self._connecting or self._connected:
            return

        self._connecting = True
        try:
            logger.info(f"正在连接MQTT Broker: {settings.MQTT_HOST}:{settings.MQTT_PORT}")
            self._client.connect_async(
                settings.MQTT_HOST,
                settings.MQTT_PORT,
                keepalive=60
            )
            self._client.loop_start()
        except Exception as e:
            logger.error(f"MQTT连接发起失败: {e}")
            self._connecting = False
            self._schedule_reconnect()

    def _schedule_reconnect(self):
        """调度重连（指数退避）"""
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.error("已达到最大重连次数，停止重连尝试")
            return

        self._reconnect_attempts += 1
        delay = min(
            self._base_reconnect_delay * (2 ** (self._reconnect_attempts - 1)),
            self._max_reconnect_delay
        )
        delay = delay * (0.8 + 0.4 * (time.time() % 1))

        logger.info(
            f"第 {self._reconnect_attempts} 次重连将在 {delay:.1f} 秒后进行"
        )

        timer = threading.Timer(delay, self._reconnect)
        timer.daemon = True
        timer.start()

    def _reconnect(self):
        if self._connected:
            return

        self._connecting = False
        try:
            logger.info("正在尝试重新连接MQTT...")
            self._client.reconnect()
        except Exception as e:
            logger.warning(f"重连失败: {e}")
            self._schedule_reconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            self._connecting = False
            self._reconnect_attempts = 0

            session_present = flags.get('session present', False)
            logger.info(
                f"MQTT已连接 | Broker: {settings.MQTT_HOST}:{settings.MQTT_PORT} "
                f"| 会话状态: {'持久会话已恢复' if session_present else '新会话'}"
            )

            status_topic = f"{settings.MQTT_TOPIC_PREFIX}/status"
            status_payload = json.dumps({
                "status": "online",
                "service": "water_heritage_backend",
                "timestamp": time.time(),
                "pending_messages": len(self._pending_messages)
            }, ensure_ascii=False)
            client.publish(status_topic, payload=status_payload, qos=1, retain=True)

            self._flush_pending_messages()

            if 'on_connect' in self._callbacks:
                try:
                    self._callbacks['on_connect'](session_present)
                except Exception as e:
                    logger.error(f"连接回调执行失败: {e}")
        else:
            self._connected = False
            self._connecting = False
            error_msgs = {
                1: "协议版本不支持",
                2: "客户端标识符被拒绝",
                3: "服务器不可用",
                4: "用户名或密码错误",
                5: "未授权"
            }
            logger.error(f"MQTT连接失败，错误码 {rc}: {error_msgs.get(rc, '未知错误')}")
            self._schedule_reconnect()

    def _on_disconnect(self, client, userdata, rc):
        was_connected = self._connected
        self._connected = False
        self._connecting = False

        if rc == 0:
            logger.info("MQTT已正常断开连接")
        else:
            logger.warning(
                f"MQTT意外断开连接 (rc={rc})，将自动重连"
            )
            if was_connected:
                self._schedule_reconnect()

    def _on_publish(self, client, userdata, mid):
        with self._lock:
            for msg_id, msg in list(self._pending_messages.items()):
                if msg.mid == mid and msg.status == MessageStatus.PUBLISHING:
                    msg.status = MessageStatus.PUBLISHED
                    msg.published_at = time.time()

                    logger.debug(
                        f"MQTT消息发布成功 | MID: {mid} | "
                        f"主题: {msg.topic} | "
                        f"重试: {msg.retry_count}次"
                    )

                    if msg.on_success:
                        try:
                            msg.on_success(msg)
                        except Exception as e:
                            logger.error(f"消息成功回调异常: {e}")

                    del self._pending_messages[msg_id]
                    break

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            logger.debug(f"收到MQTT消息 | 主题: {topic} | 负载: {payload[:100]}")

            callback_key = f"message_{topic}"
            if callback_key in self._callbacks:
                self._callbacks[callback_key](topic, payload)
        except Exception as e:
            logger.error(f"处理MQTT消息异常: {e}")

    def _flush_pending_messages(self):
        """重连后补发所有待发送消息"""
        if not self._pending_messages:
            return

        count = len(self._pending_messages)
        logger.info(f"开始补发离线消息，共 {count} 条")

        success_count = 0
        failed_count = 0

        with self._lock:
            for msg_id, msg in list(self._pending_messages.items()):
                if msg.status == MessageStatus.PENDING or msg.status == MessageStatus.FAILED:
                    if self._is_message_expired(msg):
                        msg.status = MessageStatus.EXPIRED
                        self._dead_letter_queue.append(msg)
                        del self._pending_messages[msg_id]
                        failed_count += 1
                        continue

                    result = self._do_publish(msg)
                    if result:
                        success_count += 1
                    else:
                        failed_count += 1

        logger.info(
            f"离线消息补发完成 | 成功: {success_count} | "
            f"失败: {failed_count} | 剩余: {len(self._pending_messages)}"
        )

    def _is_message_expired(self, msg: MQTTMessage) -> bool:
        return (time.time() - msg.created_at) > msg.ttl

    def _generate_message_id(self) -> str:
        with self._message_id_lock:
            self._message_counter += 1
            return f"msg_{int(time.time())}_{self._message_counter}"

    def _do_publish(self, msg: MQTTMessage) -> bool:
        """实际执行消息发布"""
        if not self._connected:
            return False

        try:
            msg.status = MessageStatus.PUBLISHING
            msg.retry_count += 1

            result = self._client.publish(
                msg.topic,
                payload=msg.payload,
                qos=msg.qos,
                retain=msg.retain
            )

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                msg.mid = result.mid
                return True
            elif result.rc == mqtt.MQTT_ERR_NO_CONN:
                msg.status = MessageStatus.FAILED
                return False
            else:
                logger.warning(f"MQTT发布返回错误码: {result.rc}")
                msg.status = MessageStatus.FAILED
                return False

        except Exception as e:
            logger.error(f"MQTT消息发布异常: {e}")
            msg.status = MessageStatus.FAILED
            return False

    def is_connected(self) -> bool:
        return self._connected

    def publish_alert(self, site_id: int, alert_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        发布告警消息
        返回消息状态信息，包含message_id和当前状态
        """
        topic = f"{settings.MQTT_TOPIC_PREFIX}/{site_id}"

        payload_data = {
            **alert_data,
            "alert_type": alert_data.get('alert_type', '文物保护预警'),
            "timestamp": time.time(),
            "site_id": site_id
        }
        payload = json.dumps(payload_data, ensure_ascii=False, default=str)

        msg_id = self._generate_message_id()
        msg = MQTTMessage(
            id=msg_id,
            topic=topic,
            payload=payload,
            qos=1,
            retain=False,
            max_retries=20,
            ttl=7200
        )

        with self._lock:
            self._pending_messages[msg_id] = msg

        if self._connected:
            success = self._do_publish(msg)
            if not success:
                msg.status = MessageStatus.PENDING
                logger.warning(f"告警消息进入离线队列: site_id={site_id}, msg_id={msg_id}")
        else:
            msg.status = MessageStatus.PENDING
            logger.warning(f"MQTT未连接，告警已加入离线队列: site_id={site_id}, msg_id={msg_id}")

        logger.info(
            f"告警消息 | 状态: {msg.status.value} | "
            f"主题: {topic} | "
            f"内容: {alert_data.get('message', '')[:50]}..."
        )

        return {
            "message_id": msg_id,
            "status": msg.status.value,
            "topic": topic,
            "created_at": msg.created_at,
            "queued": not self._connected
        }

    def publish_custom(self, topic: str, message: Dict[str, Any],
                       qos: int = 1, retain: bool = False) -> Dict[str, Any]:
        """发布自定义消息"""
        payload = json.dumps(message, ensure_ascii=False, default=str)

        msg_id = self._generate_message_id()
        msg = MQTTMessage(
            id=msg_id,
            topic=topic,
            payload=payload,
            qos=qos,
            retain=retain
        )

        with self._lock:
            self._pending_messages[msg_id] = msg

        if self._connected:
            self._do_publish(msg)
        else:
            msg.status = MessageStatus.PENDING

        return {
            "message_id": msg_id,
            "status": msg.status.value,
            "topic": topic
        }

    def get_message_status(self, message_id: str) -> Optional[Dict[str, Any]]:
        """查询消息发送状态"""
        with self._lock:
            msg = self._pending_messages.get(message_id)
            if msg:
                return {
                    "id": msg.id,
                    "topic": msg.topic,
                    "status": msg.status.value,
                    "created_at": msg.created_at,
                    "published_at": msg.published_at,
                    "retry_count": msg.retry_count
                }
        return None

    def get_pending_count(self) -> Dict[str, int]:
        """获取待发送消息统计"""
        with self._lock:
            pending = sum(
                1 for m in self._pending_messages.values()
                if m.status in (MessageStatus.PENDING, MessageStatus.FAILED)
            )
            publishing = sum(
                1 for m in self._pending_messages.values()
                if m.status == MessageStatus.PUBLISHING
            )
            dead = len(self._dead_letter_queue)

        return {
            "pending": pending,
            "publishing": publishing,
            "dead_letter": dead,
            "total": len(self._pending_messages)
        }

    def get_dead_letter_messages(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取死信队列消息"""
        with self._lock:
            msgs = self._dead_letter_queue[-limit:]
            return [
                {
                    "id": m.id,
                    "topic": m.topic,
                    "created_at": m.created_at,
                    "retry_count": m.retry_count
                }
                for m in msgs
            ]

    def clear_dead_letter(self) -> int:
        """清空死信队列"""
        with self._lock:
            count = len(self._dead_letter_queue)
            self._dead_letter_queue.clear()
            return count

    def subscribe(self, topic: str, callback: Callable[[str, str], None]) -> bool:
        """订阅主题"""
        if not self._connected:
            return False

        try:
            self._client.subscribe(topic, qos=1)
            self._callbacks[f"message_{topic}"] = callback
            logger.info(f"已订阅主题: {topic}")
            return True
        except Exception as e:
            logger.error(f"订阅失败: {e}")
            return False

    def register_connect_callback(self, callback: Callable[[bool], None]):
        """注册连接成功回调"""
        self._callbacks['on_connect'] = callback

    def get_connection_info(self) -> Dict[str, Any]:
        """获取连接信息"""
        return {
            "connected": self._connected,
            "connecting": self._connecting,
            "host": settings.MQTT_HOST,
            "port": settings.MQTT_PORT,
            "topic_prefix": settings.MQTT_TOPIC_PREFIX,
            "reconnect_attempts": self._reconnect_attempts,
            "pending_messages": self.get_pending_count()
        }

    def manual_reconnect(self) -> bool:
        """手动触发重连"""
        if self._connected:
            return True

        self._reconnect_attempts = 0
        self._reconnect()
        return True

    def disconnect(self):
        if self._client and self._connected:
            status_topic = f"{settings.MQTT_TOPIC_PREFIX}/status"
            status_payload = json.dumps({
                "status": "offline",
                "service": "water_heritage_backend",
                "timestamp": time.time(),
                "reason": "normal_shutdown"
            }, ensure_ascii=False)

            try:
                self._client.publish(
                    status_topic,
                    payload=status_payload,
                    qos=1,
                    retain=True
                )
            except Exception:
                pass

            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False
            logger.info("MQTT已正常断开连接")

    def __del__(self):
        try:
            self.disconnect()
        except Exception:
            pass
