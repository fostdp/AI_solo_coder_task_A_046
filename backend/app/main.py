from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from geoalchemy2.shape import to_shape, from_shape
from shapely.geometry import mapping, shape
import json
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.config import settings
from app.database import get_db, Base, engine
from app.models import (
    WaterHeritageSite, PaleoHydrologyData, FunctionalRestoration,
    SustainabilityAssessment, AlertRecord, DynastyDict
)
from app.schemas import (
    WaterHeritageSiteCreate, WaterHeritageSiteUpdate, WaterHeritageSiteResponse,
    PaleoHydrologyDataResponse, FunctionalRestorationResponse,
    SustainabilityAssessmentResponse, AlertRecordResponse,
    AHPCriteriaWeights, SiteComprehensiveInfo, StatisticsResponse
)
from app.services import (
    MQTTService, HydraulicRestorationModel, AHPSustainabilityAssessment
)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    description="古代水利工程遗迹功能复原与可持续性评估系统 API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

mqtt_service = MQTTService()
restoration_model = HydraulicRestorationModel()
ahp_assessment = AHPSustainabilityAssessment()


def _check_and_trigger_alert(db: Session, site: WaterHeritageSite, old_status: Optional[str] = None):
    if site.preservation_status == '完全废弃' and (old_status != '完全废弃' or old_status is None):
        alert_data = {
            'site_id': site.id,
            'site_name': site.name,
            'alert_type': '文物保护预警',
            'alert_level': '紧急',
            'timestamp': datetime.now().isoformat(),
            'coordinates': {'lng': site.longitude, 'lat': site.latitude}
        }
        mqtt_topic = f"heritage/alert/{site.id}"
        mqtt_result = mqtt_service.publish_alert(site.id, alert_data)
        mqtt_published = mqtt_result['status'] in ('publishing', 'published')
        mqtt_message_id = mqtt_result.get('message_id')

        db_alert = AlertRecord(
            site_id=site.id,
            alert_type='文物保护预警',
            alert_level='紧急',
            message=f'水利遗迹【{site.name}】保存状态已恶化为完全废弃，请立即采取保护措施！',
            mqtt_topic=mqtt_topic if mqtt_published else None,
            mqtt_message_id=mqtt_message_id
        )
        db.add(db_alert)
        db.commit()
        return db_alert
    return None


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": "1.0.0",
        "status": "running",
        "mqtt_connected": mqtt_service.is_connected()
    }


@app.get("/api/sites", response_model=List[Dict[str, Any]])
async def list_sites(
    skip: int = 0,
    limit: int = 500,
    site_type: Optional[str] = None,
    dynasty: Optional[str] = None,
    preservation_status: Optional[str] = None,
    min_irrigation: Optional[float] = None,
    max_irrigation: Optional[float] = None,
    bbox: Optional[str] = Query(None, description="格式: min_lng,min_lat,max_lng,max_lat"),
    db: Session = Depends(get_db)
):
    query = db.query(WaterHeritageSite)
    if site_type:
        query = query.filter(WaterHeritageSite.site_type == site_type)
    if dynasty:
        query = query.filter(WaterHeritageSite.dynasty == dynasty)
    if preservation_status:
        query = query.filter(WaterHeritageSite.preservation_status == preservation_status)
    if min_irrigation:
        query = query.filter(WaterHeritageSite.irrigation_area >= min_irrigation)
    if max_irrigation:
        query = query.filter(WaterHeritageSite.irrigation_area <= max_irrigation)
    if bbox:
        coords = list(map(float, bbox.split(',')))
        if len(coords) == 4:
            min_lng, min_lat, max_lng, max_lat = coords
            query = query.filter(
                and_(
                    WaterHeritageSite.longitude >= min_lng,
                    WaterHeritageSite.longitude <= max_lng,
                    WaterHeritageSite.latitude >= min_lat,
                    WaterHeritageSite.latitude <= max_lat
                )
            )

    sites = query.offset(skip).limit(limit).all()
    features = []
    for s in sites:
        feat = {
            "type": "Feature",
            "id": s.id,
            "geometry": {"type": "Point", "coordinates": [s.longitude, s.latitude]},
            "properties": {
                "id": s.id,
                "name": s.name,
                "dynasty": s.dynasty,
                "dynasty_order": s.dynasty_order,
                "site_type": s.site_type,
                "dam_height": s.dam_height,
                "canal_length": s.canal_length,
                "irrigation_area": s.irrigation_area,
                "preservation_status": s.preservation_status,
                "description": s.description
            }
        }
        features.append(feat)

    return features


