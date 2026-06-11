"""
AHP可持续性评估算法
从 ahp_assessment.py 重构，参数已外置到 common/params/ahp_params.py
"""
import numpy as np
from typing import List, Dict, Tuple, Optional, Any
import math

from common.params.ahp_params import (
    CRITERIA,
    EXPERTS,
    SAATY_SCALE,
    RI_TABLE,
    CONSISTENCY_THRESHOLD,
    TARGET_CONSISTENCY,
    MAX_ITERATIONS,
    GRADES,
    RESTORATION_POTENTIAL,
    DISAGREEMENT_LEVELS,
    SCORING_BASELINES,
    get_grade,
    get_ri,
    get_disagreement_level,
    has_restoration_potential,
)


# ==============================================
# AHP 群决策类
# ==============================================

class AHPGroupDecision:
    """AHP群决策支持：多位专家权重聚合 + 一致性检验 + 迭代修正"""

    def __init__(self, criteria_names: List[str] = None):
        self.criteria_names = criteria_names or list(CRITERIA.keys())
        self.experts = EXPERTS
        self.n = len(self.criteria_names)

    def build_pairwise_matrix(self, weights: Dict[str, float]) -> np.ndarray:
        """根据权重向量构建Saaty标度的判断矩阵"""
        n = self.n
        matrix = np.ones((n, n))
        for i in range(n):
            for j in range(n):
                if i != j:
                    wi = weights[self.criteria_names[i]]
                    wj = weights[self.criteria_names[j]]
                    ratio = wi / wj
                    # 映射到Saaty标度
                    saaty_val = self._ratio_to_saaty(ratio)
                    matrix[i][j] = saaty_val
                    matrix[j][i] = 1 / saaty_val
        return matrix

    def _ratio_to_saaty(self, ratio: float) -> float:
        """连续比例映射到Saaty 1-9标度"""
        if ratio >= 1:
            return min(9.0, max(1.0, round(ratio)))
        else:
            return 1.0 / min(9.0, max(1.0, round(1.0 / ratio)))

    def calculate_eigenvector(self, matrix: np.ndarray) -> Tuple[np.ndarray, float]:
        """计算最大特征值和特征向量（权重）"""
        eigenvalues, eigenvectors = np.linalg.eig(matrix)
        max_idx = np.argmax(np.real(eigenvalues))
        lambda_max = np.real(eigenvalues[max_idx])
        weights = np.real(eigenvectors[:, max_idx])
        weights = weights / np.sum(weights)
        return weights, float(lambda_max)

    def check_consistency(self, matrix: np.ndarray) -> Dict[str, float]:
        """一致性检验"""
        n = matrix.shape[0]
        _, lambda_max = self.calculate_eigenvector(matrix)
        CI = (lambda_max - n) / (n - 1) if n > 1 else 0
        RI = get_ri(n)
        CR = CI / RI if RI > 0 else 0
        return {
            "lambda_max": lambda_max,
            "CI": CI,
            "RI": RI,
            "CR": CR,
            "consistent": CR < CONSISTENCY_THRESHOLD
        }

    def correct_consistency_iterative(self, matrix: np.ndarray,
                                       target_cr: float = None,
                                       max_iter: int = None) -> Tuple[np.ndarray, Dict]:
        """迭代一致性修正：自动调整最不一致元素直到CR达标"""
        if target_cr is None:
            target_cr = TARGET_CONSISTENCY
        if max_iter is None:
            max_iter = MAX_ITERATIONS

        current = matrix.copy()
        iterations = 0
        cr_history = []

        for i in range(max_iter):
            iterations += 1
            weights, lambda_max = self.calculate_eigenvector(current)
            n = current.shape[0]
            CI = (lambda_max - n) / (n - 1)
            RI = get_ri(n)
            CR = CI / RI if RI > 0 else 0
            cr_history.append(CR)

            if CR < target_cr:
                break

            # 找最不一致的元素
            max_diff = 0
            max_i, max_j = 0, 1
            for i_row in range(n):
                for j_col in range(i_row + 1, n):
                    ideal_ratio = weights[i_row] / weights[j_col]
                    actual = current[i_row][j_col]
                    diff = abs(math.log(actual / ideal_ratio))
                    if diff > max_diff:
                        max_diff = diff
                        max_i, max_j = i_row, j_col

            # 调整该元素向理想值靠拢
            ideal_ij = weights[max_i] / weights[max_j]
            saaty_ij = self._ratio_to_saaty(ideal_ij)
            current[max_i][max_j] = saaty_ij
            current[max_j][max_i] = 1 / saaty_ij

        final_cr = cr_history[-1] if cr_history else 1.0
        return current, {
            "iterations": iterations,
            "final_cr": final_cr,
            "initial_cr": cr_history[0] if cr_history else None,
            "cr_history": cr_history,
            "converged": final_cr < target_cr
        }

    def aggregate_experts_geometric(self) -> Tuple[Dict[str, float], Dict]:
        """几何平均法聚合多专家权重（对数空间加权平均）"""
        n = len(self.criteria_names)

        log_sums = np.zeros(n)
        total_confidence = 0

        for expert in self.experts:
            conf = expert["confidence"]
            weights = expert["weights"]
            for i, name in enumerate(self.criteria_names):
                w = weights.get(name, 1.0 / n)
                log_sums[i] += conf * math.log(w)
            total_confidence += conf

        aggregated_log = log_sums / total_confidence
        aggregated = np.exp(aggregated_log)
        aggregated = aggregated / np.sum(aggregated)

        # 计算专家分歧度
        expert_weights_list = []
        for expert in self.experts:
            w_list = [expert["weights"].get(name, 0) for name in self.criteria_names]
            expert_weights_list.append(w_list)

        expert_array = np.array(expert_weights_list)
        weight_stds = np.std(expert_array, axis=0)
        weight_means = np.mean(expert_array, axis=0)
        cvs = weight_stds / np.where(weight_means > 0, weight_means, 1e-10)
        avg_cv = float(np.mean(cvs))

        disagreement = get_disagreement_level(avg_cv)

        result_dict = dict(zip(self.criteria_names, aggregated.tolist()))
        return result_dict, {
            "expert_count": len(self.experts),
            "aggregation_method": "geometric_weighted",
            "expert_disagreement_cv": avg_cv,
            "disagreement_level": disagreement["level"],
            "disagreement_description": disagreement["description"],
            "per_criterion_cv": dict(zip(self.criteria_names, cvs.tolist())),
        }


