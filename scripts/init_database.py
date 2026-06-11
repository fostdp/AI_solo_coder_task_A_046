#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库初始化脚本 - 自动创建表结构、导入模拟数据
"""

import os
import sys
import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from geoalchemy2.shape import from_shape
from shapely.geometry import Point

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.database import Base, engine, SessionLocal
from app.models import (
    WaterHeritageSite, PaleoHydrologyData, FunctionalRestoration,
    SustainabilityAssessment, AlertRecord, DynastyDict
)
from app.services.restoration_model import HydraulicRestorationModel
from app.services.ahp_assessment import AHPSustainabilityAssessment


def init_tables():
    print("=" * 60)
    print("  正在创建数据库表结构...")
    print("=" * 60)

    try:
        Base.metadata.create_all(bind=engine)
        print("✅ 数据库表结构创建完成")
        return True
    except Exception as e:
        print(f"❌ 创建表失败: {e}")
        print("   请确认PostgreSQL和PostGIS已正确安装并连接")
        return False


def init_dynasties(db: Session):
    print("\n📜 正在初始化朝代字典...")

    dynasties = [
        {'name': '春秋', 'start_year': -770, 'end_year': -476, 'order': 1},
        {'name': '战国', 'start_year': -475, 'end_year': -221, 'order': 2},
        {'name': '秦', 'start_year': -221, 'end_year': -206, 'order': 3},
        {'name': '西汉', 'start_year': -202, 'end_year': 8, 'order': 4},
        {'name': '东汉', 'start_year': 25, 'end_year': 220, 'order': 5},
        {'name': '三国', 'start_year': 220, 'end_year': 280, 'order': 6},
        {'name': '西晋', 'start_year': 265, 'end_year': 316, 'order': 7},
        {'name': '东晋', 'start_year': 317, 'end_year': 420, 'order': 8},
        {'name': '南北朝', 'start_year': 420, 'end_year': 589, 'order': 9},
        {'name': '隋', 'start_year': 581, 'end_year': 618, 'order': 10},
        {'name': '唐', 'start_year': 618, 'end_year': 907, 'order': 11},
        {'name': '五代', 'start_year': 907, 'end_year': 960, 'order': 12},
        {'name': '北宋', 'start_year': 960, 'end_year': 1127, 'order': 13},
        {'name': '南宋', 'start_year': 1127, 'end_year': 1279, 'order': 14},
        {'name': '元', 'start_year': 1271, 'end_year': 1368, 'order': 15},
        {'name': '明', 'start_year': 1368, 'end_year': 1644, 'order': 16},
        {'name': '清', 'start_year': 1644, 'end_year': 1912, 'order': 17},
    ]

    try:
        existing = db.query(DynastyDict).count()
        if existing > 0:
            print(f"  ℹ️  朝代数据已存在 ({existing}条)，跳过")
            return

        for d in dynasties:
            db.add(DynastyDict(**d))
        db.commit()
        print(f"✅ 成功导入 {len(dynasties)} 个朝代")
    except Exception as e:
        db.rollback()
        print(f"❌ 导入朝代失败: {e}")


def import_hydrology_data(db: Session, data_path: str):
    print("\n💧 正在导入古代水文重建数据...")

    try:
        if not os.path.exists(data_path):
            print(f"  ❌ 数据文件不存在: {data_path}")
            print("  请先运行: python scripts/generate_data.py")
            return

        with open(data_path, 'r', encoding='utf-8') as f:
            hydro_data = json.load(f)

        existing = db.query(PaleoHydrologyData).count()
        if existing > 0:
            print(f"  ℹ️  水文数据已存在 ({existing}条)，跳过")
            return

        batch_size = 1000
        total = 0
        for i in range(0, len(hydro_data), batch_size):
            batch = hydro_data[i:i + batch_size]
            db_objs = [PaleoHydrologyData(**h) for h in batch]
            db.add_all(db_objs)
            db.commit()
            total += len(batch)
            print(f"  进度: {total}/{len(hydro_data)}")

        print(f"✅ 成功导入 {len(hydro_data)} 条水文记录")
    except Exception as e:
        db.rollback()
        print(f"❌ 导入水文数据失败: {e}")


def import_sites_data(db: Session, data_path: str):
    print("\n🏛️  正在导入古代水利工程遗迹数据...")

    try:
        if not os.path.exists(data_path):
            print(f"  ❌ 数据文件不存在: {data_path}")
            print("  请先运行: python scripts/generate_data.py")
            return

        with open(data_path, 'r', encoding='utf-8') as f:
            sites_data = json.load(f)

        imported = 0
        skipped = 0
        for sd in sites_data:
            existing = db.query(WaterHeritageSite).filter(
                WaterHeritageSite.name == sd['name'],
                WaterHeritageSite.dynasty_order == sd['dynasty_order']
            ).first()
            if existing:
                skipped += 1
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
                geom=from_shape(Point(sd['longitude'], sd['latitude']), srid=4326)
            )
            db.add(db_site)
            imported += 1

        db.commit()
        print(f"✅ 成功导入 {imported} 处遗迹，跳过 {skipped} 处已存在")
    except Exception as e:
        db.rollback()
        print(f"❌ 导入遗迹数据失败: {e}")


def compute_all_restorations(db: Session):
    print("\n🔧 正在批量计算功能复原模型...")

    regions = ['中原地区', '关中地区', '江南地区', '巴蜀地区',
               '岭南地区', '江淮地区', '山东地区', '河北地区',
               '河东地区', '河西地区', '辽东地区', '滇黔地区']

    model = HydraulicRestorationModel()

    try:
        sites = db.query(WaterHeritageSite).all()
        success = 0

        from shapely.geometry import shape as shapely_shape

        for i, site in enumerate(sites, 1):
            existing = db.query(FunctionalRestoration).filter(
                FunctionalRestoration.site_id == site.id
            ).first()
            if existing:
                continue

            region = regions[hash(site.name) % len(regions)]
            hydro_data = db.query(PaleoHydrologyData).filter(
                PaleoHydrologyData.region == region
            ).all()

            result = model.restore_site(site, hydro_data)

            geom_db = None
            if result['water_supply_range_geom']:
                try:
                    poly = shapely_shape(result['water_supply_range_geom'])
                    geom_db = from_shape(poly, srid=4326)
                except Exception:
                    pass

            new_r = FunctionalRestoration(
                site_id=site.id,
                original_irrigation_capacity=result['original_irrigation_capacity'],
                actual_irrigation_capacity=result['actual_irrigation_capacity'],
                water_supply_range_geom=geom_db,
                supply_population=result['supply_population'],
                restoration_notes=result['restoration_notes']
            )
            db.add(new_r)
            success += 1

            if i % 50 == 0:
                db.commit()
                print(f"  进度: {i}/{len(sites)}")

        db.commit()
        print(f"✅ 功能复原计算完成: {success} 处")
    except Exception as e:
        db.rollback()
        print(f"❌ 功能复原计算失败: {e}")


def compute_all_assessments(db: Session):
    print("\n📊 正在批量进行AHP可持续性评估...")

    regions = ['中原地区', '关中地区', '江南地区', '巴蜀地区',
               '岭南地区', '江淮地区', '山东地区', '河北地区',
               '河东地区', '河西地区', '辽东地区', '滇黔地区']

    ahp = AHPSustainabilityAssessment()

    try:
        sites = db.query(WaterHeritageSite).all()
        success = 0

        from sqlalchemy import and_

        for i, site in enumerate(sites, 1):
            existing = db.query(SustainabilityAssessment).filter(
                SustainabilityAssessment.site_id == site.id
            ).first()
            if existing:
                continue

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

            result = ahp.assess_site(
                site, modern_hydro, ancient_hydro, original_capacity
            )

            new_a = SustainabilityAssessment(site_id=site.id, **result)
            db.add(new_a)
            success += 1

            if i % 50 == 0:
                db.commit()
                print(f"  进度: {i}/{len(sites)}")

        db.commit()
        print(f"✅ 可持续性评估完成: {success} 处")
    except Exception as e:
        db.rollback()
        print(f"❌ 可持续性评估失败: {e}")


def generate_summary(db: Session):
    print("\n" + "=" * 60)
    print("  数据初始化统计")
    print("=" * 60)

    total_sites = db.query(WaterHeritageSite).count()
    total_hydro = db.query(PaleoHydrologyData).count()
    total_restoration = db.query(FunctionalRestoration).count()
    total_assessment = db.query(SustainabilityAssessment).count()
    total_alerts = db.query(AlertRecord).count()

    by_status = dict(db.query(
        WaterHeritageSite.preservation_status,
        __import__('sqlalchemy').func.count(WaterHeritageSite.id)
    ).group_by(WaterHeritageSite.preservation_status).all())

    print(f"  🏛️  水利工程遗迹:     {total_sites} 处")
    print(f"  💧 古代水文记录:     {total_hydro} 条")
    print(f"  🔧 功能复原模型:     {total_restoration} 处")
    print(f"  📊 可持续性评估:     {total_assessment} 处")
    print(f"  🚨 文物保护告警:     {total_alerts} 条")
    print(f"  ─ 保存状态分布: {by_status}")
    print()
    print("✅ 数据库初始化全部完成！")
    print()


def main():
    print()
    print("╔" + "═" * 58 + "╗")
    print("║     古代水利工程遗迹功能复原与可持续性评估系统         ║")
    print("║              数据库初始化与数据导入                    ║")
    print("╚" + "═" * 58 + "╝")
    print()

    from app.config import settings
    print(f"📡 数据库连接: {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}")
    print(f"👤 用户名:     {settings.POSTGRES_USER}")
    print()

    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    hydro_path = os.path.join(data_dir, 'hydrology_data.json')
    sites_path = os.path.join(data_dir, 'heritage_sites.json')

    if not init_tables():
        print("\n⚠️  无法创建表结构，请检查数据库连接配置:")
        print("   - PostgreSQL是否已启动？")
        print("   - 数据库 water_heritage 是否已创建？")
        print("   - PostGIS 扩展是否已启用？")
        print("   - 连接参数可在 backend/.env 中配置")
        sys.exit(1)

    db = SessionLocal()
    try:
        init_dynasties(db)
        import_hydrology_data(db, hydro_path)
        import_sites_data(db, sites_path)
        compute_all_restorations(db)
        compute_all_assessments(db)
        generate_summary(db)
    finally:
        db.close()

    print("🚀 现在可以启动后端服务了:")
    print("   cd backend && python -m uvicorn app.main:app --reload --port 8000")
    print()
    print("🌐 然后在浏览器打开: frontend/index.html")
    print()


if __name__ == '__main__':
    main()
