"""
水力计算模型 - 核心算法
从 restoration_model.py 重构，参数已外置到 common/params
"""
import math
import random
import numpy as np
from typing import Dict, Tuple, Optional, List, Any
from shapely.geometry import Polygon, Point

from common.params.hydraulic_params import (
    GRAVITY,
    CROP_WATER_REQUIREMENT,
    EFFECTIVE_RAINFALL_COEFFICIENT,
    TYPE_PARAM_DISTRIBUTIONS,
    DYNASTY_TECH_FACTOR,
    IRRIGATION_EFFICIENCY,
    PRESERVATION_FACTOR,
    TYPE_DIVERSION_COEFFICIENT,
    TYPE_RANGE_FACTOR,
    PER_CAPITA_FOOD,
    GRAIN_PER_MU,
    CLAMP_RANGES,
    MONTECARLO_DEFAULTS,
    SUPPLY_POLYGON,
    get_param_distribution,
    get_tech_factor,
)


# ==============================================
# 数值收敛保护
# ==============================================

def _safe_log(x: float, epsilon: float = 1e-10) -> float:
    return math.log(max(x, epsilon))


def _safe_sqrt(x: float) -> float:
    return math.sqrt(max(x, 0.0))


def _clamp(val: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(val, max_val))


# ==============================================
# 参数估计器
# ==============================================

class ParameterEstimator:
    """工程参数估计器
    当遗迹结构参数缺失时，基于类型统计分布和朝代技术因子进行估计
    """

    def __init__(self):
        pass

    def estimate_parameters(self, site_type: str, dynasty_order: int,
                            irrigation_area: Optional[float] = None,
                            dam_height: Optional[float] = None,
                            canal_length: Optional[float] = None) -> Tuple[Dict[str, float], float]:
        """
        估计工程参数
        Returns: (参数字典, 估计可靠度 0-100)
        """
        params = {}
        reliability = 100.0

        tech_factor = get_tech_factor(dynasty_order)

        # 坝高估计
        if dam_height is not None:
            params['dam_height'] = dam_height
        else:
            dist = get_param_distribution(site_type, 'dam_height')
            params['dam_height'] = dist['mean'] * tech_factor
            reliability -= 8

        # 渠长估计（如果类型是渠）
        if site_type == '渠':
            if canal_length is not None:
                params['canal_length'] = canal_length
            else:
                if irrigation_area:
                    params['canal_length'] = max(5.0, math.sqrt(irrigation_area) * 3.5)
                    reliability -= 3
                else:
                    dist = get_param_distribution(site_type, 'canal_length')
                    params['canal_length'] = dist['mean'] * tech_factor
                    reliability -= 8
        elif site_type == '堰':
            dist = get_param_distribution('堰', 'weir_length')
            params['weir_length'] = dist['mean'] * tech_factor
            if dam_height is None:
                reliability -= 8

        # 流量系数
        dist_cd = get_param_distribution(site_type, 'Cd')
        params['Cd'] = dist_cd['mean']

        # 效率
        dist_eff = get_param_distribution(site_type, 'efficiency')
        params['efficiency'] = dist_eff['mean']

        # 井的特殊参数
        if site_type == '井':
            dist_depth = get_param_distribution('井', 'well_depth')
            params['well_depth'] = dist_depth['mean'] * tech_factor
            dist_radius = get_param_distribution('井', 'well_radius')
            params['well_radius'] = dist_radius['mean']
            dist_k = get_param_distribution('井', 'k_hydraulic')
            params['k_hydraulic'] = dist_k['mean']
            if dam_height is None:
                reliability -= 8

        # 陂/塘的面积比
        if site_type in ('陂', '塘'):
            dist_sar = get_param_distribution(site_type, 'surface_area_ratio')
            params['surface_area_ratio'] = dist_sar['mean'] * tech_factor
            if dam_height is None:
                reliability -= 8

        # 曼宁糙率（渠类）
        if site_type == '渠':
            dist_n = get_param_distribution('渠', 'n_manning')
            params['n_manning'] = dist_n['mean']

        params['tech_factor'] = tech_factor
        return params, max(0.0, reliability)

    def sample_parameters(self, params: Dict[str, float], site_type: str,
                          n_samples: int = 1000, seed: Optional[int] = None) -> Dict[str, np.ndarray]:
        """蒙特卡洛参数抽样"""
        if seed is not None:
            np.random.seed(seed)

        samples = {}
        tech_factor = params.get('tech_factor', 1.0)

        for param_name, base_val in params.items():
            if param_name == 'tech_factor':
                samples[param_name] = np.full(n_samples, base_val)
                continue

            dist = get_param_distribution(site_type, param_name)
            mean = dist.get('mean', base_val) * tech_factor
            std = dist.get('std', mean * 0.1)
            min_val = dist.get('min', mean * 0.3)
            max_val = dist.get('max', mean * 2.0)

            sampled = np.random.normal(mean, std, n_samples)
            sampled = np.clip(sampled, min_val, max_val)
            samples[param_name] = sampled

        return samples