# ==============================================
# 单准则评分函数
# ==============================================

def evaluate_structural(site) -> Dict[str, Any]:
    """结构完整性评价"""
    base = SCORING_BASELINES["preservation"]
    status_score = base.get(site.preservation_status, 30)

    dam_h = site.dam_height or 0
    dam_score = min(100, dam_h / SCORING_BASELINES["dam_height"]["excellent"] * 100)

    canal_l = site.canal_length or 0
    canal_score = min(100, canal_l / SCORING_BASELINES["canal_length"]["excellent"] * 100)

    area_score = min(100, site.irrigation_area / SCORING_BASELINES["irrigation_area"]["excellent"] * 100)

    sub = CRITERIA["structural"]["sub_criteria"]
    total = (status_score * sub["preservation_status"]["weight"]
             + dam_score * sub["dam_height"]["weight"]
             + canal_score * sub["canal_length"]["weight"]
             + area_score * sub["irrigation_area"]["weight"])

    return {
        "score": total,
        "details": {
            "preservation_status": status_score,
            "dam_height": dam_score,
            "canal_length": canal_score,
            "irrigation_area": area_score,
        }
    }


def evaluate_hydrological(site, hydrology_data: List = None) -> Dict[str, Any]:
    """水文条件评价"""
    if hydrology_data and len(hydrology_data) > 0:
        rainfalls = [h.rainfall for h in hydrology_data]
        runoffs = [h.runoff for h in hydrology_data]

        avg_rain = sum(rainfalls) / len(rainfalls)
        avg_runoff = sum(runoffs) / len(runoffs)

        rain_std = (sum((r - avg_rain) ** 2 for r in rainfalls) / len(rainfalls)) ** 0.5
        runoff_std = (sum((r - avg_runoff) ** 2 for r in runoffs) / len(runoffs)) ** 0.5

        rain_cv = rain_std / avg_rain if avg_rain > 0 else 1
        runoff_cv = runoff_std / avg_runoff if avg_runoff > 0 else 1

        rain_stab = min(100, max(0, (1 - rain_cv * 3) * 100))
        runoff_stab = min(100, max(0, (1 - runoff_cv * 3) * 100))

        water_avail = min(100, avg_runoff / 500 * 100)
    else:
        rain_stab = 50
        runoff_stab = 50
        water_avail = 50

    sub = CRITERIA["hydrological"]["sub_criteria"]
    total = (rain_stab * sub["rainfall_stability"]["weight"]
             + runoff_stab * sub["runoff_stability"]["weight"]
             + water_avail * sub["water_availability"]["weight"])

    return {
        "score": total,
        "details": {
            "rainfall_stability": rain_stab,
            "runoff_stability": runoff_stab,
            "water_availability": water_avail,
        }
    }


