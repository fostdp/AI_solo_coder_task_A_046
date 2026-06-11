"""
数据模拟器 - 命令行版
支持参数化生成不同年代、不同类型的遗迹数据和水文重建数据

用法:
    python -m scripts.run_simulator                     # 默认生成300处遗迹，全朝代全类型
    python -m scripts.run_simulator --sites 100         # 100处
    python -m scripts.run_simulator --dynasty 唐        # 仅唐代
    python -m scripts.run_simulator --type 渠,堰        # 仅渠和堰
    python -m scripts.run_simulator --seed 123          # 固定随机种子
    python -m scripts.run_simulator --no-hydrology      # 仅导入遗迹，不生成水文
    python -m scripts.run_simulator --hydro-only        # 仅生成水文数据
    python -m scripts.run_simulator --list-dynasties    # 列出所有朝代
"""
import sys
import os
import argparse
import random
import hashlib
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 延迟导入 common 模块（仅数据库写入时需要 pydantic_settings 等依赖）
# REGIONS 直接内联以避免依赖 hydraulic_params
REGIONS = [
    '中原地区', '关中地区', '江南地区', '巴蜀地区',
    '岭南地区', '江淮地区', '山东地区', '河北地区',
    '河东地区', '河西地区', '辽东地区', '滇黔地区',
]


# ========== 朝代定义 ==========
DYNASTIES = [
    {"id": 1, "name": "春秋", "start_year": -770, "end_year": -476, "order": 1, "weight": 0.03},
    {"id": 2, "name": "战国", "start_year": -475, "end_year": -221, "order": 2, "weight": 0.04},
    {"id": 3, "name": "秦", "start_year": -221, "end_year": -207, "order": 3, "weight": 0.03},
    {"id": 4, "name": "西汉", "start_year": -206, "end_year": 8, "order": 4, "weight": 0.08},
    {"id": 5, "name": "东汉", "start_year": 25, "end_year": 220, "order": 5, "weight": 0.06},
    {"id": 6, "name": "三国", "start_year": 220, "end_year": 280, "order": 6, "weight": 0.04},
    {"id": 7, "name": "西晋", "start_year": 265, "end_year": 316, "order": 7, "weight": 0.03},
    {"id": 8, "name": "东晋", "start_year": 317, "end_year": 420, "order": 8, "weight": 0.04},
    {"id": 9, "name": "南北朝", "start_year": 420, "end_year": 589, "order": 9, "weight": 0.05},
    {"id": 10, "name": "隋", "start_year": 581, "end_year": 618, "order": 10, "weight": 0.04},
    {"id": 11, "name": "唐", "start_year": 618, "end_year": 907, "order": 11, "weight": 0.12},
    {"id": 12, "name": "五代", "start_year": 907, "end_year": 960, "order": 12, "weight": 0.04},
    {"id": 13, "name": "北宋", "start_year": 960, "end_year": 1127, "order": 13, "weight": 0.10},
    {"id": 14, "name": "南宋", "start_year": 1127, "end_year": 1279, "order": 14, "weight": 0.08},
    {"id": 15, "name": "元", "start_year": 1271, "end_year": 1368, "order": 15, "weight": 0.06},
    {"id": 16, "name": "明", "start_year": 1368, "end_year": 1644, "order": 16, "weight": 0.12},
    {"id": 17, "name": "清", "start_year": 1644, "end_year": 1912, "order": 17, "weight": 0.04},
]

# 区域经纬度中心
REGION_CENTERS = {
    '中原地区': (34.5, 113.5),
    '关中地区': (34.3, 108.9),
    '江南地区': (31.2, 120.5),
    '巴蜀地区': (30.7, 104.1),
    '岭南地区': (23.1, 113.3),
    '江淮地区': (32.0, 118.8),
    '山东地区': (36.7, 117.0),
    '河北地区': (38.0, 115.5),
    '河东地区': (37.5, 112.5),
    '河西地区': (39.0, 100.5),
    '辽东地区': (41.8, 123.4),
    '滇黔地区': (26.6, 106.6),
}

SITE_TYPES = ['渠', '堰', '陂', '塘', '井']
TYPE_WEIGHTS = [0.30, 0.25, 0.20, 0.15, 0.10]

STATUS_OPTIONS = ['完好', '部分损毁', '完全废弃']
STATUS_WEIGHTS = [0.25, 0.50, 0.25]


