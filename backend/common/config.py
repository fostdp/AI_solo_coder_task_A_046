"""
统一配置模块
所有微服务共享此配置
"""
from pydantic_settings import BaseSettings
from typing import Optional, List


class Settings(BaseSettings):
    APP_NAME: str = "古代水利工程遗迹功能复原与可持续性评估系统"
    DEBUG: bool = False
    ENV: str = "development"

    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "water_heritage"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    MQTT_HOST: str = "localhost"
    MQTT_PORT: int = 1883
    MQTT_USERNAME: Optional[str] = None
    MQTT_PASSWORD: Optional[str] = None
    MQTT_TOPIC_PREFIX: str = "heritage/alert"

    CORS_ORIGINS: List[str] = ["*"]

    GATEWAY_PORT: int = 8000
    HERITAGE_LOADER_PORT: int = 8001
    HYDRO_RECONSTRUCTOR_PORT: int = 8002
    SUSTAINABILITY_EVALUATOR_PORT: int = 8003
    ALARM_PUBLISHER_PORT: int = 8004

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()


DATABASE_URL = (
    f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)

REDIS_URL = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"


class ChannelNames:
    """Redis Pub/Sub 频道名称"""
    HERITAGE_IMPORTED = "heritage:imported"
    HERITAGE_UPDATED = "heritage:updated"
    HERITAGE_DELETED = "heritage:deleted"

    RESTORATION_REQUESTED = "restoration:requested"
    RESTORATION_COMPLETED = "restoration:completed"
    RESTORATION_FAILED = "restoration:failed"

    ASSESSMENT_REQUESTED = "assessment:requested"
    ASSESSMENT_COMPLETED = "assessment:completed"
    ASSESSMENT_FAILED = "assessment:failed"

    ALERT_TRIGGERED = "alert:triggered"
    ALERT_PUBLISHED = "alert:published"

    BATCH_RESTORE_REQUESTED = "batch:restore:requested"
    BATCH_ASSESS_REQUESTED = "batch:assess:requested"


channels = ChannelNames()