def evaluate_economic(site, restoration=None) -> Dict[str, Any]:
    """经济价值评价"""
    area = site.irrigation_area or 0
    irrigation_potential = min(100, area / 200 * 100)

    if restoration and restoration.actual_irrigation_capacity:
        capacity = restoration.actual_irrigation_capacity
        efficiency = min(100, capacity / max(area, 1) * 100)
    else:
        efficiency = 60

    status = site.preservation_status
    feasibility_scores = {"完好": 90, "部分损毁": 60, "完全废弃": 20}
    feasibility = feasibility_scores.get(status, 40)

    sub = CRITERIA["economic"]["sub_criteria"]
    total = (irrigation_potential * sub["irrigation_potential"]["weight"]
             + efficiency * sub["engineering_efficiency"]["weight"]
             + feasibility * sub["restoration_feasibility"]["weight"])

    return {
        "score": total,
        "details": {
            "irrigation_potential": irrigation_potential,
            "engineering_efficiency": efficiency,
            "restoration_feasibility": feasibility,
        }
    }


def evaluate_cultural(site) -> Dict[str, Any]:
    """文化价值评价"""
    dynasty_order = site.dynasty_order or 10

    age_score = 50
    for start, end, score in SCORING_BASELINES["dynasty_age_weight"]:
        if start <= dynasty_order <= end:
            age_score = score
            break

    significance_scores = {'渠': 70, '堰': 85, '陂': 80, '塘': 60, '井': 50}
    significance = significance_scores.get(site.site_type, 60)

    rarity_map = {'渠': 0.3, '堰': 0.2, '陂': 0.15, '塘': 0.25, '井': 0.1}
    rarity = min(100, (1 - rarity_map.get(site.site_type, 0.2)) * 100)

    sub = CRITERIA["cultural"]["sub_criteria"]
    total = (age_score * sub["historical_age"]["weight"]
             + significance * sub["engineering_significance"]["weight"]
             + rarity * sub["rarity_score"]["weight"])

    return {
        "score": total,
        "details": {
            "historical_age": age_score,
            "engineering_significance": significance,
            "rarity_score": rarity,
        }
    }


