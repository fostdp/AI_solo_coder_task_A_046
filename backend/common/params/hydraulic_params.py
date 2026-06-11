"""
水力计算模型参数 - 外置配置
所有参数集中管理，便于调优和扩展
"""
from typing import Dict, Any


# ========== 基础参数 ==========
GRAVITY = 9.81  # 重力加速度 m/s²
CROP_WATER_REQUIREMENT = 450.0  # 作物需水量 m³/亩·年
EFFECTIVE_RAINFALL_COEFFICIENT = 0.6  # 有效降雨系数


# ========== 各类工程参数分布 ==========
# 用于参数估计的统计分布（均值、标准差、最小值、最大值）
TYPE_PARAM_DISTRIBUTIONS: Dict[str, Dict[str, Dict[str, float]]] = {
    '渠': {
        'dam_height': {'mean': 3.5, 'std': 2.0, 'min': 0.5, 'max': 12.0},
        'canal_length': {'mean': 80.0, 'std': 60.0, 'min': 5.0, 'max': 500.0},
        'Cd': {'mean': 0.62, 'std': 0.08, 'min': 0.4, 'max': 0.85},
        'n_manning': {'mean': 0.030, 'std': 0.008, 'min': 0.02, 'max': 0.05},
        'efficiency': {'mean': 0.75, 'std': 0.10, 'min': 0.5, 'max': 0.9},
    },
    '堰': {
        'dam_height': {'mean': 10.0, 'std': 6.0, 'min': 2.0, 'max': 35.0},
        'weir_length': {'mean': 60.0, 'std': 40.0, 'min': 10.0, 'max': 200.0},
        'Cd': {'mean': 0.58, 'std': 0.10, 'min': 0.35, 'max': 0.8},
        'efficiency': {'mean': 0.70, 'std': 0.12, 'min': 0.45, 'max': 0.9},
    },
    '陂': {
        'dam_height': {'mean': 12.0, 'std': 7.0, 'min': 3.0, 'max': 40.0},
        'surface_area_ratio': {'mean': 80, 'std': 30, 'min': 30, 'max': 200},
        'Cd': {'mean': 0.55, 'std': 0.10, 'min': 0.3, 'max': 0.75},
        'efficiency': {'mean': 0.80, 'std': 0.08, 'min': 0.6, 'max': 0.92},
    },
    '塘': {
        'dam_height': {'mean': 5.0, 'std': 3.0, 'min': 1.0, 'max': 18.0},
        'surface_area_ratio': {'mean': 60, 'std': 25, 'min': 20, 'max': 150},
        'efficiency': {'mean': 0.65, 'std': 0.12, 'min': 0.4, 'max': 0.85},
    },
    '井': {
        'well_depth': {'mean': 25.0, 'std': 15.0, 'min': 5.0, 'max': 80.0},
        'well_radius': {'mean': 0.15, 'std': 0.05, 'min': 0.08, 'max': 0.35},
        'k_hydraulic': {'mean': 2.5, 'std': 1.5, 'min': 0.5, 'max': 10.0},
        'efficiency': {'mean': 0.50, 'std': 0.15, 'min': 0.2, 'max': 0.75},
    }
}


# ========== 朝代技术因子 ==========
# 反映不同朝代水利技术发展水平（1=最高水平）
DYNASTY_TECH_FACTOR: Dict[int, float] = {
    1: 0.70,   # 春秋
    2: 0.78,   # 战国
    3: 0.82,   # 秦
    4: 0.88,   # 西汉
    5: 0.90,   # 东汉
    6: 0.88,   # 三国
    7: 0.85,   # 西晋
    8: 0.87,   # 东晋
    9: 0.90,   # 南北朝
    10: 0.93,  # 隋
    11: 0.98,  # 唐
    12: 0.92,  # 五代
    13: 1.00,  # 北宋
    14: 0.97,  # 南宋
    15: 0.95,  # 元
    16: 1.02,  # 明
    17: 1.05,  # 清
}


# ========== 灌溉效率 ==========
IRRIGATION_EFFICIENCY: Dict[str, float] = {
    '渠': 0.75,
    '堰': 0.70,
    '陂': 0.80,
    '塘': 0.65,
    '井': 0.50
}


# ========== 保存状态折减系数 ==========
PRESERVATION_FACTOR: Dict[str, float] = {
    '完好': 0.95,
    '部分损毁': 0.55,
    '完全废弃': 0.10
}


# ========== 引水系数 ==========
# 各类工程可引用的径流比例
TYPE_DIVERSION_COEFFICIENT: Dict[str, float] = {
    '渠': 0.60,
    '堰': 0.50,
    '陂': 0.35,
    '塘': 0.25,
    '井': 0.08
}


# ========== 供水范围类型因子 ==========
# 各类工程供水范围形态修正
TYPE_RANGE_FACTOR: Dict[str, float] = {
    '渠': 1.5,
    '堰': 1.0,
    '陂': 0.8,
    '塘': 0.6,
    '井': 0.3
}


# ========== 人口估算参数 ==========
PER_CAPITA_FOOD = 250.0  # 人均年粮食消费量 kg
GRAIN_PER_MU = 150.0    # 古代粮食亩产 kg
FOOD_TO_POPULATION_RATIO = 3.0  # 粮食产量到人口的换算系数


# ========== 区域列表 ==========
REGIONS = [
    '中原地区', '关中地区', '江南地区', '巴蜀地区',
    '岭南地区', '江淮地区', '山东地区', '河北地区',
    '河东地区', '河西地区', '辽东地区', '滇黔地区'
]


# ========== 数值范围（收敛保护） ==========
CLAMP_RANGES: Dict[str, Dict[str, float]] = {
    'weir_flow': {'min': 0.0, 'max': 10000.0},
    'canal_capacity': {'min': 0.0, 'max': 5000.0},
    'reservoir_capacity': {'min': 100.0, 'max': 1e8},
    'well_yield': {'min': 0.0, 'max': 1000.0},
    'irrigation_capacity': {'min': 0.1, 'max': 100000.0},
}


# ========== 蒙特卡洛默认参数 ==========
MONTECARLO_DEFAULTS: Dict[str, Any] = {
    'n_samples': 1000,
    'seed': 42,
    'convergence_mean_error': 0.05,   # 收敛均值误差阈值
    'convergence_std_error': 0.10,    # 收敛标准差误差阈值
}


# ========== 供水多边形参数 ==========
SUPPLY_POLYGON: Dict[str, Any] = {
    'area_to_radius_factor': 0.003,   # 灌溉面积→经纬度半径系数
    'detail_points': 24,               # 详细模式点数
    'simplified_points': 8,            # 简化模式点数
    'noise_amplitude': 0.5,             # 边界噪声幅度（0-1）
    'min_radius': 0.005,                # 最小半径（度）
    'max_radius': 1.5,                  # 最大半径（度）
}


def get_param_distribution(site_type: str, param_name: str) -> Dict[str, float]:
    """获取指定类型的参数分布"""
    type_dists = TYPE_PARAM_DISTRIBUTIONS.get(site_type, {})
    return type_dists.get(param_name, {'mean': 1.0, 'std': 0.5, 'min': 0.1, 'max': 10.0})


def get_tech_factor(dynasty_order: int) -> float:
    """获取朝代技术因子"""
    return DYNASTY_TECH_FACTOR.get(dynasty_order, 1.0)