# ========== 名字生成 ==========
SITE_NAME_PREFIXES = [
    '龙', '凤', '金', '玉', '永', '安', '太', '平', '万', '福',
    '清', '白', '青', '翠', '古', '灵', '神', '圣', '文', '武',
]
SITE_NAME_SUFFIXES = {
    '渠': ['渠', '灌渠', '引水渠', '通济渠', '惠民渠'],
    '堰': ['堰', '大坝', '分水堰', '溢流堰', '石堰'],
    '陂': ['陂', '湖陂', '蓄水陂', '官陂', '民陂'],
    '塘': ['塘', '水塘', '山塘', '平塘', '陂塘'],
    '井': ['井', '古井', '泉井', '水井', '八卦井'],
}


def generate_site_name(site_type):
    prefix = random.choice(SITE_NAME_PREFIXES)
    suffix = random.choice(SITE_NAME_SUFFIXES[site_type])
    return f"{prefix}{suffix}"


def weighted_choice(items, weights):
    return random.choices(items, weights=weights, k=1)[0]


# ========== 遗迹生成 ==========
def generate_sites(count, dynasty_filter=None, type_filter=None, seed=42):
    """生成遗迹数据"""
    random.seed(seed)

    # 应用朝代过滤
    available_dynasties = DYNASTIES
    if dynasty_filter and dynasty_filter.lower() != 'all':
        filtered = [d for d in DYNASTIES
                    if d['name'] == dynasty_filter
                    or d['name'].startswith(dynasty_filter)]
        if filtered:
            available_dynasties = filtered

    # 应用类型过滤
    available_types = SITE_TYPES
    available_weights = TYPE_WEIGHTS
    if type_filter and type_filter.lower() != 'all':
        selected_types = [t.strip() for t in type_filter.split(',') if t.strip() in SITE_TYPES]
        if selected_types:
            available_types = selected_types
            available_weights = [1.0 / len(selected_types)] * len(selected_types)

    sites = []
    dynasty_weights = [d['weight'] for d in available_dynasties]

    for i in range(count):
        dynasty = weighted_choice(available_dynasties, dynasty_weights)
        site_type = weighted_choice(available_types, available_weights)
        status = weighted_choice(STATUS_OPTIONS, STATUS_WEIGHTS)

        # 区域选择：基于名字确定性哈希
        name = generate_site_name(site_type)
        region_idx = int(hashlib.md5(name.encode()).hexdigest(), 16) % len(REGIONS)
        region = REGIONS[region_idx]
        center_lat, center_lon = REGION_CENTERS.get(region, (34.0, 110.0))

        # 经纬度偏移
        lon = center_lon + (random.random() - 0.5) * 3.0
        lat = center_lat + (random.random() - 0.5) * 2.5

        # 结构参数
        irrigation_area = max(5.0, random.lognormvariate(5.0, 1.2))

        if site_type == '井':
            dam_height = None
            canal_length = None
        else:
            dam_height = max(0.5, random.gauss(
                {'渠': 3.5, '堰': 10.0, '陂': 12.0, '塘': 5.0}[site_type], 3.0
            ))
            dam_height = round(dam_height, 1)

            if site_type == '渠':
                canal_length = max(5.0, random.gauss(80, 50))
                canal_length = round(canal_length, 1)
            else:
                canal_length = None

        description = (f"{dynasty['name']}代{site_type}类水利工程，"
                       f"位于{region}，主要用于农业灌溉和防洪。")

        sites.append({
            'name': name,
            'dynasty': dynasty['name'],
            'dynasty_order': dynasty['order'],
            'longitude': round(lon, 6),
            'latitude': round(lat, 6),
            'site_type': site_type,
            'dam_height': dam_height,
            'canal_length': canal_length,
            'irrigation_area': round(irrigation_area, 1),
            'preservation_status': status,
            'description': description,
        })

    return sites, available_dynasties