# ==============================================
# 水力计算公式
# ==============================================

def calculate_weir_flow(Cd: float, weir_length: float, water_head: float) -> float:
    """宽顶堰流公式 Q = Cd * (2/3) * sqrt(2g) * L * h^(3/2)"""
    Q = Cd * (2 / 3) * math.sqrt(2 * GRAVITY) * weir_length * (max(water_head, 0) ** 1.5)
    return _clamp(Q, *CLAMP_RANGES['weir_flow'].values())


def calculate_canal_capacity(canal_width: float, water_depth: float,
                             slope: float, n_manning: float) -> float:
    """曼宁公式计算明渠输水能力 Q = A * v = A * (1/n) * R^(2/3) * S^(1/2)"""
    A = canal_width * water_depth
    P = canal_width + 2 * water_depth
    R = A / P if P > 0 else 0
    v = (1 / n_manning) * (R ** (2 / 3)) * (slope ** 0.5)
    Q = A * v
    return _clamp(Q, *CLAMP_RANGES['canal_capacity'].values())


def calculate_reservoir_capacity(dam_height: float, surface_area: float) -> float:
    """锥形库容估算 V = (1/3) * H * A * (0.4 + 0.1*H/10)"""
    V = (1 / 3) * dam_height * surface_area * (0.4 + 0.1 * dam_height / 10)
    return _clamp(V, *CLAMP_RANGES['reservoir_capacity'].values())


def calculate_well_yield(k: float, aquifer_thickness: float, water_depth: float,
                         well_radius: float, influence_radius: float = 100.0) -> float:
    """Dupuit稳定井流公式 Q = πk(H² - hw²) / ln(R/rw)"""
    H = aquifer_thickness
    hw = max(H - water_depth, 0.1)
    Q = math.pi * k * (H ** 2 - hw ** 2) / _safe_log(influence_radius / well_radius)
    return _clamp(Q, *CLAMP_RANGES['well_yield'].values())


# ==============================================
# 供水多边形生成
# ==============================================

def generate_supply_polygon(lon: float, lat: float, irrigation_area: float,
                            site_type: str, simplified: bool = False) -> Polygon:
    """生成供水范围多边形"""
    type_factor = TYPE_RANGE_FACTOR.get(site_type, 1.0)
    radius = math.sqrt(max(irrigation_area, 0.1)) * SUPPLY_POLYGON['area_to_radius_factor'] * type_factor

    radius = _clamp(radius, SUPPLY_POLYGON['min_radius'], SUPPLY_POLYGON['max_radius'])

    if simplified:
        n_points = SUPPLY_POLYGON['simplified_points']
        noise_amp = 0
    else:
        n_points = SUPPLY_POLYGON['detail_points']
        noise_amp = SUPPLY_POLYGON['noise_amplitude']

    points = []
    for i in range(n_points):
        angle = 2 * math.pi * i / n_points
        r = radius * (1 + (random.random() - 0.5) * 2 * noise_amp * 0.3)
        x = lon + r * math.cos(angle)
        y = lat + r * math.sin(angle)
        points.append((x, y))

    return Polygon(points)


