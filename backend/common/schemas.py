"""
Pydantic Schema 模块
所有微服务共享
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime


class WaterHeritageSiteBase(BaseModel):
    name: str = Field(..., max_length=200)
    dynasty: str = Field(..., max_length=100)
    dynasty_order: int
    longitude: float
    latitude: float
    site_type: str = Field(..., pattern='^(渠|堰|陂|塘|井)$')
    dam_height: Optional[float] = None
    canal_length: Optional[float] = None
    irrigation_area: float
    preservation_status: str = Field(..., pattern='^(完好|部分损毁|完全废弃)$')
    description: Optional[str] = None


class WaterHeritageSiteCreate(WaterHeritageSiteBase):
    pass


class WaterHeritageSiteUpdate(BaseModel):
    name: Optional[str] = None
    dynasty: Optional[str] = None
    dynasty_order: Optional[int] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    site_type: Optional[str] = Field(None, pattern='^(渠|堰|陂|塘|井)$')
    dam_height: Optional[float] = None
    canal_length: Optional[float] = None
    irrigation_area: Optional[float] = None
    preservation_status: Optional[str] = Field(None, pattern='^(完好|部分损毁|完全废弃)$')
    description: Optional[str] = None


class WaterHeritageSiteResponse(WaterHeritageSiteBase):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PaleoHydrologyDataBase(BaseModel):
    year: int
    region: str
    rainfall: float
    runoff: float
    temperature: Optional[float] = None


class PaleoHydrologyDataResponse(PaleoHydrologyDataBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class FunctionalRestorationBase(BaseModel):
    site_id: int
    original_irrigation_capacity: float
    actual_irrigation_capacity: float
    water_supply_range_geom: Optional[dict] = None
    supply_population: Optional[int] = None
    restoration_notes: Optional[str] = None
    parameter_estimation: Optional[dict] = None
    uncertainty_analysis: Optional[dict] = None


class FunctionalRestorationResponse(FunctionalRestorationBase):
    id: int
    calculated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SustainabilityAssessmentBase(BaseModel):
    site_id: int
    structural_score: float
    hydrological_score: float
    economic_score: float
    cultural_score: float
    environmental_score: float
    total_score: float
    grade: str
    restoration_potential: bool
    assessment_details: Optional[dict] = None
    group_decision_info: Optional[dict] = None


class SustainabilityAssessmentResponse(SustainabilityAssessmentBase):
    id: int
    assessed_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AlertRecordBase(BaseModel):
    site_id: int
    alert_type: str
    alert_level: str = Field(..., pattern='^(低|中|高|紧急)$')
    message: str
    mqtt_topic: Optional[str] = None


class AlertRecordResponse(AlertRecordBase):
    id: int
    acknowledged: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AHPCriteriaWeights(BaseModel):
    structural: float = 0.30
    hydrological: float = 0.25
    economic: float = 0.15
    cultural: float = 0.15
    environmental: float = 0.15


class SiteComprehensiveInfo(BaseModel):
    site: WaterHeritageSiteResponse
    restoration: Optional[FunctionalRestorationResponse] = None
    assessment: Optional[SustainabilityAssessmentResponse] = None


class StatisticsResponse(BaseModel):
    total_sites: int
    by_type: dict
    by_dynasty: dict
    by_status: dict
    avg_irrigation_area: float
    alerts_count: int
    high_potential_count: int


class EventMessage(BaseModel):
    """Redis Pub/Sub 事件消息格式"""
    event_type: str
    site_id: Optional[int] = None
    data: Optional[Dict[str, Any]] = None
    timestamp: float
    source: str
    message_id: str
