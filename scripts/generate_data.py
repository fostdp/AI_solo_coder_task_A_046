#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
古代水利工程遗迹与水文数据模拟生成脚本
生成300处从春秋至清代的水利工程遗迹数据
以及每10年分辨率的古代水文重建数据
"""

import json
import random
import math
from datetime import datetime, timedelta

random.seed(42)

DYNASTIES = [
    {'name': '春秋', 'order': 1, 'start_year': -770, 'end_year': -476, 'weight': 8},
    {'name': '战国', 'order': 2, 'start_year': -475, 'end_year': -221, 'weight': 12},
    {'name': '秦', 'order': 3, 'start_year': -221, 'end_year': -206, 'weight': 5},
    {'name': '西汉', 'order': 4, 'start_year': -202, 'end_year': 8, 'weight': 15},
    {'name': '东汉', 'order': 5, 'start_year': 25, 'end_year': 220, 'weight': 12},
    {'name': '三国', 'order': 6, 'start_year': 220, 'end_year': 280, 'weight': 8},
    {'name': '西晋', 'order': 7, 'start_year': 265, 'end_year': 316, 'weight': 6},
    {'name': '东晋', 'order': 8, 'start_year': 317, 'end_year': 420, 'weight': 7},
    {'name': '南北朝', 'order': 9, 'start_year': 420, 'end_year': 589, 'weight': 10},
    {'name': '隋', 'order': 10, 'start_year': 581, 'end_year': 618, 'weight': 7},
    {'name': '唐', 'order': 11, 'start_year': 618, 'end_year': 907, 'weight': 18},
    {'name': '五代', 'order': 12, 'start_year': 907, 'end_year': 960, 'weight': 6},
    {'name': '北宋', 'order': 13, 'start_year': 960, 'end_year': 1127, 'weight': 16},
    {'name': '南宋', 'order': 14, 'start_year': 1127, 'end_year': 1279, 'weight': 14},
    {'name': '元', 'order': 15, 'start_year': 1271, 'end_year': 1368, 'weight': 12},
    {'name': '明', 'order': 16, 'start_year': 1368, 'end_year': 1644, 'weight': 20},
    {'name': '清', 'order': 17, 'start_year': 1644, 'end_year': 1912, 'weight': 22},
]

SITE_TYPES = ['渠', '堰', '陂', '塘', '井']
SITE_TYPE_WEIGHTS = [30, 25, 20, 15, 10]

PRESERVATION_STATUSES = ['完好', '部分损毁', '完全废弃']
PRESERVATION_WEIGHTS = [25, 50, 25]

REGIONS = [
    '中原地区', '关中地区', '江南地区', '巴蜀地区',
    '岭南地区', '江淮地区', '山东地区', '河北地区',
    '河东地区', '河西地区', '辽东地区', '滇黔地区'
]

SITE_NAME_PREFIXES = [
    '通济', '永济', '广济', '丰利', '利民', '惠民', '济民', '富民',
    '太平', '永乐', '长安', '兴庆', '延丰', '昭德', '景福', '咸宁',
    '青龙', '白鹿', '凤凰', '玄武', '朱雀', '金明', '玉华', '翠微',
    '灵渠', '郑国', '白公', '李冰', '西门', '史起', '马融', '邓艾',
    '芍陂', '鸿隙', '镜湖', '鉴湖', '太湖', '鄱阳', '洞庭', '洪泽'
]

CHINA_CENTERS = [
    {'name': '关中', 'lat': 34.5, 'lng': 108.9, 'spread': 2.0},
    {'name': '中原', 'lat': 34.0, 'lng': 113.5, 'spread': 2.5},
    {'name': '江南', 'lat': 31.0, 'lng': 120.0, 'spread': 2.5},
    {'name': '巴蜀', 'lat': 30.5, 'lng': 104.0, 'spread': 2.0},
    {'name': '岭南', 'lat': 23.5, 'lng': 113.5, 'spread': 2.5},
    {'name': '江淮', 'lat': 32.5, 'lng': 117.5, 'spread': 2.0},
    {'name': '山东', 'lat': 36.5, 'lng': 118.0, 'spread': 2.0},
    {'name': '河北', 'lat': 38.5, 'lng': 115.5, 'spread': 2.5},
    {'name': '河东', 'lat': 35.5, 'lng': 111.0, 'spread': 1.5},
    {'name': '河西', 'lat': 39.0, 'lng': 100.0, 'spread': 3.0},
    {'name': '辽东', 'lat': 41.0, 'lng': 123.0, 'spread': 2.0},
    {'name': '滇黔', 'lat': 26.0, 'lng': 105.0, 'spread': 3.0},
]


def weighted_choice(items, weights):
    return random.choices(items, weights=weights, k=1)[0]


def generate_site_name(site_type, idx):
    prefix = random.choice(SITE_NAME_PREFIXES)
    suffixes = {
        '渠': ['渠', '运河', '漕渠', '灌渠'],
        '堰': ['堰', '坝', '拦河堰'],
        '陂': ['陂', '湖陂', '塘陂'],
        '塘': ['塘', '水塘', '水库'],
        '井': ['井', '古井', '泉井']
    }
    suffix = random.choice(suffixes[site_type])
    if idx % 7 == 0:
        return f"{prefix}{suffix}"
    else:
        numbers = ['第一', '第二', '第三', '东', '西', '南', '北', '上', '下', '新', '古']
        return f"{random.choice(numbers)}{prefix}{suffix}"


def generate_coordinates():
    center = random.choice(CHINA_CENTERS)
    lat = center['lat'] + random.uniform(-center['spread'], center['spread'])
    lng = center['lng'] + random.uniform(-center['spread'], center['spread'])
    lat = max(18.0, min(53.0, lat))
    lng = max(73.0, min(135.0, lng))
    return round(lng, 6), round(lat, 6)


def generate_structure_params(site_type):
    params = {}
    if site_type == '渠':
        params['canal_length'] = round(random.uniform(5, 500), 1)
        params['dam_height'] = round(random.uniform(0.5, 5), 1)
        params['irrigation_area'] = round(random.lognormvariate(5, 1.2), 1)
    elif site_type == '堰':
        params['dam_height'] = round(random.uniform(2, 30), 1)
        params['canal_length'] = round(random.uniform(1, 50), 1)
        params['irrigation_area'] = round(random.lognormvariate(5.5, 1.0), 1)
    elif site_type == '陂':
        params['dam_height'] = round(random.uniform(3, 25), 1)
        params['canal_length'] = round(random.uniform(2, 30), 1)
        params['irrigation_area'] = round(random.lognormvariate(6, 0.8), 1)
    elif site_type == '塘':
        params['dam_height'] = round(random.uniform(1, 15), 1)
        params['canal_length'] = round(random.uniform(0.5, 10), 1)
        params['irrigation_area'] = round(random.lognormvariate(3.5, 0.9), 1)
    elif site_type == '井':
        params['dam_height'] = None
        params['canal_length'] = None
        params['irrigation_area'] = round(random.lognormvariate(1.5, 0.8), 1)
    return params


def generate_sites(count=300):
    sites = []
    for i in range(count):
        dynasty = weighted_choice(DYNASTIES, [d['weight'] for d in DYNASTIES])
        site_type = weighted_choice(SITE_TYPES, SITE_TYPE_WEIGHTS)
        lng, lat = generate_coordinates()
        params = generate_structure_params(site_type)
        preservation = weighted_choice(PRESERVATION_STATUSES, PRESERVATION_WEIGHTS)

        site = {
            'id': i + 1,
            'name': generate_site_name(site_type, i),
            'dynasty': dynasty['name'],
            'dynasty_order': dynasty['order'],
            'longitude': lng,
            'latitude': lat,
            'geom': f'SRID=4326;POINT({lng} {lat})',
            'site_type': site_type,
            'dam_height': params['dam_height'],
            'canal_length': params['canal_length'],
            'irrigation_area': params['irrigation_area'],
            'preservation_status': preservation,
            'description': f"位于{random.choice(REGIONS)}的{dynasty['name']}时期{site_type}工程，{random.choice([
                '是当地重要的水利灌溉设施', '对区域农业发展起到了关键作用',
                '见证了古代水利技术的辉煌成就', '具有重要的历史文化价值',
                '反映了当时的社会经济发展水平', '是古代劳动人民智慧的结晶'
            ])}。"
        }
        sites.append(site)
    return sites


def generate_hydrology_data():
    records = []
    years = list(range(-800, 2000, 10))

    base_climate = {
        '中原地区': {'rain': 650, 'runoff': 180, 'temp': 14.0},
        '关中地区': {'rain': 580, 'runoff': 140, 'temp': 13.5},
        '江南地区': {'rain': 1200, 'runoff': 600, 'temp': 16.5},
        '巴蜀地区': {'rain': 1000, 'runoff': 450, 'temp': 16.0},
        '岭南地区': {'rain': 1600, 'runoff': 900, 'temp': 22.0},
        '江淮地区': {'rain': 1000, 'runoff': 400, 'temp': 15.5},
        '山东地区': {'rain': 700, 'runoff': 200, 'temp': 13.0},
        '河北地区': {'rain': 550, 'runoff': 120, 'temp': 12.0},
        '河东地区': {'rain': 500, 'runoff': 100, 'temp': 11.0},
        '河西地区': {'rain': 150, 'runoff': 20, 'temp': 8.0},
        '辽东地区': {'rain': 700, 'runoff': 180, 'temp': 8.5},
        '滇黔地区': {'rain': 1100, 'runoff': 500, 'temp': 17.0},
    }

    for year in years:
        for region, base in base_climate.items():
            century_factor = 1.0
            if -800 <= year < -500:
                century_factor = random.uniform(0.85, 1.05)
            elif -500 <= year < 0:
                century_factor = random.uniform(0.90, 1.10)
            elif 0 <= year < 300:
                century_factor = random.uniform(0.95, 1.15)
            elif 300 <= year < 600:
                century_factor = random.uniform(0.85, 1.05)
            elif 600 <= year < 1000:
                century_factor = random.uniform(1.00, 1.20)
            elif 1000 <= year < 1300:
                century_factor = random.uniform(1.05, 1.25)
            elif 1300 <= year < 1500:
                century_factor = random.uniform(0.80, 1.00)
            elif 1500 <= year < 1700:
                century_factor = random.uniform(0.85, 1.05)
            elif 1700 <= year < 1900:
                century_factor = random.uniform(0.90, 1.10)
            else:
                century_factor = random.uniform(0.95, 1.20)

            annual_variation = random.uniform(0.80, 1.20)
            temp_variation = random.uniform(-1.5, 1.5)

            records.append({
                'year': year,
                'region': region,
                'rainfall': round(base['rain'] * century_factor * annual_variation, 1),
                'runoff': round(base['runoff'] * century_factor * annual_variation, 1),
                'temperature': round(base['temp'] + temp_variation + (year - 1950) * 0.01, 2)
            })
    return records


def main():
    print("正在生成水利工程遗迹数据...")
    sites = generate_sites(300)
    print(f"  生成了 {len(sites)} 处水利工程遗迹")

    status_count = {'完好': 0, '部分损毁': 0, '完全废弃': 0}
    type_count = {}
    dynasty_count = {}
    for s in sites:
        status_count[s['preservation_status']] += 1
        type_count[s['site_type']] = type_count.get(s['site_type'], 0) + 1
        dynasty_count[s['dynasty']] = dynasty_count.get(s['dynasty'], 0) + 1

    print(f"  保存状态分布: {status_count}")
    print(f"  工程类型分布: {type_count}")
    print(f"  朝代分布Top5: {sorted(dynasty_count.items(), key=lambda x: -x[1])[:5]}")

    with open('data/heritage_sites.json', 'w', encoding='utf-8') as f:
        json.dump(sites, f, ensure_ascii=False, indent=2)
    print("  已保存到 data/heritage_sites.json")

    print("\n正在生成古代水文重建数据...")
    hydro_data = generate_hydrology_data()
    print(f"  生成了 {len(hydro_data)} 条水文记录")

    with open('data/hydrology_data.json', 'w', encoding='utf-8') as f:
        json.dump(hydro_data, f, ensure_ascii=False, indent=2)
    print("  已保存到 data/hydrology_data.json")

    print("\n正在生成GeoJSON格式遗迹数据...")
    geojson_features = []
    for s in sites:
        geojson_features.append({
            'type': 'Feature',
            'id': s['id'],
            'geometry': {
                'type': 'Point',
                'coordinates': [s['longitude'], s['latitude']]
            },
            'properties': {k: v for k, v in s.items() if k not in ['longitude', 'latitude', 'geom']}
        })

    geojson_data = {
        'type': 'FeatureCollection',
        'features': geojson_features
    }

    with open('data/heritage_sites.geojson', 'w', encoding='utf-8') as f:
        json.dump(geojson_data, f, ensure_ascii=False, indent=2)
    print("  已保存到 data/heritage_sites.geojson")

    print("\n数据生成完成！")


if __name__ == '__main__':
    main()