def _estimate_irrigation_capacity(site_type: str, params: Dict[str, float],
                                  avg_rainfall: float, avg_runoff: float) -> float:
    """估算灌溉能力（内部辅助函数）"""
    eff_rainfall = avg_rainfall * EFFECTIVE_RAINFALL_COEFFICIENT
    water_demand = CROP_WATER_REQUIREMENT - eff_rainfall
    water_demand = max(water_demand, 100.0)

    diversion_coeff = TYPE_DIVERSION_COEFFICIENT.get(site_type, 0.5)
    efficiency = IRRIGATION_EFFICIENCY.get(site_type, 0.7)

    if site_type == '渠':
        canal_width = max(2.0, params.get('dam_height', 3.0) * 1.5)
        water_depth = params.get('dam_height', 3.0) * 0.7
        slope = 0.001
        n_manning = params.get('n_manning', 0.03)
        flow_rate = calculate_canal_capacity(canal_width, water_depth, slope, n_manning)
        annual_water = flow_rate * 3600 * 24 * 300
    elif site_type == '堰':
        weir_length = params.get('weir_length', 60.0)
        water_head = params.get('dam_height', 10.0) * 0.4
        Cd = params.get('Cd', 0.58)
        flow_rate = calculate_weir_flow(Cd, weir_length, water_head)
        annual_water = flow_rate * 3600 * 24 * 200
    elif site_type == '陂':
        dam_height = params.get('dam_height', 12.0)
        sar = params.get('surface_area_ratio', 80)
        surface_area = dam_height * sar
        capacity = calculate_reservoir_capacity(dam_height, surface_area)
        annual_water = capacity * 0.7
    elif site_type == '塘':
        dam_height = params.get('dam_height', 5.0)
        sar = params.get('surface_area_ratio', 60)
        surface_area = dam_height * sar
        capacity = calculate_reservoir_capacity(dam_height, surface_area)
        annual_water = capacity * 0.6
    elif site_type == '井':
        k = params.get('k_hydraulic', 2.5)
        aquifer = params.get('well_depth', 25.0) * 0.6
        water_depth = params.get('well_depth', 25.0) * 0.4
        rw = params.get('well_radius', 0.15)
        daily_yield = calculate_well_yield(k, aquifer, water_depth, rw)
        annual_water = daily_yield * 365
    else:
        annual_water = avg_runoff * 100000 * diversion_coeff

    effective_water = annual_water * efficiency
    irrigation_capacity = effective_water / water_demand

    return _clamp(irrigation_capacity, *CLAMP_RANGES['irrigation_capacity'].values())


# ==============================================
# 蒙特卡洛分析
# ==============================================

def monte_carlo_analysis(site_type: str, base_params: Dict[str, float],
                         avg_rainfall: float, avg_runoff: float,
                         n_samples: int = None, seed: int = None) -> Dict[str, Any]:
    """蒙特卡洛不确定性分析"""
    if n_samples is None:
        n_samples = MONTECARLO_DEFAULTS['n_samples']
    if seed is None:
        seed = MONTECARLO_DEFAULTS['seed']

    estimator = ParameterEstimator()
    param_samples = estimator.sample_parameters(base_params, site_type, n_samples, seed)

    rainfall_samples = np.random.normal(avg_rainfall, avg_rainfall * 0.15, n_samples)
    runoff_samples = np.random.normal(avg_runoff, avg_runoff * 0.2, n_samples)

    irrigation_results = np.zeros(n_samples)
    for i in range(n_samples):
        sample_params = {k: v[i] for k, v in param_samples.items()}
        irrigation_results[i] = _estimate_irrigation_capacity(
            site_type, sample_params,
            float(rainfall_samples[i]),
            float(runoff_samples[i])
        )

    # 统计
    mean_val = float(np.mean(irrigation_results))
    std_val = float(np.std(irrigation_results))
    cv = std_val / mean_val if mean_val > 0 else 0

    # 收敛检验
    half = n_samples // 2
    mean1 = float(np.mean(irrigation_results[:half]))
    mean2 = float(np.mean(irrigation_results[half:]))
    std1 = float(np.std(irrigation_results[:half]))
    std2 = float(np.std(irrigation_results[half:]))
    mean_error = abs(mean1 - mean2) / mean_val if mean_val > 0 else 1.0
    std_error = abs(std1 - std2) / std_val if std_val > 0 else 1.0

    # SRC 敏感性分析
    src_results = {}
    for param_name in param_samples:
        vals = param_samples[param_name]
        if np.std(vals) > 0 and std_val > 0:
            src = float(np.corrcoef(vals, irrigation_results)[0, 1])
        else:
            src = 0.0
        src_results[param_name] = src

    # 分位数
    quantiles = {
        'p5': float(np.percentile(irrigation_results, 5)),
        'p25': float(np.percentile(irrigation_results, 25)),
        'median': float(np.median(irrigation_results)),
        'p75': float(np.percentile(irrigation_results, 75)),
        'p95': float(np.percentile(irrigation_results, 95)),
    }

    return {
        'n_samples': n_samples,
        'mean': mean_val,
        'std': std_val,
        'cv': cv,
        'quantiles': quantiles,
        'src_analysis': src_results,
        'convergence': {
            'mean_error': mean_error,
            'std_error': std_error,
            'converged': (mean_error < MONTECARLO_DEFAULTS['convergence_mean_error']
                          and std_error < MONTECARLO_DEFAULTS['convergence_std_error'])
        }
    }


