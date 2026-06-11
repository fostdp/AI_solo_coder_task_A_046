import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class ExpertOpinion:
    """专家意见数据结构"""
    expert_id: str
    expert_name: str
    weights: Dict[str, float]
    confidence: float = 1.0
    pairwise_matrix: Optional[np.ndarray] = None
    consistency_ratio: float = 0.0


class AHPGroupDecision:
    """
    AHP群决策模块
    - 多位专家权重聚合
    - 一致性迭代修正
    - 专家分歧度分析
    """

    CRITERIA_ORDER = ['structural', 'hydrological', 'economic', 'cultural', 'environmental']

    RI_TABLE = {1: 0, 2: 0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}

    DEFAULT_EXPERTS = [
        {'id': 'hydrologist', 'name': '水利工程专家', 'confidence': 0.85,
         'weights': {'structural': 0.28, 'hydrological': 0.32, 'economic': 0.12, 'cultural': 0.13, 'environmental': 0.15}},
        {'id': 'archaeologist', 'name': '考古学专家', 'confidence': 0.75,
         'weights': {'structural': 0.20, 'hydrological': 0.15, 'economic': 0.10, 'cultural': 0.40, 'environmental': 0.15}},
        {'id': 'economist', 'name': '经济学专家', 'confidence': 0.70,
         'weights': {'structural': 0.20, 'hydrological': 0.20, 'economic': 0.35, 'cultural': 0.10, 'environmental': 0.15}},
        {'id': 'environmentalist', 'name': '环境学专家', 'confidence': 0.78,
         'weights': {'structural': 0.22, 'hydrological': 0.28, 'economic': 0.10, 'cultural': 0.10, 'environmental': 0.30}},
        {'id': 'default', 'name': '综合专家组', 'confidence': 1.0,
         'weights': {'structural': 0.30, 'hydrological': 0.25, 'economic': 0.15, 'cultural': 0.15, 'environmental': 0.15}},
    ]

    def build_pairwise_matrix(self, weights: Dict[str, float]) -> np.ndarray:
        """构建成对比较矩阵（Saaty 1-9标度）"""
        n = len(self.CRITERIA_ORDER)
        matrix = np.ones((n, n))
        for i in range(n):
            for j in range(i + 1, n):
                wi = weights.get(self.CRITERIA_ORDER[i], 0.2)
                wj = weights.get(self.CRITERIA_ORDER[j], 0.2)
                if wj <= 0:
                    ratio = 1.0
                else:
                    ratio = wi / wj
                saaty_val = self._to_saaty_scale(ratio)
                matrix[i][j] = saaty_val
                matrix[j][i] = 1.0 / saaty_val
        return matrix

    def _to_saaty_scale(self, ratio: float) -> float:
        """将连续比值映射到Saaty 1-9标度"""
        if ratio <= 1.0:
            return 1.0
        if ratio >= 9.0:
            return 9.0

        saaty_scale = [1, 2, 3, 4, 5, 6, 7, 8, 9]
        for i in range(len(saaty_scale) - 1):
            if saaty_scale[i] <= ratio <= saaty_scale[i + 1]:
                if (ratio - saaty_scale[i]) < (saaty_scale[i + 1] - ratio):
                    return float(saaty_scale[i])
                else:
                    return float(saaty_scale[i + 1])
        return 9.0

    def check_consistency(self, matrix: np.ndarray) -> Tuple[bool, float, float]:
        """
        一致性检验
        返回: (是否一致, CR值, CI值)
        """
        n = matrix.shape[0]
        if n <= 2:
            return True, 0.0, 0.0

        eigenvalues = np.linalg.eigvals(matrix)
        lambda_max = float(np.max(np.real(eigenvalues)))
        ci = (lambda_max - n) / (n - 1)
        ri = self.RI_TABLE.get(n, 1.49)
        cr = ci / ri if ri > 0 else 0.0

        return cr < 0.10, cr, ci

    def correct_consistency_iterative(self, matrix: np.ndarray, max_iter: int = 50,
                                       target_cr: float = 0.08) -> Tuple[np.ndarray, float, int]:
        """
        迭代法一致性修正
        通过调整不一致元素逐步降低CR
        """
        n = matrix.shape[0]
        current_matrix = matrix.copy()
        _, current_cr, _ = self.check_consistency(current_matrix)
        iterations = 0

        while current_cr > target_cr and iterations < max_iter:
            eigenvector = self._calc_eigenvector(current_matrix)

            max_diff = -1
            max_i, max_j = 0, 0

            for i in range(n):
                for j in range(i + 1, n):
                    if eigenvector[j] > 0:
                        ideal_ratio = eigenvector[i] / eigenvector[j]
                        actual = current_matrix[i][j]
                        diff = abs(actual - self._to_saaty_scale(ideal_ratio))
                        if diff > max_diff:
                            max_diff = diff
                            max_i, max_j = i, j

            if eigenvector[max_j] > 0:
                ideal = self._to_saaty_scale(eigenvector[max_i] / eigenvector[max_j])
                current_matrix[max_i][max_j] = current_matrix[max_i][max_j] * 0.7 + ideal * 0.3
                current_matrix[max_j][max_i] = 1.0 / current_matrix[max_i][max_j]

            _, current_cr, _ = self.check_consistency(current_matrix)
            iterations += 1

        return current_matrix, current_cr, iterations

    def _calc_eigenvector(self, matrix: np.ndarray) -> np.ndarray:
        """计算最大特征向量"""
        eigenvalues, eigenvectors = np.linalg.eig(matrix)
        max_idx = np.argmax(np.real(eigenvalues))
        eigenvector = np.real(eigenvectors[:, max_idx])
        return eigenvector / np.sum(eigenvector)

    def aggregate_experts_geometric(self, expert_matrices: List[np.ndarray],
                                     expert_confidences: List[float] = None) -> np.ndarray:
        """
        几何平均法聚合多位专家的成对比较矩阵
        可带专家置信度加权
        """
        if not expert_matrices:
            raise ValueError("至少需要一位专家的判断矩阵")

        n = expert_matrices[0].shape[0]
        aggregated = np.ones((n, n))

        if expert_confidences is None:
            expert_confidences = [1.0] * len(expert_matrices)

        total_confidence = sum(expert_confidences)
        normalized_confidences = [c / total_confidence for c in expert_confidences]

        for i in range(n):
            for j in range(i + 1, n):
                log_sum = 0.0
                for k, matrix in enumerate(expert_matrices):
                    if matrix[i][j] > 0:
                        log_sum += normalized_confidences[k] * np.log(matrix[i][j])
                aggregated[i][j] = np.exp(log_sum)
                aggregated[j][i] = 1.0 / aggregated[i][j]

        return aggregated

    def calculate_expert_disagreement(self, expert_matrices: List[np.ndarray]) -> Dict[str, Any]:
        """
        计算专家之间的分歧度
        """
        if len(expert_matrices) < 2:
            return {'disagreement_index': 0.0, 'level': '一致', 'details': '仅一位专家'}

        n = expert_matrices[0].shape[0]
        eigenvectors = []
        for m in expert_matrices:
            ev = self._calc_eigenvector(m)
            eigenvectors.append(ev)

        mean_ev = np.mean(eigenvectors, axis=0)
        std_ev = np.std(eigenvectors, axis=0)
        cv = np.sum(std_ev / (mean_ev + 1e-8)) / n

        level = '高度一致'
        if cv > 0.3:
            level = '分歧较大'
        elif cv > 0.15:
            level = '中等分歧'
        elif cv > 0.05:
            level = '基本一致'

        return {
            'disagreement_index': round(cv, 4),
            'level': level,
            'std_per_criterion': [round(v, 4) for v in std_ev.tolist()],
            'criteria': self.CRITERIA_ORDER
        }

    def get_default_experts(self) -> List[ExpertOpinion]:
        """获取默认专家库"""
        experts = []
        for exp in self.DEFAULT_EXPERTS:
            matrix = self.build_pairwise_matrix(exp['weights'])
            is_ok, cr, ci = self.check_consistency(matrix)
            expert = ExpertOpinion(
                expert_id=exp['id'],
                expert_name=exp['name'],
                weights=exp['weights'],
                confidence=exp['confidence'],
                pairwise_matrix=matrix,
                consistency_ratio=cr
            )
            experts.append(expert)
        return experts