def evaluate_environmental(site) -> Dict[str, Any]:
    """环境协调性评价"""
    type_map = {
        '渠': {'eco': 85, 'impact': 70, 'sustain': 80},
        '堰': {'eco': 75, 'impact': 60, 'sustain': 70},
        '陂': {'eco': 80, 'impact': 50, 'sustain': 85},
        '塘': {'eco': 90, 'impact': 85, 'sustain': 90},
        '井': {'eco': 95, 'impact': 90, 'sustain': 75},
    }
    t = type_map.get(site.site_type, {'eco': 70, 'impact': 60, 'sustain': 70})

    sub = CRITERIA["environmental"]["sub_criteria"]
    total = (t['eco'] * sub["ecological_compatibility"]["weight"]
             + t['impact'] * sub["environmental_impact"]["weight"]
             + t['sustain'] * sub["sustainability"]["weight"])

    return {
        "score": total,
        "details": {
            "ecological_compatibility": t['eco'],
            "environmental_impact": t['impact'],
            "sustainability": t['sustain'],
        }
    }


# ==============================================
# 主流程：可持续性评估
# ==============================================

class AHPSustainabilityAssessment:
    """可持续性评估主类"""

    def __init__(self):
        self.criteria_names = list(CRITERIA.keys())
        self.group_decision = AHPGroupDecision(self.criteria_names)
        self.aggregated_weights, self.group_info = self.group_decision.aggregate_experts_geometric()

    def assess_site(self, site, hydrology_data: List = None, restoration=None) -> Dict[str, Any]:
        """评估单个遗迹的可持续性"""
        struct = evaluate_structural(site)
        hydro = evaluate_hydrological(site, hydrology_data)
        econ = evaluate_economic(site, restoration)
        cult = evaluate_cultural(site)
        env = evaluate_environmental(site)

        weights = self.aggregated_weights
        total = (
            struct["score"] * weights["structural"]
            + hydro["score"] * weights["hydrological"]
            + econ["score"] * weights["economic"]
            + cult["score"] * weights["cultural"]
            + env["score"] * weights["environmental"]
        )

        grade = get_grade(total)
        potential = has_restoration_potential(total, site.preservation_status)

        return {
            "structural_score": struct["score"],
            "hydrological_score": hydro["score"],
            "economic_score": econ["score"],
            "cultural_score": cult["score"],
            "environmental_score": env["score"],
            "total_score": total,
            "grade": grade,
            "restoration_potential": potential,
            "assessment_details": {
                "structural": struct["details"],
                "hydrological": hydro["details"],
                "economic": econ["details"],
                "cultural": cult["details"],
                "environmental": env["details"],
                "criteria_weights": weights,
            },
            "group_decision_info": self.group_info,
        }

    def get_expert_weights(self) -> List[Dict]:
        """获取所有专家的权重配置"""
        return [
            {
                "expert_id": e["id"],
                "expert_name": e["name"],
                "confidence": e["confidence"],
                "weights": e["weights"]
            }
            for e in self.experts
        ]

    def check_matrix_consistency(self, weights: Dict[str, float]) -> Dict[str, Any]:
        """检查给定权重矩阵的一致性"""
        matrix = self.group_decision.build_pairwise_matrix(weights)
        result = self.group_decision.check_consistency(matrix)
        eigvec, _ = self.group_decision.calculate_eigenvector(matrix)
        result["derived_weights"] = dict(zip(self.criteria_names, eigvec.tolist()))
        return result

    def correct_matrix(self, weights: Dict[str, float]) -> Dict[str, Any]:
        """迭代修正一致性"""
        matrix = self.group_decision.build_pairwise_matrix(weights)
        corrected, info = self.group_decision.correct_consistency_iterative(matrix)
        eigvec, _ = self.group_decision.calculate_eigenvector(corrected)
        return {
            "original_weights": weights,
            "corrected_weights": dict(zip(self.criteria_names, eigvec.tolist())),
            "correction_info": info,
            "corrected_matrix": corrected.tolist(),
        }


# 单例实例
_assessment_instance = None


def get_assessment() -> AHPSustainabilityAssessment:
    global _assessment_instance
    if _assessment_instance is None:
        _assessment_instance = AHPSustainabilityAssessment()
    return _assessment_instance
