"""
Redis Pub/Sub 客户端
微服务间异步通信的消息总线
"""
import json
import time
import uuid
import logging
from typing import Callable, Dict, Any, Optional, List
import redis
from common.config import settings, channels

logger = logging.getLogger(__name__)


class RedisPubSub:
    """Redis Pub/Sub 消息总线"""

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

        self._redis = None
        self._pubsub = None
        self._callbacks: Dict[str, List[Callable]] = {}
        self._running = False
        self._thread = None

        self._connect()

    def _connect(self):
        try:
            self._redis = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                password=settings.REDIS_PASSWORD,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True
            )
            self._redis.ping()
            logger.info("Redis连接成功")
        except Exception as e:
            logger.warning(f"Redis连接失败: {e}，将使用降级模式")
            self._redis = None

    def is_connected(self) -> bool:
        return self._redis is not None

    def publish(self, channel: str, data: Dict[str, Any]) -> bool:
        """发布消息"""
        if not self._redis:
            logger.warning(f"Redis未连接，跳过发布: {channel}")
            return False

        try:
            message = {
                "message_id": str(uuid.uuid4()),
                "timestamp": time.time(),
                "source": "backend-service",
                **data
            }
            self._redis.publish(channel, json.dumps(message, ensure_ascii=False, default=str))
            logger.debug(f"发布消息到 {channel}: {message.get('event_type', 'unknown')}")
            return True
        except Exception as e:
            logger.error(f"发布消息失败 {channel}: {e}")
            return False

    def subscribe(self, channel: str, callback: Callable[[Dict[str, Any]], None]):
        """订阅频道"""
        if channel not in self._callbacks:
            self._callbacks[channel] = []
        self._callbacks[channel].append(callback)

        if not self._running and self._redis:
            self._start_listening()

    def _start_listening(self):
        """启动监听线程"""
        if not self._redis:
            return

        self._running = True
        self._pubsub = self._redis.pubsub()

        for channel in self._callbacks.keys():
            self._pubsub.subscribe(channel)

        import threading
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info("Redis Pub/Sub 监听已启动")

    def _listen_loop(self):
        """消息监听循环"""
        try:
            for message in self._pubsub.listen():
                if message['type'] != 'message':
                    continue

                channel = message['channel']
                try:
                    data = json.loads(message['data'])
                except json.JSONDecodeError:
                    data = {"raw": message['data']}

                callbacks = self._callbacks.get(channel, [])
                for callback in callbacks:
                    try:
                        callback(data)
                    except Exception as e:
                        logger.error(f"消息回调执行异常 {channel}: {e}")
        except Exception as e:
            logger.error(f"Redis监听异常: {e}")
            self._running = False

    def close(self):
        if self._running:
            self._running = False
            if self._pubsub:
                self._pubsub.close()
        if self._redis:
            self._redis.close()


pubsub = RedisPubSub()