# ========== 水文数据生成 ==========
def generate_hydrology(dynasties=None, seed=42):
    """生成每10年分辨率的水文重建数据"""
    random.seed(seed)
    np_seed = seed
    try:
        import numpy as np
        np.random.seed(np_seed)
        has_numpy = True
    except ImportError:
        has_numpy = False

    if dynasties is None:
        dynasties = DYNASTIES

    records = []
    all_years = []

    # 生成所有需要的年份
    for dyn in dynasties:
        start = max(dyn['start_year'] - (dyn['start_year'] % 10), -770)
        end = min(dyn['end_year'] + 10, 1912)
        year = start
        while year <= end:
            if -770 <= year <= 1912:
                all_years.append((year, dyn['name']))
            year += 10

    # 去重
    seen = set()
    unique_years = []
    for y, d in all_years:
        if y not in seen:
            seen.add(y)
            unique_years.append((y, d))
    unique_years.sort()

    for region in REGIONS:
        # 基准气候参数
        base_rainfall = 700 + random.random() * 500  # 700~1200mm
        base_runoff = 200 + random.random() * 400     # 200~600万m³

        # 长期趋势系数
        if has_numpy:
            trend = np.linspace(-0.1, 0.1, len(unique_years))
            noise_rain = np.random.normal(0, 0.08, len(unique_years))
            noise_runoff = np.random.normal(0, 0.12, len(unique_years))
            noise_temp = np.random.normal(0, 0.5, len(unique_years))
        else:
            trend = [0] * len(unique_years)
            noise_rain = [random.gauss(0, 0.08) for _ in unique_years]
            noise_runoff = [random.gauss(0, 0.12) for _ in unique_years]
            noise_temp = [random.gauss(0, 0.5) for _ in unique_years]

        for i, (year, dyn_name) in enumerate(unique_years):
            rainfall_factor = 1.0 + trend[i] + noise_rain[i]
            runoff_factor = 1.0 + trend[i] * 1.2 + noise_runoff[i]
            temperature = 14.0 + trend[i] * 3 + noise_temp[i]

            rainfall = max(100, base_rainfall * rainfall_factor)
            runoff = max(50, base_runoff * runoff_factor)

            records.append({
                'year': year,
                'region': region,
                'rainfall': round(rainfall, 1),
                'runoff': round(runoff, 1),
                'temperature': round(temperature, 2),
            })

    return records