@app.get("/api/sites/geojson")
async def get_sites_geojson(
    with_assessment: bool = True,
    with_restoration: bool = True,
    db: Session = Depends(get_db)
):
    query = db.query(WaterHeritageSite)
    sites = query.all()

    features = []
    for s in sites:
        properties = {
            "id": s.id,
            "name": s.name,
            "dynasty": s.dynasty,
            "dynasty_order": s.dynasty_order,
            "site_type": s.site_type,
            "dam_height": s.dam_height,
            "canal_length": s.canal_length,
            "irrigation_area": s.irrigation_area,
            "preservation_status": s.preservation_status,
            "description": s.description
        }

        if with_assessment:
            assessment = db.query(SustainabilityAssessment).filter(
                SustainabilityAssessment.site_id == s.id
            ).first()
            if assessment:
                properties['total_score'] = assessment.total_score
                properties['grade'] = assessment.grade
                properties['restoration_potential'] = assessment.restoration_potential

        if with_restoration:
            restoration = db.query(FunctionalRestoration).filter(
                FunctionalRestoration.site_id == s.id
            ).first()
            if restoration:
                properties['original_irrigation_capacity'] = restoration.original_irrigation_capacity
                properties['actual_irrigation_capacity'] = restoration.actual_irrigation_capacity

        feat = {
            "type": "Feature",
            "id": s.id,
            "geometry": {"type": "Point", "coordinates": [s.longitude, s.latitude]},
            "properties": properties
        }
        features.append(feat)

    return {"type": "FeatureCollection", "features": features}


@app.get("/api/sites/{site_id}", response_model=WaterHeritageSiteResponse)
async def get_site(site_id: int, db: Session = Depends(get_db)):
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹未找到")
    return site


