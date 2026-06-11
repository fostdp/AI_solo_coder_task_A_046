import math
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from shapely.geometry import Point, Polygon
from shapely.ops import transform
from dataclasses import dataclass
import json


@dataclass
class MonteCarloResult:
    """蒙特卡洛模拟结果"""
    mean: float
    std: float
    median: float
    p5: float
    p25: float
    p75: float
    p95: float
    cv: float
    samples: np.ndarray


class ParameterEstimator:
    """
    缺失参数估计器 - 基于同类型遗迹统计回归的参数反算
    当结构参数缺失时，通过经验公式和统计规律进行合理估计
    """

    TYPE_PARAM_DISTRIBUTIONS = {
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

    DYNASTY_TECH_FACTOR = {
        1: 0.70, 2: 0.78, 3: 0.82, 4: 0.88, 5: 0.90, 6: 0.88,
        7: 0.85, 8: 0.87, 9: 0.90, 10: 0.93, 11: 0.98, 12: 0.92,
        13: 1.00, 14: 0.97, 15: 0.95, 16: 1.02, 17: 1.05
    }

    def estimate_parameters(self, site_type: str, dynasty_order: int,
                            known_params: Dict[str, float],
                            irrigation_area: float) -> Dict[str, Any]:
        """
        基于同类型遗迹统计分布和已知参数，估计缺失参数
        返回估计值、置信区间和估计可靠性
        """
        dists = self.TYPE_PARAM_DISTRIBUTIONS.get(site_type, {})
        tech_factor = self.DYNASTY_TECH_FACTOR.get(dynasty_order, 1.0)

        estimated = {}
        param_sources = {}
        reliability_score = 100.0

        for param_name, dist in dists.items():
            if param_name in known_params and known_params[param_name] is not None:
                estimated[param_name] = known_params[param_name]
                param_sources[param_name] = 'measured'
            else:
                estimate = dist['mean'] * tech_factor
                estimate = max(dist['min'], min(dist['max'], estimate))
                estimated[param_name] = estimate
                param_sources[param_name] = 'estimated'
                reliability_score -= 8.0

        if irrigation_area and irrigation_area > 0:
            if site_type in ['渠', '堰'] and 'canal_length' not in known_params:
                area_estimate = max(5.0, math.sqrt(irrigation_area) * 3.5)
                estimated['canal_length'] = area_estimate
                param_sources['canal_length'] = 'area_regression'
                reliability_score -= 3.0

            if site_type in ['堰', '陂', '塘'] and 'dam_height' not in known_params:
                height_estimate = max(1.0, math.sqrt(irrigation_area) * 0.6)
                estimated['dam_height'] = min(dist['max'], height_estimate)
                param_sources['dam_height'] = 'area_regression'
                reliability_score -= 3.0

        reliability_score = max(20.0, min(100.0, reliability_score))

        return {
            'parameters': estimated,
            'sources': param_sources,
            'reliability_score': round(reliability_score, 1),
            'tech_factor': round(tech_factor, 3),
            'estimated_count': sum(1 for s in param_sources.values() if s != 'measured')
        }


class HydraulicRestorationModel:
    """
    古代水利工程功能复原模型 v2.0
    - 基于工程结构参数和古代水文数据反推原始灌溉能力
    - 新增：参数估计（缺失参数智能补全）
    - 新增：蒙特卡洛不确定性分析（置信区间、敏感性分析）
    - 新增：收敛性保护（防止计算发散）
    """

    CROP_WATER_REQUIREMENT = 450.0
    GRAVITY = 9.81

    IRRIGATION_EFFICIENCY = {
        '渠': 0.75, '堰': 0.70, '陂': 0.80, '塘': 0.65, '井': 0.50
    }

    PRESERVATION_FACTOR = {
        '完好': 0.95, '部分损毁': 0.55, '完全废弃': 0.10
    }

    TYPE_DIVERSION_COEFFICIENT = {
        '渠': 0.60, '堰': 0.50, '陂': 0.35, '塘': 0.25, '井': 0.08
    }

    def __init__(self):
        self.param_estimator = ParameterEstimator()
        self._monte_carlo_cache = {}

    def _safe_log(self, x: float, default: float = -10.0) -> float:
        """安全对数，防止负数或零导致发散"""
        if x <= 0:
            return default
        return math.log(x)

    def _safe_sqrt(self, x: float) -> float:
        """安全平方根"""
        if x <= 0:
            return 0.0
        return math.sqrt(x)

    def _clamp(self, value: float, min_val: float, max_val: float) -> float:
        """数值钳制，防止极端值导致发散"""
        return max(min_val, min(max_val, value))

    def calculate_weir_flow(self, dam_height: float, weir_length: float = 50.0,
                            Cd: float = 0.62) -> float:
        """堰流计算 - 宽顶堰公式"""
        if dam_height is None or dam_height <= 0:
            return 0.0
        h = max(dam_height * 0.7, 0.1)
        Cd_safe = self._clamp(Cd, 0.3, 0.9)
        weir_length_safe = self._clamp(weir_length, 1.0, 500.0)
        h_safe = self._clamp(h, 0.1, 50.0)
        flow = Cd_safe * (2.0 / 3.0) * self._safe_sqrt(2 * self.GRAVITY) * weir_length_safe * (h_safe ** 1.5)
        return self._clamp(flow, 0.0, 10000.0)

    def calculate_canal_capacity(self, canal_length: float, dam_height: float = 2.0,
                                  n_manning: float = 0.03, slope: float = 0.0005) -> float:
        """明渠输水能力 - 曼宁公式"""
        if canal_length is None or canal_length <= 0:
            return 0.0
        width = 1.5 + self._safe_sqrt(canal_length) * 0.3
        depth = max(0.3, (dam_height or 2.0) * 0.4)
        area = width * depth
        wetted_perimeter = width + 2 * depth
        if wetted_perimeter <= 0:
            return 0.0
        hydraulic_radius = area / wetted_perimeter
        n_safe = self._clamp(n_manning, 0.01, 0.1)
        slope_safe = self._clamp(slope, 0.0001, 0.05)
        velocity = (1.0 / n_safe) * (hydraulic_radius ** (2.0 / 3.0)) * (slope_safe ** 0.5)
        capacity = area * velocity
        return self._clamp(capacity, 0.0, 5000.0)

    def calculate_reservoir_capacity(self, dam_height: float, surface_area_ratio: float = 80.0) -> float:
        """水库库容计算 - 锥形近似"""
        if dam_height is None or dam_height <= 0:
            return 1000.0
        dam_height_safe = self._clamp(dam_height, 1.0, 100.0)
        sar_safe = self._clamp(surface_area_ratio, 10.0, 500.0)
        surface_area = sar_safe * 100
        capacity = (1.0 / 3.0) * dam_height_safe * surface_area * (0.4 + 0.1 * dam_height_safe / 10.0)
        return self._clamp(capacity, 100.0, 1e8)

    def calculate_well_yield(self, well_depth: float, well_radius: float = 0.15,
                              k: float = 2.5, influence_radius: float = 1000.0) -> float:
        """管井涌水量 - Dupuit稳定流公式"""
        if well_depth <= 0 or well_radius <= 0:
            return 0.0
        h0 = max(1.0, well_depth * 0.8)
        hw = max(0.5, well_depth * 0.5)
        k_safe = self._clamp(k, 0.1, 50.0)
        r_safe = self._clamp(well_radius, 0.05, 2.0)
        R_safe = self._clamp(influence_radius, 100.0, 10000.0)
        denom = self._safe_log(R_safe / r_safe)
        if abs(denom) < 0.01:
            return 0.0
        yield_val = (math.pi * k_safe * (h0 ** 2 - hw ** 2)) / denom
        return self._clamp(yield_val, 0.0, 1000.0)

    def calculate_available_water(self, site_type: str, params: Dict[str, float],
                                  avg_runoff: float) -> float:
        """可用水量计算 - 带收敛保护"""
        annual_runoff_volume = avg_runoff * 10000.0
        if annual_runoff_volume <= 0:
            annual_runoff_volume = 10000.0

        diversion = self.TYPE_DIVERSION_COEFFICIENT.get(site_type, 0.3)

        if site_type == '渠':
            canal_flow = self.calculate_canal_capacity(
                params.get('canal_length', 50),
                params.get('dam_height', 2),
                params.get('n_manning', 0.03)
            )
            canal_annual = canal_flow * 86400 * 200
            return self._clamp(min(annual_runoff_volume * diversion, canal_annual), 100.0, 1e9)

        elif site_type == '堰':
            weir_flow = self.calculate_weir_flow(
                params.get('dam_height', 5),
                params.get('weir_length', 50),
                params.get('Cd', 0.6)
            )
            weir_annual = weir_flow * 86400 * 180
            return self._clamp(min(annual_runoff_volume * diversion, weir_annual), 100.0, 1e9)

        elif site_type == '陂':
            reservoir_cap = self.calculate_reservoir_capacity(
                params.get('dam_height', 10),
                params.get('surface_area_ratio', 80)
            )
            return self._clamp(min(annual_runoff_volume * diversion, reservoir_cap * 1.5), 100.0, 1e9)

        elif site_type == '塘':
            reservoir_cap = self.calculate_reservoir_capacity(
                params.get('dam_height', 5),
                params.get('surface_area_ratio', 60)
            )
            return self._clamp(reservoir_cap * 1.2, 100.0, 1e8)

        elif site_type == '井':
            well_yield = self.calculate_well_yield(
                params.get('well_depth', 25),
                params.get('well_radius', 0.15),
                params.get('k_hydraulic', 2.5)
            )
            well_annual = well_yield * 86400 * 250
            return self._clamp(well_annual, 100.0, 1e7)

        return annual_runoff_volume * 0.3

    def calculate_irrigation_capacity(self, available_water: float, site_type: str,
                                      avg_rainfall: float, efficiency: float = None) -> float:
        """灌溉面积反算 - 带收敛保护"""
        if efficiency is None:
            efficiency = self.IRRIGATION_EFFICIENCY.get(site_type, 0.6)
        efficiency_safe = self._clamp(efficiency, 0.1, 0.95)
        net_rain = avg_rainfall * 0.6 * 10
        net_requirement = max(self.CROP_WATER_REQUIREMENT * 10 - net_rain,
                              self.CROP_WATER_REQUIREMENT * 3)
        effective_water = max(available_water * efficiency_safe, 100.0)
        capacity = effective_water / net_requirement
        return self._clamp(capacity, 0.1, 100000.0)

    def generate_supply_polygon(self, lng: float, lat: float,
                                irrigation_capacity: float,
                                site_type: str, simplify: bool = False) -> Dict[str, Any]:
        """生成供水范围多边形 - 可选择简化以提升性能"""
        if irrigation_capacity <= 0:
            return None

        base_radius = self._safe_sqrt(irrigation_capacity / math.pi) * 0.003
        type_factors = {'渠': 1.5, '堰': 1.0, '陂': 0.8, '塘': 0.6, '井': 0.3}
        radius = base_radius * type_factors.get(site_type, 1.0)
        radius = max(0.005, min(radius, 1.5))

        num_points = 8 if simplify else 24
        points = []
        for i in range(num_points):
            angle = 2 * math.pi * i / num_points
            if simplify:
                r = radius * 0.85
            else:
                noise = 0.75 + 0.5 * math.sin(angle * 3) * math.cos(angle * 2)
                r = radius * noise
            x = lng + r * math.cos(angle) / math.cos(math.radians(lat))
            y = lat + r * math.sin(angle)
            points.append((x, y))
        points.append(points[0])

        polygon = Polygon(points)
        geojson = {
            "type": "Polygon",
            "coordinates": [list(polygon.exterior.coords)]
        }
        return geojson

    def estimate_supply_population(self, irrigation_capacity: float) -> int:
        if irrigation_capacity <= 0:
            return 0
        per_capita_food = 250.0
        grain_per_mu = 150.0
        total_grain = irrigation_capacity * grain_per_mu * 0.0015
        population = total_grain / per_capita_food * 3
        return int(max(0, min(100000, population)))

    def monte_carlo_analysis(self, site: Any, hydrology_data: List[Any],
                              n_samples: int = 1000,
                              seed: int = 42) -> Dict[str, Any]:
        """
        蒙特卡洛不确定性分析
        - 对参数的不确定性进行抽样
        - 计算输出变量的统计分布
        - 敏感性分析（SRC标准化回归系数）
        """
        np.random.seed(seed)

        known_params = {
            'dam_height': site.dam_height,
            'canal_length': site.canal_length
        }
        est_result = self.param_estimator.estimate_parameters(
            site.site_type, site.dynasty_order, known_params, site.irrigation_area
        )
        params = est_result['parameters']
        sources = est_result['sources']
        dists = self.param_estimator.TYPE_PARAM_DISTRIBUTIONS.get(site.site_type, {})

        samples_storage = {}
        for param_name, dist in dists.items():
            if sources.get(param_name) == 'measured':
                samples_storage[param_name] = np.full(n_samples, params[param_name])
            else:
                mean = dist['mean'] * est_result['tech_factor']
                std = dist['std']
                samples = np.random.normal(mean, std, n_samples)
                samples = np.clip(samples, dist['min'], dist['max'])
                samples_storage[param_name] = samples

        runoff_values = [h.runoff for h in hydrology_data]
        if len(runoff_values) > 0:
            runoff_mean = np.mean(runoff_values)
            runoff_std = np.std(runoff_values) or runoff_mean * 0.2
            runoff_samples = np.random.normal(runoff_mean, runoff_std, n_samples)
            runoff_samples = np.clip(runoff_samples, runoff_mean * 0.3, runoff_mean * 2.0)
        else:
            runoff_samples = np.full(n_samples, 150.0)

        rainfall_values = [h.rainfall for h in hydrology_data]
        if len(rainfall_values) > 0:
            rainfall_mean = np.mean(rainfall_values)
            rainfall_std = np.std(rainfall_values) or rainfall_mean * 0.15
            rainfall_samples = np.random.normal(rainfall_mean, rainfall_std, n_samples)
        else:
            rainfall_samples = np.full(n_samples, 600.0)

        capacity_samples = np.zeros(n_samples)
        for i in range(n_samples):
            sample_params = {k: v[i] for k, v in samples_storage.items()}
            available_water = self.calculate_available_water(
                site.site_type, sample_params, runoff_samples[i]
            )
            efficiency = sample_params.get('efficiency',
                                           self.IRRIGATION_EFFICIENCY.get(site.site_type, 0.6))
            capacity = self.calculate_irrigation_capacity(
                available_water, site.site_type, rainfall_samples[i], efficiency
            )
            capacity_samples[i] = capacity

        mc_result = self._calc_mc_stats(capacity_samples)

        sensitivity = self._sensitivity_analysis(
            samples_storage, runoff_samples, rainfall_samples, capacity_samples
        )

        return {
            'capacity_monte_carlo': {
                'mean': mc_result.mean,
                'std': mc_result.std,
                'cv': mc_result.cv,
                'median': mc_result.median,
                'percentiles': {
                    'p5': mc_result.p5, 'p25': mc_result.p25,
                    'p75': mc_result.p75, 'p95': mc_result.p95
                },
                'n_samples': n_samples,
                'convergence': self._check_convergence(capacity_samples)
            },
            'parameter_estimation': {
                'estimated_params': {k: round(v, 3) for k, v in params.items()},
                'sources': sources,
                'reliability_score': est_result['reliability_score'],
                'tech_factor': est_result['tech_factor'],
                'estimated_count': est_result['estimated_count']
            },
            'sensitivity_analysis': sensitivity
        }

    def _calc_mc_stats(self, samples: np.ndarray) -> MonteCarloResult:
        """计算蒙特卡洛统计量"""
        mean_val = float(np.mean(samples))
        std_val = float(np.std(samples))
        cv_val = std_val / mean_val if mean_val > 0 else 1.0

        return MonteCarloResult(
            mean=mean_val,
            std=std_val,
            median=float(np.median(samples)),
            p5=float(np.percentile(samples, 5)),
            p25=float(np.percentile(samples, 25)),
            p75=float(np.percentile(samples, 75)),
            p95=float(np.percentile(samples, 95)),
            cv=round(cv_val, 4),
            samples=samples
        )

    def _check_convergence(self, samples: np.ndarray) -> Dict[str, Any]:
        """检查蒙特卡洛收敛性"""
        if len(samples) < 100:
            return {'converged': False, 'reason': '样本量不足'}

        first_half = samples[:len(samples) // 2]
        second_half = samples[len(samples) // 2:]

        mean_diff = abs(np.mean(first_half) - np.mean(second_half)) / np.mean(samples)
        std_diff = abs(np.std(first_half) - np.std(second_half)) / np.std(samples)

        converged = mean_diff < 0.05 and std_diff < 0.10

        return {
            'converged': converged,
            'mean_relative_error': round(mean_diff, 4),
            'std_relative_error': round(std_diff, 4),
            'recommended_samples': 2000 if not converged else len(samples)
        }

    def _sensitivity_analysis(self, param_samples: Dict[str, np.ndarray],
                               runoff_samples: np.ndarray,
                               rainfall_samples: np.ndarray,
                               output_samples: np.ndarray) -> Dict[str, Any]:
        """
        敏感性分析 - 标准化回归系数法 (SRC)
        衡量各参数不确定性对输出不确定性的贡献比例
        """
        output_std = np.std(output_samples)
        if output_std == 0:
            return {}

        sensitivities = {}

        for name, samples in param_samples.items():
            param_std = np.std(samples)
            if param_std == 0:
                sensitivities[name] = 0.0
                continue
            cov = np.cov(samples, output_samples)[0, 1]
            src = cov * param_std / (output_std * param_std) if output_std > 0 else 0
            sensitivities[name] = round(abs(src), 4)

        runoff_std = np.std(runoff_samples)
        if runoff_std > 0:
            cov = np.cov(runoff_samples, output_samples)[0, 1]
            sensitivities['runoff'] = round(abs(cov / (output_std * runoff_std)) if output_std > 0 else 0, 4)

        rain_std = np.std(rainfall_samples)
        if rain_std > 0:
            cov = np.cov(rainfall_samples, output_samples)[0, 1]
            sensitivities['rainfall'] = round(abs(cov / (output_std * rain_std)) if output_std > 0 else 0, 4)

        total = sum(sensitivities.values()) or 1.0
        normalized = {k: round(v / total, 4) for k, v in sensitivities.items()}

        most_influential = max(normalized, key=normalized.get) if normalized else 'unknown'

        return {
            'src_coefficients': sensitivities,
            'normalized_contributions': normalized,
            'most_influential': most_influential,
            'method': 'Standardized Regression Coefficients (SRC)'
        }

    def restore_site(self, site: Any, hydrology_data: List[Any],
                     with_monte_carlo: bool = True,
                     n_samples: int = 1000) -> Dict[str, Any]:
        """
        主入口：水利遗迹功能复原
        v2.0：包含参数估计、确定性计算、蒙特卡洛不确定性分析
        """
        dynasty_order = getattr(site, 'dynasty_order', 11)

        filtered = [h for h in hydrology_data if
                    ((dynasty_order <= 4 and -770 <= h.year <= 220) or
                     (5 <= dynasty_order <= 9 and 220 < h.year <= 618) or
                     (10 <= dynasty_order <= 12 and 581 < h.year <= 960) or
                     (13 <= dynasty_order <= 14 and 960 < h.year <= 1279) or
                     (dynasty_order >= 15 and h.year > 1279))]

        if not filtered:
            filtered = hydrology_data[:50] if len(hydrology_data) >= 50 else hydrology_data

        avg_rainfall = float(np.mean([h.rainfall for h in filtered])) if filtered else 600.0
        avg_runoff = float(np.mean([h.runoff for h in filtered])) if filtered else 150.0

        known_params = {
            'dam_height': getattr(site, 'dam_height', None),
            'canal_length': getattr(site, 'canal_length', None),
        }

        est_result = self.param_estimator.estimate_parameters(
            site.site_type, dynasty_order, known_params,
            getattr(site, 'irrigation_area', 50.0)
        )
        params = est_result['parameters']

        available_water = self.calculate_available_water(
            site.site_type, params, avg_runoff
        )

        original_capacity = self.calculate_irrigation_capacity(
            available_water, site.site_type, avg_rainfall
        )

        preservation_factor = self.PRESERVATION_FACTOR.get(
            getattr(site, 'preservation_status', '部分损毁'), 0.5
        )
        actual_capacity = original_capacity * preservation_factor

        supply_polygon = self.generate_supply_polygon(
            getattr(site, 'longitude', 110.0),
            getattr(site, 'latitude', 34.0),
            original_capacity, site.site_type
        )

        supply_population = self.estimate_supply_population(original_capacity)

        mc_analysis = None
        if with_monte_carlo:
            try:
                mc_analysis = self.monte_carlo_analysis(site, filtered, n_samples)
            except Exception as e:
                print(f"蒙特卡洛分析失败: {e}")
                mc_analysis = {'error': str(e)}

        notes_parts = []
        notes_parts.append(f"基于{len(filtered)}条同期水文记录重建")
        notes_parts.append(f"平均降雨量: {avg_rainfall:.1f}mm/年")
        notes_parts.append(f"平均径流量: {avg_runoff:.1f}万m³/km²")
        notes_parts.append(f"理论可用水量: {available_water:.1f}m³")
        if known_params.get('dam_height'):
            notes_parts.append(f"坝高: {known_params['dam_height']}m")
        else:
            notes_parts.append(f"坝高估计值: {params.get('dam_height', 0):.1f}m")
        if known_params.get('canal_length'):
            notes_parts.append(f"渠长: {known_params['canal_length']}km")
        elif 'canal_length' in params:
            notes_parts.append(f"渠长估计值: {params['canal_length']:.1f}km")

        if est_result['estimated_count'] > 0:
            notes_parts.append(f"参数估计可靠度: {est_result['reliability_score']}%")
        notes = "；".join(notes_parts) + "。"

        result = {
            "original_irrigation_capacity": round(max(0.1, original_capacity), 2),
            "actual_irrigation_capacity": round(max(0.0, actual_capacity), 2),
            "water_supply_range_geom": supply_polygon,
            "supply_population": max(0, supply_population),
            "restoration_notes": notes,
            "hydrology_summary": {
                "avg_rainfall": round(avg_rainfall, 1),
                "avg_runoff": round(avg_runoff, 1),
                "records_count": len(filtered)
            },
            "parameter_estimation": {
                "estimated_params": {k: round(v, 3) for k, v in params.items()},
                "sources": est_result['sources'],
                "reliability_score": est_result['reliability_score'],
                "tech_factor": est_result['tech_factor'],
                "estimated_count": est_result['estimated_count']
            }
        }

        if mc_analysis:
            result["uncertainty_analysis"] = mc_analysis

        return result