# ========== 数据库写入 ==========
def insert_to_database(sites, hydrology, dynasties_list):
    """写入PostgreSQL数据库"""
    try:
        from common.database import SessionLocal, init_db
        from common.models import WaterHeritageSite, PaleoHydrologyData, DynastyDict
        from geoalchemy2.shape import from_shape
        from shapely.geometry import Point
        from sqlalchemy import text
    except ImportError as e:
        print(f"⚠️  缺少数据库依赖，跳过写入: {e}")
        print(f"   已生成 {len(sites)} 处遗迹，{len(hydrology)} 条水文记录")
        return False

    print("📦 正在写入数据库...")
    init_db()
    db = SessionLocal()

    try:
        # 朝代字典
        print("  → 写入朝代字典...")
        for d in dynasties_list:
            existing = db.query(DynastyDict).filter(DynastyDict.order == d['order']).first()
            if not existing:
                db.add(DynastyDict(
                    id=d['id'], name=d['name'],
                    start_year=d['start_year'], end_year=d['end_year'], order=d['order']
                ))
        db.flush()

        # 遗迹数据
        print(f"  → 写入 {len(sites)} 处遗迹...")
        count = 0
        for s in sites:
            point = Point(s['longitude'], s['latitude'])
            geom = from_shape(point, srid=4326)
            site = WaterHeritageSite(
                name=s['name'], dynasty=s['dynasty'],
                dynasty_order=s['dynasty_order'],
                longitude=s['longitude'], latitude=s['latitude'],
                geom=geom, site_type=s['site_type'],
                dam_height=s['dam_height'], canal_length=s['canal_length'],
                irrigation_area=s['irrigation_area'],
                preservation_status=s['preservation_status'],
                description=s['description'],
            )
            db.add(site)
            count += 1
            if count % 100 == 0:
                db.flush()
                print(f"    · 已写入 {count}/{len(sites)}")

        db.flush()

        # 水文数据
        if hydrology:
            print(f"  → 写入 {len(hydrology)} 条水文记录...")
            count = 0
            for h in hydrology:
                record = PaleoHydrologyData(
                    year=h['year'], region=h['region'],
                    rainfall=h['rainfall'], runoff=h['runoff'],
                    temperature=h['temperature'],
                )
                db.add(record)
                count += 1
                if count % 500 == 0:
                    db.flush()
                    print(f"    · 已写入 {count}/{len(hydrology)}")

        db.commit()
        print(f"\n✅ 写入完成！")
        print(f"   朝代: {len(dynasties_list)} 个")
        print(f"   遗迹: {len(sites)} 处")
        if hydrology:
            print(f"   水文: {len(hydrology)} 条")
        return True

    except Exception as e:
        db.rollback()
        print(f"❌ 写入失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


# ========== CLI ==========
def main():
    parser = argparse.ArgumentParser(
        description='古代水利工程遗迹数据模拟器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                                    # 默认300处，全朝代全类型
  %(prog)s --sites 500                        # 500处遗迹
  %(prog)s --dynasty 唐                       # 仅唐代
  %(prog)s --dynasty 宋                       # 宋代（北宋+南宋）
  %(prog)s --type 渠,堰                       # 仅渠和堰
  %(prog)s --sites 100 --dynasty 明 --type 塘 # 明代100处塘
  %(prog)s --no-hydrology                     # 不生成水文数据
  %(prog)s --hydro-only                       # 仅生成水文数据
  %(prog)s --list-dynasties                   # 列出所有朝代
        """
    )
    parser.add_argument('--sites', type=int, default=300,
                        help='生成遗迹数量 (默认: 300)')
    parser.add_argument('--dynasty', type=str, default='all',
                        help='朝代过滤，如：唐、宋、明 (默认: all)')
    parser.add_argument('--type', type=str, default='all',
                        help='工程类型，逗号分隔，如：渠,堰,陂 (默认: all)')
    parser.add_argument('--seed', type=int, default=42,
                        help='随机种子 (默认: 42)')
    parser.add_argument('--no-hydrology', action='store_true',
                        help='不生成水文数据')
    parser.add_argument('--hydro-only', action='store_true',
                        help='仅生成水文数据，不生成遗迹')
    parser.add_argument('--list-dynasties', action='store_true',
                        help='列出所有支持的朝代并退出')
    parser.add_argument('--dry-run', action='store_true',
                        help='仅生成数据，不写入数据库')

    args = parser.parse_args()

    # 列出朝代
    if args.list_dynasties:
        print("📜 支持的朝代列表:")
        print("-" * 50)
        for d in DYNASTIES:
            years = f"{d['start_year']}~{d['end_year']}"
            years = years.replace('--', '前').replace('-', '前')
            if '前' in years and '~' in years:
                parts = years.split('~')
                if not parts[1].startswith('前') and not parts[0].startswith('前'):
                    pass
            print(f"  {d['order']:2d}. {d['name']:<4s} ({years:>12s})  权重: {d['weight']:.0%}")
        print()
        print("可用类型: 渠, 堰, 陂, 塘, 井")
        return

    # 参数校验
    if args.sites <= 0:
        print("❌ --sites 必须大于 0")
        sys.exit(1)

    print("=" * 60)
    print("🏛️  古代水利工程遗迹数据模拟器")
    print("=" * 60)
    print(f"📝 配置:")
    if not args.hydro_only:
        print(f"  遗迹数量:   {args.sites}")
        print(f"  朝代过滤:   {args.dynasty}")
        print(f"  类型过滤:   {args.type}")
    print(f"  随机种子:   {args.seed}")
    print(f"  生成水文:   {'否' if args.no_hydrology else '是'}")
    print(f"  写入数据库: {'否' if args.dry_run else '是'}")
    print()

    sites = []
    hydrology = []
    used_dynasties = DYNASTIES

    # 生成遗迹
    if not args.hydro_only:
        print(f"🏗️  正在生成 {args.sites} 处遗迹...")
        sites, used_dynasties = generate_sites(
            args.sites,
            dynasty_filter=args.dynasty,
            type_filter=args.type,
            seed=args.seed
        )

        # 统计
        type_counts = {}
        dynasty_counts = {}
        status_counts = {}
        for s in sites:
            type_counts[s['site_type']] = type_counts.get(s['site_type'], 0) + 1
            dynasty_counts[s['dynasty']] = dynasty_counts.get(s['dynasty'], 0) + 1
            status_counts[s['preservation_status']] = status_counts.get(s['preservation_status'], 0) + 1

        print(f"  类型分布: {type_counts}")
        print(f"  朝代分布: {dynasty_counts}")
        print(f"  保存状态: {status_counts}")
        print()

    # 生成水文
    if not args.no_hydrology:
        print(f"🌧️  正在生成水文重建数据...")
        hydrology = generate_hydrology(dynasties=used_dynasties, seed=args.seed + 1)
        print(f"  共 {len(hydrology)} 条记录")
        print(f"  覆盖区域: {len(REGIONS)} 个")
        print(f"  时间范围: 每10年分辨率")
        print()

    # 写入数据库
    if args.dry_run:
        print("⏭️  Dry-Run 模式，跳过数据库写入")
        print(f"   遗迹: {len(sites)} 处")
        print(f"   水文: {len(hydrology)} 条")
    else:
        ok = insert_to_database(sites, hydrology, used_dynasties)
        if not ok:
            print("\n💡 提示: 使用 --dry-run 仅生成数据不写入数据库")
            sys.exit(1)

    print()
    print("🎉 模拟完成！")


if __name__ == '__main__':
    main()