# ==============================================
# 主流程：功能复原
# ==============================================

def restore_site(site_data: Dict, hydrology_data: List[Dict]) -> Dict[str, Any]:
    """
    功能复原主流程
    Args:
        site_data: 遗迹数据字典
        hydrology_data: 水文数据列表
    Returns:
        复原结果字典
    """
    site_type = site_data['site_type']
    dynasty_order = site_data.get('dynasty_order', 10)
    preservation = site_data.get('preservation_status', '完好')
    irrigation_area_recorded = site_data.get('irrigation_area', 100)
    dam_height = site_data.get('dam_height')
    canal_length = site_data.get('canal_length')
    lon = site_data['longitude']
    lat = site_data['latitude']

    # 1. 平均水文数据
    if hydrology_data:
        avg_rainfall = sum(h['rainfall'] for h in hydrology_data) / len(hydrology_data)
        avg_runoff = sum(h['runoff'] for h in hydrology_data) / len(hydrology_data)
    else:
        avg_rainfall = 800.0
        avg_runoff = 300.0

    # 2. 参数估计
    estimator = ParameterEstimator()
    params, reliability = estimator.estimate_parameters(
        site_type, dynasty_order,
        irrigation_area=irrigation_area_recorded,
        dam_height=dam_height,
        canal_length=canal_length
    )

    # 3. 灌溉能力估算（原始）
    original_capacity = _estimate_irrigation_capacity(site_type, params, avg_rainfall, avg_runoff)

    # 4. 保存状态折减
    preservation_factor = PRESERVATION_FACTOR.get(preservation, 0.5)
    actual_capacity = original_capacity * preservation_factor

    # 5. 供水多边形
    supply_polygon = generate_supply_polygon(lon, lat, actual_capacity, site_type)

    # 6. 人口估算
    population = int(actual_capacity * GRAIN_PER_MU / PER_CAPITA_FOOD * 3)

    # 7. 备注
    notes_parts = []
    notes_parts.append(f"工程类型：{site_type}，朝代技术因子：{params['tech_factor']:.2f}")
    notes_parts.append(f"参数估计可靠度：{reliability:.1f}%")
    notes_parts.append(f"年均有效降雨：{avg_rainfall * EFFECTIVE_RAINFALL_COEFFICIENT:.0f} mm")
    notes_parts.append(f"原始灌溉能力：{original_capacity:.1f} 亩")
    notes_parts.append(f"保存折减系数：{preservation_factor}")
    notes_parts.append(f"实际灌溉能力：{actual_capacity:.1f} 亩")
    notes_parts.append(f"估算供水人口：约 {population} 人")

    # 8. 蒙特卡洛分析
    mc_result = monte_carlo_analysis(site_type, params, avg_rainfall, avg_runoff)

    return {
        'original_irrigation_capacity': original_capacity,
        'actual_irrigation_capacity': actual_capacity,
        'supply_polygon': supply_polygon,
        'supply_population': population,
        'restoration_notes': '\n'.join(notes_parts),
        'parameter_estimation': {
            'parameters': params,
            'reliability': reliability,
            'estimated_params_count': sum(1 for k in params if k not in ('Cd', 'efficiency', 'tech_factor'))
        },
        'uncertainty_analysis': mc_result,
    }
