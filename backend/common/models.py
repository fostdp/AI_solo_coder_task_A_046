"""
数据模型模块
所有微服务共享的SQLAlchemy模型
"""
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, Boolean, ForeignKey, CheckConstraint, JSON
)
from sqlalchemy.sql import func
from geoalchemy2 import Geometry
from common.database import Base


class DynastyDict(Base):
    __tablename__ = "dynasty_dict"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    start_year = Column(Integer, nullable=False)
    end_year = Column(Integer, nullable=False)
    order = Column(Integer, nullable=False, unique=True)


class WaterHeritageSite(Base):
    __tablename__ = "water_heritage_sites"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, index=True)
    dynasty = Column(String(100), nullable=False)
    dynasty_order = Column(Integer, nullable=False, index=True)
    longitude = Column(Float, nullable=False)
    latitude = Column(Float, nullable=False)
    geom = Column(Geometry(geometry_type='POINT', srid=4326), index=True)
    site_type = Column(String(20), nullable=False, index=True)
    dam_height = Column(Float)
    canal_length = Column(Float)
    irrigation_area = Column(Float, nullable=False)
    preservation_status = Column(String(20), nullable=False, index=True)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("site_type IN ('渠', '堰', '陂', '塘', '井')", name='ck_site_type'),
        CheckConstraint("preservation_status IN ('完好', '部分损毁', '完全废弃')", name='ck_preservation_status'),
    )


class PaleoHydrologyData(Base):
    __tablename__ = "paleo_hydrology_data"

    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False, index=True)
    region = Column(String(100), nullable=False, index=True)
    rainfall = Column(Float, nullable=False)
    runoff = Column(Float, nullable=False)
    temperature = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FunctionalRestoration(Base):
    __tablename__ = "functional_restoration"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("water_heritage_sites.id", ondelete="CASCADE"), nullable=False, unique=True)
    original_irrigation_capacity = Column(Float, nullable=False)
    actual_irrigation_capacity = Column(Float, nullable=False)
    water_supply_range_geom = Column(Geometry(geometry_type='POLYGON', srid=4326), index=True)
    supply_population = Column(Integer)
    restoration_notes = Column(Text)
    parameter_estimation = Column(JSON)
    uncertainty_analysis = Column(JSON)
    calculated_at = Column(DateTime(timezone=True), server_default=func.now())


class SustainabilityAssessment(Base):
    __tablename__ = "sustainability_assessment"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("water_heritage_sites.id", ondelete="CASCADE"), nullable=False, unique=True)
    structural_score = Column(Float, nullable=False)
    hydrological_score = Column(Float, nullable=False)
    economic_score = Column(Float, nullable=False)
    cultural_score = Column(Float, nullable=False)
    environmental_score = Column(Float, nullable=False)
    total_score = Column(Float, nullable=False, index=True)
    grade = Column(String(2), nullable=False)
    restoration_potential = Column(Boolean, nullable=False)
    assessment_details = Column(JSON)
    group_decision_info = Column(JSON)
    assessed_at = Column(DateTime(timezone=True), server_default=func.now())


class AlertRecord(Base):
    __tablename__ = "alert_records"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("water_heritage_sites.id", ondelete="CASCADE"), nullable=False)
    alert_type = Column(String(50), nullable=False)
    alert_level = Column(String(20), nullable=False, index=True)
    message = Column(Text, nullable=False)
    mqtt_topic = Column(String(200))
    mqtt_message_id = Column(String(100))
    mqtt_status = Column(String(20))
    acknowledged = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        CheckConstraint("alert_level IN ('低', '中', '高', '紧急')", name='ck_alert_level'),
    )