class AHPSustainabilityAssessment:
    """
    AHP层次分析法 - 古代水利工程可持续性评估模型 v2.0

    新增特性：
    - 群决策支持：5位专家权重几何平均聚合
    - 一致性迭代修正：CR>0.1时自动迭代修正
    - 专家分歧度分析
    - 更严格的评分校准
    """

    CRITERIA_NAMES = {
        'structural': '结构完整性',
        'hydrological': '水文条件',
        'economic': '经济价值',
        'cultural': '文化价值',
        'environmental': '环境协调性'
    }

    CRITERIA_ORDER = ['structural', 'hydrological', 'economic', 'cultural', 'environmental']

    def __init__(self):
        self.group_decision = AHPGroupDecision()
        self._default_weights_cache = None

    def get_aggregated_weights(self, custom_weights: Dict[str, float] = None) -> Dict[str, Any]:
        """
        获取群决策聚合后的权重
        如果提供自定义权重则进行一致性修正后返回
        """
        if custom_weights:
            matrix = self.group_decision.build_pairwise_matrix(custom_weights)
            is_consistent, cr, ci = self.group_decision.check_consistency(matrix)
            expert = ExpertOpinion(
                expert_id='custom',
                expert_name='用户自定义',
                weights=custom_weights,
                confidence=1.0,
                pairwise_matrix=matrix,
                consistency_ratio=cr
            )

            if not is_consistent:
                corrected_matrix, new_cr, iterations = self.group_decision.correct_consistency_iterative(matrix)
                eigenvector = self.group_decision._calc_eigenvector(corrected_matrix)
                return {
                    'weights': {k: round(v, 4) for k, v in zip(self.CRITERIA_ORDER, eigenvector)},
                    'consistency_ratio': round(new_cr, 4),
                    'is_consistent': new_cr < 0.10,
                    'corrected': True,
                    'correction_iterations': iterations,
                    'original_cr': round(cr, 4),
                    'method': 'single_expert_corrected'
                }
            else:
                eigenvector = self.group_decision._calc_eigenvector(matrix)
                return {
                    'weights': {k: round(v, 4) for k, v in zip(self.CRITERIA_ORDER, eigenvector)},
                    'consistency_ratio': round(cr, 4),
                    'is_consistent': True,
                    'corrected': False,
                    'method': 'single_expert'
                }
        else:
            if self._default_weights_cache:
                return self._default_weights_cache

            experts = self.group_decision.get_default_experts()

            matrices = [e.pairwise_matrix for e in experts if e.pairwise_matrix is not None]
            confidences = [e.confidence for e in experts]

            aggregated_matrix = self.group_decision.aggregate_experts_geometric(
                matrices, confidences
            )

            is_consistent, cr, ci = self.group_decision.check_consistency(aggregated_matrix)
            correction_iterations = 0
            original_cr = cr

            if not is_consistent:
                aggregated_matrix, cr, correction_iterations = (
                    self.group_decision.correct_consistency_iterative(aggregated_matrix)
                )
                is_consistent = cr < 0.10

            final_weights = self.group_decision._calc_eigenvector(aggregated_matrix)

            disagreement = self.group_decision.calculate_expert_disagreement(matrices)

            result = {
                'weights': {k: round(float(v), 4) for k, v in zip(self.CRITERIA_ORDER, final_weights)},
                'consistency_ratio': round(cr, 4),
                'is_consistent': is_consistent,
                'corrected': correction_iterations > 0,
                'correction_iterations': correction_iterations,
                'original_cr': round(original_cr, 4),
                'method': 'group_geometric_mean',
                'expert_count': len(experts),
                'expert_disagreement': disagreement
            }

            self._default_weights_cache = result
            return result

    def evaluate_structural(self, site: Any) -> Tuple[float, Dict[str, float]]:
        score = 0.0
        details = {}

        status_scores = {'完好': 90, '部分损毁': 50, '完全废弃': 15}
        status_score = status_scores.get(site.preservation_status, 30)
        details['preservation_status'] = status_score
        score += status_score * 0.40

        if site.dam_height and site.dam_height > 0:
            dam_score = min(100, 30 + site.dam_height * 4)
            details['dam_height'] = dam_score
            score += dam_score * 0.25
        else:
            if site.site_type == '井':
                details['dam_height'] = 60
                score += 60 * 0.25
            else:
                details['dam_height'] = 20
                score += 20 * 0.25

        if site.canal_length and site.canal_length > 0:
            canal_score = min(100, 20 + site.canal_length * 1.5)
            details['canal_length'] = canal_score
            score += canal_score * 0.20
        else:
            if site.site_type in ['塘', '井']:
                details['canal_length'] = 50
                score += 50 * 0.20
            else:
                details['canal_length'] = 15
                score += 15 * 0.20

        area_score = min(100, 10 + np.log1p(site.irrigation_area) * 18)
        details['irrigation_area'] = area_score
        score += area_score * 0.15

        return round(score, 2), details

    def evaluate_hydrological(self, site: Any, modern_hydro: List[Any],
                                ancient_hydro: List[Any]) -> Tuple[float, Dict[str, float]]:
        score = 0.0
        details = {}

        if modern_hydro:
            modern_rain = float(np.mean([h.rainfall for h in modern_hydro]))
            modern_runoff = float(np.mean([h.runoff for h in modern_hydro]))
        else:
            modern_rain = 600.0
            modern_runoff = 150.0

        if ancient_hydro:
            ancient_rain = float(np.mean([h.rainfall for h in ancient_hydro]))
            ancient_runoff = float(np.mean([h.runoff for h in ancient_hydro]))
        else:
            ancient_rain = modern_rain
            ancient_runoff = modern_runoff

        if ancient_rain > 0:
            rain_ratio = min(modern_rain / ancient_rain, 1.5)
        else:
            rain_ratio = 1.0
        rain_stability = min(100, 30 + rain_ratio * 50)
        details['rainfall_stability'] = rain_stability
        score += rain_stability * 0.30

        if ancient_runoff > 0:
            runoff_ratio = min(modern_runoff / ancient_runoff, 1.5)
        else:
            runoff_ratio = 1.0
        runoff_stability = min(100, 30 + runoff_ratio * 50)
        details['runoff_stability'] = runoff_stability
        score += runoff_stability * 0.35

        if site.site_type == '井':
            groundwater_score = min(100, 40 + modern_runoff * 0.3)
        else:
            surface_score = min(100, 30 + modern_runoff * 0.4)
            groundwater_score = surface_score
        details['water_availability'] = groundwater_score
        score += groundwater_score * 0.35

        return round(score, 2), details

    def evaluate_economic(self, site: Any, original_capacity: float) -> Tuple[float, Dict[str, float]]:
        score = 0.0
        details = {}

        capacity_score = min(100, 10 + np.log1p(original_capacity) * 18)
        details['irrigation_potential'] = capacity_score
        score += capacity_score * 0.45

        type_economic = {'渠': 85, '堰': 80, '陂': 70, '塘': 60, '井': 50}
        type_score = type_economic.get(site.site_type, 60)
        details['type_efficiency'] = type_score
        score += type_score * 0.30

        status_factor = {'完好': 1.0, '部分损毁': 0.6, '完全废弃': 0.2}
        restoration_cost_score = min(100, 20 + (1 - status_factor.get(site.preservation_status, 0.5)) * 100)
        details['restoration_feasibility'] = restoration_cost_score
        score += restoration_cost_score * 0.25

        return round(score, 2), details

    def evaluate_cultural(self, site: Any) -> Tuple[float, Dict[str, float]]:
        score = 0.0
        details = {}

        dynasty_age = {1: 100, 2: 95, 3: 90, 4: 88, 5: 85, 6: 82, 7: 80, 8: 78,
                       9: 75, 10: 73, 11: 70, 12: 68, 13: 65, 14: 63, 15: 60,
                       16: 55, 17: 50}
        age_score = dynasty_age.get(site.dynasty_order, 50)
        details['historical_age'] = age_score
        score += age_score * 0.40

        type_significance = {'渠': 95, '堰': 90, '陂': 85, '塘': 70, '井': 75}
        significance_score = type_significance.get(site.site_type, 75)
        details['engineering_significance'] = significance_score
        score += significance_score * 0.35

        rarity_score = min(100, 30 + (1 - min(site.irrigation_area, 500) / 500) * 70)
        details['rarity'] = rarity_score
        score += rarity_score * 0.25

        return round(score, 2), details

    def evaluate_environmental(self, site: Any) -> Tuple[float, Dict[str, float]]:
        score = 0.0
        details = {}

        eco_compatibility = {'渠': 85, '堰': 80, '陂': 90, '塘': 88, '井': 95}
        eco_score = eco_compatibility.get(site.site_type, 80)
        details['ecosystem_compatibility'] = eco_score
        score += eco_score * 0.35

        status_env = {'完好': 90, '部分损毁': 60, '完全废弃': 30}
        env_score = status_env.get(site.preservation_status, 50)
        details['environmental_impact'] = env_score
        score += env_score * 0.35

        sustainability_score = min(100, 40 + np.log1p(site.irrigation_area) * 12)
        details['sustainability'] = sustainability_score
        score += sustainability_score * 0.30

        return round(score, 2), details

    def determine_grade(self, total_score: float) -> str:
        if total_score >= 85:
            return 'S'
        elif total_score >= 75:
            return 'A'
        elif total_score >= 60:
            return 'B'
        elif total_score >= 45:
            return 'C'
        elif total_score >= 30:
            return 'D'
        else:
            return 'E'

    def assess_site(self, site: Any, modern_hydro: List[Any],
                    ancient_hydro: List[Any], original_capacity: float,
                    custom_weights: Optional[Dict[str, float]] = None,
                    use_group_decision: bool = True) -> Dict[str, Any]:
        """
        主评估函数 v2.0
        """
        weight_result = self.get_aggregated_weights(custom_weights if not use_group_decision else None)
        weights = weight_result['weights']

        structural_score, structural_details = self.evaluate_structural(site)
        hydrological_score, hydrological_details = self.evaluate_hydrological(site, modern_hydro, ancient_hydro)
        economic_score, economic_details = self.evaluate_economic(site, original_capacity)
        cultural_score, cultural_details = self.evaluate_cultural(site)
        environmental_score, environmental_details = self.evaluate_environmental(site)

        total_score = (
            structural_score * weights['structural'] +
            hydrological_score * weights['hydrological'] +
            economic_score * weights['economic'] +
            cultural_score * weights['cultural'] +
            environmental_score * weights['environmental']
        )

        grade = self.determine_grade(total_score)
        restoration_potential = total_score >= 50 and site.preservation_status != '完全废弃'

        assessment_details = {
            'consistency_ratio': weight_result['consistency_ratio'],
            'is_consistent': weight_result['is_consistent'],
            'corrected': weight_result.get('corrected', False),
            'correction_iterations': weight_result.get('correction_iterations', 0),
            'original_cr': weight_result.get('original_cr', weight_result['consistency_ratio']),
            'criteria_weights': weights,
            'weight_method': weight_result.get('method', 'unknown'),
            'structural_details': structural_details,
            'hydrological_details': hydrological_details,
            'economic_details': economic_details,
            'cultural_details': cultural_details,
            'environmental_details': environmental_details,
            'recommendations': self._generate_recommendations(
                total_score, grade, site.preservation_status, structural_score, hydrological_score
            )
        }

        if 'expert_disagreement' in weight_result:
            assessment_details['expert_disagreement'] = weight_result['expert_disagreement']
            assessment_details['expert_count'] = weight_result.get('expert_count', 0)

        return {
            'structural_score': round(structural_score, 2),
            'hydrological_score': round(hydrological_score, 2),
            'economic_score': round(economic_score, 2),
            'cultural_score': round(cultural_score, 2),
            'environmental_score': round(environmental_score, 2),
            'total_score': round(total_score, 2),
            'grade': grade,
            'restoration_potential': restoration_potential,
            'assessment_details': assessment_details
        }

    def _generate_recommendations(self, total_score: float, grade: str,
                                    preservation_status: str,
                                    structural_score: float,
                                    hydro_score: float) -> List[str]:
        recommendations = []

        if preservation_status == '完全废弃':
            recommendations.append('立即启动文物保护应急程序，防止进一步损毁')
            recommendations.append('组织考古调查，完整记录工程遗存信息')
        elif preservation_status == '部分损毁':
            recommendations.append('制定修复方案，优先加固关键结构部位')
            recommendations.append('定期监测结构变化，建立预警机制')

        if total_score >= 80:
            recommendations.append('具备极高修复价值，建议优先纳入修复计划')
            recommendations.append('可申报省级或国家级文物保护单位')
        elif total_score >= 60:
            recommendations.append('具备较好修复潜力，可作为区域水利文化展示点')
        elif total_score >= 40:
            recommendations.append('修复成本较高，建议以保护现状为主')

        if structural_score < 40:
            recommendations.append('结构完整性较差，需专业工程评估')

        if hydro_score < 40:
            recommendations.append('水文条件变化较大，建议补充水文地质调查')

        return recommendations

    def get_expert_list(self) -> List[Dict[str, Any]]:
        """获取专家库列表"""
        experts = self.group_decision.get_default_experts()
        return [
            {
                'id': e.expert_id,
                'name': e.expert_name,
                'confidence': e.confidence,
                'weights': e.weights,
                'consistency_ratio': round(e.consistency_ratio, 4)
            }
            for e in experts
        ]
