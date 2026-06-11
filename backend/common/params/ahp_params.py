"""
AHP可持续性评估参数 - 外置配置
所有AHP相关参数集中管理
"""
from typing import Dict, List, Any


# ========== 评价准则 ==========
CRITERIA = {
    "structural": {
        "name": "结构完整性",
        "weight": 0.30,
        "sub_criteria": {
            "preservation_status": {"name": "保存状态", "weight": 0.40},
            "dam_height": {"name": "坝高", "weight": 0.25},
            "canal_length": {"name": "渠长", "weight": 0.20},
            "irrigation_area": {"name": "灌溉面积", "weight": 0.15},
        }
    },
    "hydrological": {
        "name": "水文条件",
        "weight": 0.25,
        "sub_criteria": {
            "rainfall_stability": {"name": "降雨稳定性", "weight": 0.30},
            "runoff_stability": {"name": "径流稳定性", "weight": 0.35},
            "water_availability": {"name": "水资源量", "weight": 0.35},
        }
    },
    "economic": {
        "name": "经济价值",
        "weight": 0.15,
        "sub_criteria": {
            "irrigation_potential": {"name": "灌溉潜力", "weight": 0.45},
            "engineering_efficiency": {"name": "工程效率", "weight": 0.30},
            "restoration_feasibility": {"name": "修复可行性", "weight": 0.25},
        }
    },
    "cultural": {
        "name": "文化价值",
        "weight": 0.15,
        "sub_criteria": {
            "historical_age": {"name": "历史年代", "weight": 0.40},
            "engineering_significance": {"name": "工程意义", "weight": 0.35},
            "rarity_score": {"name": "稀缺性", "weight": 0.25},
        }
    },
    "environmental": {
        "name": "环境协调性",
        "weight": 0.15,
        "sub_criteria": {
            "ecological_compatibility": {"name": "生态兼容性", "weight": 0.35},
            "environmental_impact": {"name": "环境影响", "weight": 0.35},
            "sustainability": {"name": "可持续性", "weight": 0.30},
        }
    }
}


# ========== 专家权重配置 ==========
EXPERTS: List[Dict[str, Any]] = [
    {
        "id": "water_engineer",
        "name": "水利工程专家",
        "confidence": 0.85,
        "weights": {
            "structural": 0.28,
            "hydrological": 0.32,
            "economic": 0.12,
            "cultural": 0.13,
            "environmental": 0.15
        }
    },
    {
        "id": "archaeologist",
        "name": "考古学专家",
        "confidence": 0.75,
        "weights": {
            "structural": 0.20,
            "hydrological": 0.15,
            "economic": 0.10,
            "cultural": 0.40,
            "environmental": 0.15
        }
    },
    {
        "id": "economist",
        "name": "经济学专家",
        "confidence": 0.70,
        "weights": {
            "structural": 0.20,
            "hydrological": 0.20,
            "economic": 0.35,
            "cultural": 0.10,
            "environmental": 0.15
        }
    },
    {
        "id": "environmentalist",
        "name": "环境学专家",
        "confidence": 0.78,
        "weights": {
            "structural": 0.22,
            "hydrological": 0.28,
            "economic": 0.10,
            "cultural": 0.10,
            "environmental": 0.30
        }
    },
    {
        "id": "comprehensive",
        "name": "综合评估专家",
        "confidence": 1.00,
        "weights": {
            "structural": 0.30,
            "hydrological": 0.25,
            "economic": 0.15,
            "cultural": 0.15,
            "environmental": 0.15
        }
    }
]


# ========== Saaty 标度 ==========
SAATY_SCALE = [1, 2, 3, 4, 5, 6, 7, 8, 9]


# ========== RI 随机一致性指标 ==========
# n=1..15 的 RI 值
RI_TABLE = {
    1: 0.00,
    2: 0.00,
    3: 0.58,
    4: 0.90,
    5: 1.12,
    6: 1.24,
    7: 1.32,
    8: 1.41,
    9: 1.45,
    10: 1.49,
    11: 1.51,
    12: 1.54,
    13: 1.56,
    14: 1.57,
    15: 1.59
}


# ========== 一致性阈值 ==========
CONSISTENCY_THRESHOLD = 0.10  # CR < 0.1 视为一致
TARGET_CONSISTENCY = 0.08     # 迭代修正目标
MAX_ITERATIONS = 50           # 最大迭代次数


# ========== 评分等级 ==========
GRADES = [
    {"grade": "S", "min_score": 85, "description": "优秀，可持续性极强"},
    {"grade": "A", "min_score": 75, "description": "良好，可持续性强"},
    {"grade": "B", "min_score": 60, "description": "中等，有一定可持续性"},
    {"grade": "C", "min_score": 45, "description": "一般，可持续性较弱"},
    {"grade": "D", "min_score": 30, "description": "较差，可持续性弱"},
    {"grade": "E", "min_score": 0, "description": "很差，不可持续"},
]


# ========== 修复潜力判定 ==========
RESTORATION_POTENTIAL = {
    "min_total_score": 50,
    "exclude_status": ["完全废弃"]
}


# ========== 专家分歧度分级 ==========
DISAGREEMENT_LEVELS = [
    {"level": "highly_consistent", "max_cv": 0.05, "description": "高度一致"},
    {"level": "mostly_consistent", "max_cv": 0.10, "description": "基本一致"},
    {"level": "moderate_disagreement", "max_cv": 0.20, "description": "中等分歧"},
    {"level": "large_disagreement", "max_cv": 1.0, "description": "分歧较大"},
]


# ========== 各子项评分基准 ==========
SCORING_BASELINES = {
    "dam_height": {"min": 1, "max": 30, "excellent": 15},
    "canal_length": {"min": 5, "max": 200, "excellent": 100},
    "irrigation_area": {"min": 10, "max": 500, "excellent": 300},
    "preservation": {
        "完好": 90,
        "部分损毁": 50,
        "完全废弃": 15
    },
    "dynasty_age_weight": [
        (1, 2, 95),   # 春秋
        (3, 5, 90),   # 秦汉
        (6, 9, 85),   # 魏晋南北朝
        (10, 12, 80), # 隋唐五代
        (13, 14, 75), # 宋
        (15, 15, 70), # 元
        (16, 17, 65), # 明清
    ],
    "rainfall_stability_cv": {
        "excellent": 0.05,
        "good": 0.15,
        "moderate": 0.25
    }
}


def get_grade(score: float) -> str:
    """根据分数获取等级"""
    for g in GRADES:
        if score >= g["min_score"]:
            return g["grade"]
    return "E"


def get_ri(n: int) -> float:
    """获取随机一致性指标"""
    return RI_TABLE.get(n, 1.59)


def get_disagreement_level(cv: float) -> Dict[str, Any]:
    """获取专家分歧度等级"""
    for level in DISAGREEMENT_LEVELS:
        if cv <= level["max_cv"]:
            return level
    return DISAGREEMENT_LEVELS[-1]


def has_restoration_potential(total_score: float, preservation_status: str) -> bool:
    """判断是否具有修复潜力"""
    if preservation_status in RESTORATION_POTENTIAL["exclude_status"]:
        return False
    return total_score >= RESTORATION_POTENTIAL["min_total_score"]