@app.post("/api/sites", response_model=WaterHeritageSiteResponse)
async def create_site(
    site_data: WaterHeritageSiteCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    geom_wkt = f'SRID=4326;POINT({site_data.longitude} {site_data.latitude})'
    db_site = WaterHeritageSite(
        **site_data.model_dump(),
        geom=from_shape(
            __import__('shapely.geometry', fromlist=['Point']).Point(
                site_data.longitude, site_data.latitude
            ), srid=4326
        )
    )
    db.add(db_site)
    db.commit()
    db.refresh(db_site)

    _check_and_trigger_alert(db, db_site)

    return db_site


@app.put("/api/sites/{site_id}", response_model=WaterHeritageSiteResponse)
async def update_site(
    site_id: int,
    site_data: WaterHeritageSiteUpdate,
    db: Session = Depends(get_db)
):
    db_site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not db_site:
        raise HTTPException(status_code=404, detail="遗迹未找到")

    old_status = db_site.preservation_status
    update_data = site_data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(db_site, key, value)

    if 'longitude' in update_data or 'latitude' in update_data:
        from shapely.geometry import Point as ShapelyPoint
        db_site.geom = from_shape(
            ShapelyPoint(db_site.longitude, db_site.latitude), srid=4326
        )

    db.commit()
    db.refresh(db_site)

    _check_and_trigger_alert(db, db_site, old_status)

    return db_site


@app.delete("/api/sites/{site_id}")
async def delete_site(site_id: int, db: Session = Depends(get_db)):
    db_site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not db_site:
        raise HTTPException(status_code=404, detail="遗迹未找到")
    db.delete(db_site)
    db.commit()
    return {"message": "删除成功"}


@app.get("/api/sites/{site_id}/comprehensive")
async def get_site_comprehensive(site_id: int, db: Session = Depends(get_db)):
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹未找到")

    restoration = db.query(FunctionalRestoration).filter(
        FunctionalRestoration.site_id == site_id
    ).first()

    assessment = db.query(SustainabilityAssessment).filter(
        SustainabilityAssessment.site_id == site_id
    ).first()

    result = {
        'site': {
            'id': site.id, 'name': site.name, 'dynasty': site.dynasty,
            'dynasty_order': site.dynasty_order, 'longitude': site.longitude,
            'latitude': site.latitude, 'site_type': site.site_type,
            'dam_height': site.dam_height, 'canal_length': site.canal_length,
            'irrigation_area': site.irrigation_area,
            'preservation_status': site.preservation_status,
            'description': site.description,
            'created_at': site.created_at, 'updated_at': site.updated_at
        },
        'restoration': None,
        'assessment': None
    }

    if restoration:
        geom_obj = None
        if restoration.water_supply_range_geom:
            try:
                shp = to_shape(restoration.water_supply_range_geom)
                geom_obj = mapping(shp)
            except Exception:
                pass
        result['restoration'] = {
            'id': restoration.id,
            'site_id': restoration.site_id,
            'original_irrigation_capacity': restoration.original_irrigation_capacity,
            'actual_irrigation_capacity': restoration.actual_irrigation_capacity,
            'water_supply_range_geom': geom_obj,
            'supply_population': restoration.supply_population,
            'restoration_notes': restoration.restoration_notes,
            'calculated_at': restoration.calculated_at
        }

    if assessment:
        result['assessment'] = {
            'id': assessment.id,
            'site_id': assessment.site_id,
            'structural_score': assessment.structural_score,
            'hydrological_score': assessment.hydrological_score,
            'economic_score': assessment.economic_score,
            'cultural_score': assessment.cultural_score,
            'environmental_score': assessment.environmental_score,
            'total_score': assessment.total_score,
            'grade': assessment.grade,
            'restoration_potential': assessment.restoration_potential,
            'assessment_details': assessment.assessment_details,
            'assessed_at': assessment.assessed_at
        }

    return result


@app.get("/api/sites/{site_id}/hydrology-trend")
async def get_hydrology_trend(
    site_id: int,
    region: Optional[str] = Query(None, description="区域名称"),
    db: Session = Depends(get_db)
):
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹未找到")

    regions = ['中原地区', '关中地区', '江南地区', '巴蜀地区',
               '岭南地区', '江淮地区', '山东地区', '河北地区',
               '河东地区', '河西地区', '辽东地区', '滇黔地区']

    if region and region in regions:
        target_regions = [region]
    else:
        idx = hash(site.name) % len(regions)
        target_regions = [regions[idx]]

    hydro_data = db.query(PaleoHydrologyData).filter(
        PaleoHydrologyData.region.in_(target_regions)
    ).order_by(PaleoHydrologyData.year).all()

    trend = []
    for h in hydro_data:
        trend.append({
            'year': h.year,
            'rainfall': h.rainfall,
            'runoff': h.runoff,
            'temperature': h.temperature,
            'region': h.region
        })

    return {
        'site_id': site_id,
        'site_name': site.name,
        'regions_used': target_regions,
        'trend': trend
    }


@app.post("/api/sites/{site_id}/restore")
async def restore_site_function(site_id: int, db: Session = Depends(get_db)):
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹未找到")

    regions = ['中原地区', '关中地区', '江南地区', '巴蜀地区',
               '岭南地区', '江淮地区', '山东地区', '河北地区',
               '河东地区', '河西地区', '辽东地区', '滇黔地区']
    region = regions[hash(site.name) % len(regions)]

    hydro_data = db.query(PaleoHydrologyData).filter(
        PaleoHydrologyData.region == region
    ).all()

    restoration_result = restoration_model.restore_site(site, hydro_data)

    existing = db.query(FunctionalRestoration).filter(
        FunctionalRestoration.site_id == site_id
    ).first()

    from shapely.geometry import shape as shapely_shape
    geom_db = None
    if restoration_result['water_supply_range_geom']:
        try:
            poly = shapely_shape(restoration_result['water_supply_range_geom'])
            geom_db = from_shape(poly, srid=4326)
        except Exception:
            pass

    if existing:
        existing.original_irrigation_capacity = restoration_result['original_irrigation_capacity']
        existing.actual_irrigation_capacity = restoration_result['actual_irrigation_capacity']
        existing.water_supply_range_geom = geom_db
        existing.supply_population = restoration_result['supply_population']
        existing.restoration_notes = restoration_result['restoration_notes']
    else:
        new_restoration = FunctionalRestoration(
            site_id=site_id,
            original_irrigation_capacity=restoration_result['original_irrigation_capacity'],
            actual_irrigation_capacity=restoration_result['actual_irrigation_capacity'],
            water_supply_range_geom=geom_db,
            supply_population=restoration_result['supply_population'],
            restoration_notes=restoration_result['restoration_notes']
        )
        db.add(new_restoration)

    db.commit()

    return restoration_result


@app.get("/api/sites/{site_id}/cross-section")
async def get_cross_section(site_id: int, db: Session = Depends(get_db)):
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹未找到")

    section_data = _generate_cross_section(site)

    return {
        'site_id': site_id,
        'site_name': site.name,
        'site_type': site.site_type,
        'cross_section': section_data
    }


def _generate_cross_section(site: WaterHeritageSite) -> Dict[str, Any]:
    n_points = 50
    section_type = site.site_type
    dam_height = site.dam_height or (5.0 if section_type != '井' else 15.0)
    canal_length = site.canal_length or (20.0 if section_type in ['渠', '堰'] else 5.0)

    profiles = {
        '渠': {
            'width_surface': 8 + canal_length * 0.05,
            'width_bottom': 3 + canal_length * 0.02,
            'depth': min(max(1, dam_height * 0.4), 8),
            'side_slope': 1.5,
            'water_level': 0.7
        },
        '堰': {
            'crest_elevation': dam_height,
            'crest_width': max(2, dam_height * 0.15),
            'upstream_slope': 1.0,
            'downstream_slope': 1.5,
            'base_width': dam_height * 3,
            'water_depth_upstream': dam_height * 0.8,
            'water_depth_downstream': dam_height * 0.3
        },
        '陂': {
            'dam_height': dam_height,
            'dam_top_width': max(3, dam_height * 0.2),
            'upstream_slope': 2.5,
            'downstream_slope': 2.0,
            'base_width': dam_height * 5,
            'water_depth': dam_height * 0.75,
            'bottom_elevation': -dam_height * 0.1
        },
        '塘': {
            'max_depth': dam_height,
            'diameter': 30 + dam_height * 5,
            'side_slope': 3.0,
            'water_level': 0.85,
            'bottom_width': 10 + dam_height * 2
        },
        '井': {
            'depth': dam_height,
            'diameter': 1.2,
            'water_depth': dam_height * 0.6,
            'wall_thickness': 0.3,
            'stone_wall_depth': dam_height * 0.8
        }
    }

    profile = profiles.get(section_type, profiles['渠'])
    x = list(range(n_points + 1))
    y_ground = []
    y_structure = []
    y_water = []

    if section_type == '渠':
        w_s = profile['width_surface']
        w_b = profile['width_bottom']
        d = profile['depth']
        for i in range(n_points + 1):
            xi = (i / n_points) * (w_s + 10) - (w_s + 10) / 2
            if abs(xi) <= w_b / 2:
                yg = -d
                ys = -d
                yw = -d * (1 - profile['water_level'])
            elif abs(xi) <= w_s / 2:
                side_x = (abs(xi) - w_b / 2) / ((w_s - w_b) / 2)
                yg = -d * (1 - side_x)
                ys = yg
                yw = max(-d * (1 - profile['water_level']), yg)
            else:
                yg = min(2, abs(xi) - w_s / 2) * 0.3
                ys = yg
                yw = None
            y_ground.append(yg)
            y_structure.append(ys)
            y_water.append(yw if yw is not None and yw >= yg else None)

    elif section_type in ['堰', '陂']:
        h = profile['dam_height'] if section_type == '陂' else profile['crest_elevation']
        bw = profile['base_width']
        tw = profile['dam_top_width'] if section_type == '陂' else profile['crest_width']
        uss = profile['upstream_slope'] if section_type == '陂' else profile['upstream_slope']
        dss = profile['downstream_slope'] if section_type == '陂' else profile['downstream_slope']
        wd = profile.get('water_depth', profile.get('water_depth_upstream', h * 0.8))

        total_width = bw * 3
        center_x = 0
        us_start = -bw / 2
        crest_left = -tw / 2
        crest_right = tw / 2
        ds_end = bw / 2

        for i in range(n_points + 1):
            xi = (i / n_points) * total_width - total_width / 2
            if xi < us_start:
                dist = us_start - xi
                yg = -min(h * 0.3, dist * 0.05)
                ys = yg
                yw = wd * 0.9
            elif xi < crest_left:
                ratio = (xi - us_start) / (crest_left - us_start)
                yg = -h * 0.1
                ys = -h * 0.1 + h * ratio
                yw = wd * 0.9
            elif xi <= crest_right:
                yg = -h * 0.1
                ys = h
                yw = None
            elif xi <= ds_end:
                ratio = (ds_end - xi) / (ds_end - crest_right)
                yg = -h * 0.1
                ys = -h * 0.1 + h * ratio
                yw = None
            else:
                dist = xi - ds_end
                yg = -h * 0.1 + min(h * 0.3, dist * 0.05)
                ys = yg
                yw = None

            y_ground.append(round(yg, 2))
            y_structure.append(round(ys, 2))
            y_water.append(round(yw, 2) if yw is not None and yw < ys else None)

    elif section_type == '塘':
        md = profile['max_depth']
        diam = profile['diameter']
        ss = profile['side_slope']
        bw = profile['bottom_width']
        half = diam / 2
        wl = md * profile['water_level']

        for i in range(n_points + 1):
            xi = (i / n_points) * diam * 1.5 - diam * 0.75
            abs_x = abs(xi)
            if abs_x <= bw / 2:
                yg = -md
                ys = -md
                yw = -wl
            elif abs_x <= half:
                ratio = (abs_x - bw / 2) / (half - bw / 2)
                yg = -md * (1 - ratio * 0.9)
                ys = yg
                yw = max(-wl, yg) if yg < -wl * 0.1 else None
            else:
                yg = (abs_x - half) * 0.1
                ys = yg
                yw = None
            y_ground.append(round(yg, 2))
            y_structure.append(round(ys, 2))
            y_water.append(round(yw, 2) if yw is not None and yw >= ys else None)

    elif section_type == '井':
        d = profile['depth']
        dia = profile['diameter']
        wt = profile['wall_thickness']
        wd = profile['water_depth']
        swd = profile['stone_wall_depth']

        total_width = dia * 6
        for i in range(n_points + 1):
            xi = (i / n_points) * total_width - total_width / 2
            abs_x = abs(xi)

            if abs_x <= dia / 2:
                yg = -d
                ys = None
                yw = -(d - wd)
            elif abs_x <= dia / 2 + wt:
                depth_ratio = 1.0 if abs_x <= dia / 2 + wt else 0
                yg = -d * 0.95
                ys = 0 if yg == 0 else -swd
                if ys is not None and abs(abs_x - (dia / 2 + wt / 2)) < 0.01:
                    ys = -swd
                yw = None
            else:
                yg = 0
                ys = 0
                yw = None

            y_ground.append(round(yg, 2))
            y_structure.append(round(ys, 2) if ys is not None else None)
            y_water.append(round(yw, 2) if yw is not None else None)

    x_labels = [round((i / n_points) * 100 - 50, 1) for i in range(n_points + 1)]

    return {
        'type': section_type,
        'profile_params': profile,
        'x_normalized': x,
        'x_percent': x_labels,
        'ground_profile': y_ground,
        'structure_profile': y_structure,
        'water_profile': y_water,
        'max_depth': max([abs(y) for y in y_ground if y is not None]),
        'max_height': max([y for y in y_structure if y is not None] + [0])
    }


@app.post("/api/sites/{site_id}/assess")
async def assess_site_sustainability(
    site_id: int,
    weights: Optional[AHPCriteriaWeights] = None,
    db: Session = Depends(get_db)
):
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹未找到")

    regions = ['中原地区', '关中地区', '江南地区', '巴蜀地区',
               '岭南地区', '江淮地区', '山东地区', '河北地区',
               '河东地区', '河西地区', '辽东地区', '滇黔地区']
    region = regions[hash(site.name) % len(regions)]

    modern_hydro = db.query(PaleoHydrologyData).filter(
        and_(PaleoHydrologyData.region == region, PaleoHydrologyData.year >= 1900)
    ).all()

    ancient_hydro = db.query(PaleoHydrologyData).filter(
        and_(PaleoHydrologyData.region == region, PaleoHydrologyData.year < 1900)
    ).all()

    existing_restoration = db.query(FunctionalRestoration).filter(
        FunctionalRestoration.site_id == site_id
    ).first()

    if existing_restoration:
        original_capacity = existing_restoration.original_irrigation_capacity
    else:
        hydro_all = ancient_hydro + modern_hydro
        restoration_temp = restoration_model.restore_site(site, hydro_all)
        original_capacity = restoration_temp['original_irrigation_capacity']

    custom_weights = None
    if weights:
        custom_weights = {
            'structural': weights.structural,
            'hydrological': weights.hydrological,
            'economic': weights.economic,
            'cultural': weights.cultural,
            'environmental': weights.environmental
        }

    assessment_result = ahp_assessment.assess_site(
        site, modern_hydro, ancient_hydro, original_capacity, custom_weights
    )

    existing = db.query(SustainabilityAssessment).filter(
        SustainabilityAssessment.site_id == site_id
    ).first()

    if existing:
        for key, value in assessment_result.items():
            setattr(existing, key, value)
    else:
        new_assessment = SustainabilityAssessment(
            site_id=site_id,
            **assessment_result
        )
        db.add(new_assessment)

    db.commit()

    return assessment_result


@app.post("/api/restore-all")
async def restore_all_sites(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    sites = db.query(WaterHeritageSite).all()
    success_count = 0

    regions = ['中原地区', '关中地区', '江南地区', '巴蜀地区',
               '岭南地区', '江淮地区', '山东地区', '河北地区',
               '河东地区', '河西地区', '辽东地区', '滇黔地区']

    from shapely.geometry import shape as shapely_shape

    for site in sites:
        try:
            region = regions[hash(site.name) % len(regions)]
            hydro_data = db.query(PaleoHydrologyData).filter(
                PaleoHydrologyData.region == region
            ).all()

            result = restoration_model.restore_site(site, hydro_data)

            existing = db.query(FunctionalRestoration).filter(
                FunctionalRestoration.site_id == site.id
            ).first()

            geom_db = None
            if result['water_supply_range_geom']:
                try:
                    poly = shapely_shape(result['water_supply_range_geom'])
                    geom_db = from_shape(poly, srid=4326)
                except Exception:
                    pass

            if existing:
                existing.original_irrigation_capacity = result['original_irrigation_capacity']
                existing.actual_irrigation_capacity = result['actual_irrigation_capacity']
                existing.water_supply_range_geom = geom_db
                existing.supply_population = result['supply_population']
                existing.restoration_notes = result['restoration_notes']
            else:
                new_r = FunctionalRestoration(
                    site_id=site.id,
                    original_irrigation_capacity=result['original_irrigation_capacity'],
                    actual_irrigation_capacity=result['actual_irrigation_capacity'],
                    water_supply_range_geom=geom_db,
                    supply_population=result['supply_population'],
                    restoration_notes=result['restoration_notes']
                )
                db.add(new_r)

            success_count += 1
            if success_count % 50 == 0:
                db.commit()
        except Exception as e:
            print(f"处理遗迹 {site.id} 失败: {e}")
            continue

    db.commit()

    return {"processed": len(sites), "success": success_count, "message": "功能复原计算完成"}


@app.post("/api/assess-all")
async def assess_all_sites(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    sites = db.query(WaterHeritageSite).all()
    success_count = 0

    regions = ['中原地区', '关中地区', '江南地区', '巴蜀地区',
               '岭南地区', '江淮地区', '山东地区', '河北地区',
               '河东地区', '河西地区', '辽东地区', '滇黔地区']

    for site in sites:
        try:
            region = regions[hash(site.name) % len(regions)]

            modern_hydro = db.query(PaleoHydrologyData).filter(
                and_(PaleoHydrologyData.region == region, PaleoHydrologyData.year >= 1900)
            ).all()
            ancient_hydro = db.query(PaleoHydrologyData).filter(
                and_(PaleoHydrologyData.region == region, PaleoHydrologyData.year < 1900)
            ).all()

            existing_restoration = db.query(FunctionalRestoration).filter(
                FunctionalRestoration.site_id == site.id
            ).first()

            original_capacity = existing_restoration.original_irrigation_capacity if existing_restoration else 50.0

            result = ahp_assessment.assess_site(
                site, modern_hydro, ancient_hydro, original_capacity
            )

            existing = db.query(SustainabilityAssessment).filter(
                SustainabilityAssessment.site_id == site.id
            ).first()

            if existing:
                for key, value in result.items():
                    setattr(existing, key, value)
            else:
                new_a = SustainabilityAssessment(site_id=site.id, **result)
                db.add(new_a)

            success_count += 1
            if success_count % 50 == 0:
                db.commit()
        except Exception as e:
            print(f"评估遗迹 {site.id} 失败: {e}")
            continue

    db.commit()

    return {"processed": len(sites), "success": success_count, "message": "可持续性评估完成"}


@app.get("/api/restoration/supply-ranges")
async def get_supply_ranges_geojson(db: Session = Depends(get_db)):
    restorations = db.query(FunctionalRestoration).filter(
        FunctionalRestoration.water_supply_range_geom.isnot(None)
    ).all()

    features = []
    for r in restorations:
        try:
            shp = to_shape(r.water_supply_range_geom)
            feat = {
                "type": "Feature",
                "id": f"range_{r.site_id}",
                "geometry": mapping(shp),
                "properties": {
                    "site_id": r.site_id,
                    "original_capacity": r.original_irrigation_capacity,
                    "actual_capacity": r.actual_irrigation_capacity,
                    "supply_population": r.supply_population
                }
            }
            features.append(feat)
        except Exception:
            continue

    return {"type": "FeatureCollection", "features": features}


@app.get("/api/hydrology")
async def list_hydrology(
    region: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(PaleoHydrologyData)
    if region:
        query = query.filter(PaleoHydrologyData.region == region)
    if year_start:
        query = query.filter(PaleoHydrologyData.year >= year_start)
    if year_end:
        query = query.filter(PaleoHydrologyData.year <= year_end)
    return query.order_by(PaleoHydrologyData.year, PaleoHydrologyData.region).all()


@app.get("/api/statistics", response_model=StatisticsResponse)
async def get_statistics(db: Session = Depends(get_db)):
    total_sites = db.query(func.count(WaterHeritageSite.id)).scalar() or 0

    by_type_rows = db.query(
        WaterHeritageSite.site_type, func.count(WaterHeritageSite.id)
    ).group_by(WaterHeritageSite.site_type).all()
    by_type = {row[0]: row[1] for row in by_type_rows}

    by_dynasty_rows = db.query(
        WaterHeritageSite.dynasty, func.count(WaterHeritageSite.id)
    ).group_by(WaterHeritageSite.dynasty, WaterHeritageSite.dynasty_order
    ).order_by(WaterHeritageSite.dynasty_order).all()
    by_dynasty = {row[0]: row[1] for row in by_dynasty_rows}

    by_status_rows = db.query(
        WaterHeritageSite.preservation_status, func.count(WaterHeritageSite.id)
    ).group_by(WaterHeritageSite.preservation_status).all()
    by_status = {row[0]: row[1] for row in by_status_rows}

    avg_area = db.query(func.avg(WaterHeritageSite.irrigation_area)).scalar() or 0

    alerts_count = db.query(func.count(AlertRecord.id)).scalar() or 0

    high_potential = db.query(func.count(SustainabilityAssessment.id)).filter(
        SustainabilityAssessment.restoration_potential == True
    ).scalar() or 0

    return StatisticsResponse(
        total_sites=total_sites,
        by_type=by_type,
        by_dynasty=by_dynasty,
        by_status=by_status,
        avg_irrigation_area=round(avg_area, 2),
        alerts_count=alerts_count,
        high_potential_count=high_potential
    )


@app.get("/api/alerts", response_model=List[AlertRecordResponse])
async def list_alerts(
    site_id: Optional[int] = None,
    alert_level: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    query = db.query(AlertRecord).order_by(AlertRecord.created_at.desc())
    if site_id:
        query = query.filter(AlertRecord.site_id == site_id)
    if alert_level:
        query = query.filter(AlertRecord.alert_level == alert_level)
    if acknowledged is not None:
        query = query.filter(AlertRecord.acknowledged == acknowledged)
    return query.limit(limit).all()


@app.put("/api/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(AlertRecord).filter(AlertRecord.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="告警未找到")
    alert.acknowledged = True
    db.commit()
    return {"message": "告警已确认"}


@app.post("/api/mqtt/test-publish")
async def test_mqtt_publish(topic: str, message: Dict[str, Any]):
    success = mqtt_service.publish_custom(topic, message)
    return {"success": success, "topic": topic}


@app.post("/api/import/sites")
async def import_sites_from_json(db: Session = Depends(get_db)):
    import os
    data_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'heritage_sites.json')
    if not os.path.exists(data_path):
        raise HTTPException(status_code=404, detail="数据文件不存在")

    with open(data_path, 'r', encoding='utf-8') as f:
        sites_data = json.load(f)

    from shapely.geometry import Point as ShapelyPoint
    imported = 0
    existing_count = 0

    for sd in sites_data:
        existing = db.query(WaterHeritageSite).filter(
            and_(WaterHeritageSite.name == sd['name'],
                 WaterHeritageSite.dynasty_order == sd['dynasty_order'])
        ).first()
        if existing:
            existing_count += 1
            continue

        db_site = WaterHeritageSite(
            name=sd['name'],
            dynasty=sd['dynasty'],
            dynasty_order=sd['dynasty_order'],
            longitude=sd['longitude'],
            latitude=sd['latitude'],
            site_type=sd['site_type'],
            dam_height=sd['dam_height'],
            canal_length=sd['canal_length'],
            irrigation_area=sd['irrigation_area'],
            preservation_status=sd['preservation_status'],
            description=sd['description'],
            geom=from_shape(ShapelyPoint(sd['longitude'], sd['latitude']), srid=4326)
        )
        db.add(db_site)
        imported += 1

    db.commit()
    return {"imported": imported, "existing_skipped": existing_count, "total": len(sites_data)}


@app.post("/api/import/hydrology")
async def import_hydrology_from_json(db: Session = Depends(get_db)):
    import os
    data_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'hydrology_data.json')
    if not os.path.exists(data_path):
        raise HTTPException(status_code=404, detail="数据文件不存在")

    with open(data_path, 'r', encoding='utf-8') as f:
        hydro_data = json.load(f)

    existing = db.query(func.count(PaleoHydrologyData.id)).scalar() or 0
    if existing > 0:
        return {"message": "水文数据已存在，跳过导入", "existing_count": existing}

    batch_size = 1000
    for i in range(0, len(hydro_data), batch_size):
        batch = hydro_data[i:i + batch_size]
        db_objs = [PaleoHydrologyData(**h) for h in batch]
        db.add_all(db_objs)
        db.commit()

    return {"imported": len(hydro_data), "message": "水文数据导入完成"}


@app.get("/api/dynasties")
async def get_dynasties(db: Session = Depends(get_db)):
    dynasties = db.query(DynastyDict).order_by(DynastyDict.order).all()
    return [{
        'name': d.name,
        'start_year': d.start_year,
        'end_year': d.end_year,
        'order': d.order
    } for d in dynasties]


@app.post("/api/sites/{site_id}/monte-carlo")
async def run_monte_carlo_analysis(
    site_id: int,
    n_simulations: int = Query(1000, description="蒙特卡洛模拟次数"),
    db: Session = Depends(get_db)
):
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹未找到")

    regions = ['中原地区', '关中地区', '江南地区', '巴蜀地区',
               '岭南地区', '江淮地区', '山东地区', '河北地区',
               '河东地区', '河西地区', '辽东地区', '滇黔地区']
    region = regions[hash(site.name) % len(regions)]

    hydro_data = db.query(PaleoHydrologyData).filter(
        PaleoHydrologyData.region == region
    ).all()

    try:
        mc_result = restoration_model.monte_carlo_analysis(
            site, hydro_data, n_simulations=n_simulations
        )

        existing = db.query(FunctionalRestoration).filter(
            FunctionalRestoration.site_id == site_id
        ).first()
        if existing:
            existing.uncertainty_analysis = mc_result

        return {
            "site_id": site_id,
            "site_name": site.name,
            "n_simulations": n_simulations,
            "uncertainty_analysis": mc_result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"蒙特卡洛分析失败: {str(e)}")


@app.get("/api/sites/{site_id}/parameter-estimation")
async def get_parameter_estimation(site_id: int, db: Session = Depends(get_db)):
    site = db.query(WaterHeritageSite).filter(WaterHeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="遗迹未找到")

    try:
        from app.services.restoration_model import ParameterEstimator
        estimator = ParameterEstimator()
        estimated = estimator.estimate_parameters(site)

        existing = db.query(FunctionalRestoration).filter(
            FunctionalRestoration.site_id == site_id
        ).first()
        if existing:
            existing.parameter_estimation = estimated

        return {
            "site_id": site_id,
            "site_name": site.name,
            "parameter_estimation": estimated
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"参数估计失败: {str(e)}")


@app.get("/api/ahp/experts")
async def get_ahp_experts():
    try:
        from app.services.ahp_assessment import AHPGroupDecision
        expert_info = AHPGroupDecision.get_expert_info()
        return {"experts": expert_info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ahp/group-weights")
async def get_ahp_group_weights():
    try:
        from app.services.ahp_assessment import AHPGroupDecision
        group_decision = AHPGroupDecision()
        result = group_decision.get_aggregated_weights()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ahp/check-consistency")
async def check_ahp_consistency(weights: AHPCriteriaWeights):
    try:
        weight_dict = {
            'structural': weights.structural,
            'hydrological': weights.hydrological,
            'economic': weights.economic,
            'cultural': weights.cultural,
            'environmental': weights.environmental
        }
        from app.services.ahp_assessment import AHPGroupDecision
        result = AHPGroupDecision.check_weights_consistency(weight_dict)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mqtt/status")
async def get_mqtt_status():
    info = mqtt_service.get_connection_info()
    return info


@app.get("/api/mqtt/pending-count")
async def get_mqtt_pending_count():
    count = mqtt_service.get_pending_count()
    return count


@app.get("/api/mqtt/messages/{message_id}/status")
async def get_mqtt_message_status(message_id: str):
    status = mqtt_service.get_message_status(message_id)
    if status is None:
        raise HTTPException(status_code=404, detail="消息不存在或已发送完成")
    return status


@app.get("/api/mqtt/dead-letter")
async def get_mqtt_dead_letter(limit: int = 50):
    msgs = mqtt_service.get_dead_letter_messages(limit=limit)
    return {"count": len(msgs), "messages": msgs}


@app.delete("/api/mqtt/dead-letter")
async def clear_mqtt_dead_letter():
    count = mqtt_service.clear_dead_letter()
    return {"cleared": count}


@app.post("/api/mqtt/reconnect")
async def mqtt_manual_reconnect():
    success = mqtt_service.manual_reconnect()
    return {"reconnect_triggered": success}


@app.get("/api/restoration/supply-ranges/simplified")
async def get_simplified_supply_ranges(
    tolerance: float = Query(0.001, description="简化容差（度）"),
    db: Session = Depends(get_db)
):
    restorations = db.query(FunctionalRestoration).filter(
        FunctionalRestoration.water_supply_range_geom.isnot(None)
    ).all()

    features = []
    for r in restorations:
        try:
            from shapely.geometry import mapping as shapely_mapping
            shp = to_shape(r.water_supply_range_geom)
            simplified = shp.simplify(tolerance, preserve_topology=True)

            feat = {
                "type": "Feature",
                "id": f"range_{r.site_id}",
                "geometry": shapely_mapping(simplified),
                "properties": {
                    "site_id": r.site_id,
                    "original_capacity": r.original_irrigation_capacity,
                    "actual_capacity": r.actual_irrigation_capacity,
                    "supply_population": r.supply_population
                }
            }
            features.append(feat)
        except Exception:
            continue

    return {"type": "FeatureCollection", "features": features, "tolerance": tolerance}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
