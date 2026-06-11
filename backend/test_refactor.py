"""
重构回归测试脚本
验证所有模块导入正常
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print('=' * 60)
print('重构回归测试 - 模块导入验证')
print('=' * 60)

# 共享模块
print('\n📦 共享模块:')
shared_modules = [
    ('common.config', 'settings, channels'),
    ('common.database', 'Base, engine, get_db'),
    ('common.models', 'WaterHeritageSite, FunctionalRestoration'),
    ('common.schemas', 'WaterHeritageSiteResponse'),
    ('common.params.hydraulic_params', 'GRAVITY, REGIONS, TYPE_PARAM_DISTRIBUTIONS'),
    ('common.params.ahp_params', 'CRITERIA, EXPERTS, get_grade'),
]

all_ok = True
for module_name, items in shared_modules:
    try:
        mod = __import__(module_name, fromlist=items.split(', '))
        print(f'  ✓ {module_name}')
    except Exception as e:
        print(f'  ✗ {module_name}: {e}')
        all_ok = False
        import traceback
        traceback.print_exc()

# 业务模块
print('\n📦 业务模块:')
business_modules = [
    ('services.hydro_reconstructor.restoration_model', 'restore_site, ParameterEstimator'),
    ('services.sustainability_evaluator.ahp_assessment', 'AHPSustainabilityAssessment, AHPGroupDecision'),
]

for module_name, items in business_modules:
    try:
        mod = __import__(module_name, fromlist=items.split(', '))
        print(f'  ✓ {module_name}')
    except Exception as e:
        print(f'  ✗ {module_name}: {e}')
        all_ok = False
        import traceback
        traceback.print_exc()

# 功能测试
print('\n🧪 功能测试:')

# 测试1: 水力计算
print('\n  1. 水力计算核心公式:')
try:
    from services.hydro_reconstructor.restoration_model import (
        calculate_weir_flow, calculate_canal_capacity,
        calculate_reservoir_capacity, calculate_well_yield
    )
    q_weir = calculate_weir_flow(0.58, 50, 3.0)
    print(f'     宽顶堰流 (Cd=0.58, L=50m, h=3m): {q_weir:.2f} m³/s')

    q_canal = calculate_canal_capacity(5.0, 2.0, 0.001, 0.03)
    print(f'     明渠输水 (宽5m, 深2m, 坡0.001, n=0.03): {q_canal:.2f} m³/s')

    v_res = calculate_reservoir_capacity(15, 800)
    print(f'     锥形库容 (高15m, 面积800㎡): {v_res:.0f} m³')

    q_well = calculate_well_yield(2.5, 20, 8, 0.15)
    print(f'     井出水量 (k=2.5, H=20m, hw=8m, rw=0.15m): {q_well:.2f} m³/d')
    print('     ✓ 通过')
except Exception as e:
    print(f'     ✗ 失败: {e}')
    all_ok = False
    import traceback
    traceback.print_exc()

# 测试2: 参数估计
print('\n  2. 参数估计器:')
try:
    from services.hydro_reconstructor.restoration_model import ParameterEstimator
    estimator = ParameterEstimator()
    params, rel = estimator.estimate_parameters('堰', 16, irrigation_area=200)
    print(f'     类型: 堰, 朝代: 明 (order=16)')
    print(f'     坝高: {params["dam_height"]:.2f}m')
    print(f'     技术因子: {params["tech_factor"]:.2f}')
    print(f'     估计可靠度: {rel:.1f}%')
    print('     ✓ 通过')
except Exception as e:
    print(f'     ✗ 失败: {e}')
    all_ok = False
    import traceback
    traceback.print_exc()

# 测试3: 蒙特卡洛
print('\n  3. 蒙特卡洛分析:')
try:
    from services.hydro_reconstructor.restoration_model import monte_carlo_analysis
    from services.hydro_reconstructor.restoration_model import ParameterEstimator

    est = ParameterEstimator()
    p, _ = est.estimate_parameters('渠', 11, irrigation_area=150)
    result = monte_carlo_analysis('渠', p, 800, 300, n_samples=200, seed=42)
    print(f'     抽样次数: {result["n_samples"]}')
    print(f'     均值: {result["mean"]:.1f} 亩')
    print(f'     变异系数CV: {result["cv"]:.4f}')
    print(f'     收敛: {result["convergence"]["converged"]}')
    print(f'     SRC参数数: {len(result["src_analysis"])}')
    print('     ✓ 通过')
except Exception as e:
    print(f'     ✗ 失败: {e}')
    all_ok = False
    import traceback
    traceback.print_exc()

# 测试4: AHP群决策
print('\n  4. AHP群决策:')
try:
    from services.sustainability_evaluator.ahp_assessment import AHPGroupDecision

    ahp = AHPGroupDecision(['structural', 'hydrological', 'economic', 'cultural', 'environmental'])
    weights, info = ahp.aggregate_experts_geometric()
    print(f'     专家数: {info["expert_count"]}')
    print(f'     分歧度: {info["disagreement_description"]}')
    print(f'     结构权重: {weights["structural"]:.3f}')
    print(f'     水文权重: {weights["hydrological"]:.3f}')
    print('     ✓ 通过')
except Exception as e:
    print(f'     ✗ 失败: {e}')
    all_ok = False
    import traceback
    traceback.print_exc()

# 测试5: AHP一致性检验
print('\n  5. AHP一致性检验:')
try:
    from services.sustainability_evaluator.ahp_assessment import AHPGroupDecision
    from common.params.ahp_params import CRITERIA

    ahp = AHPGroupDecision()
    test_weights = {k: v["weight"] for k, v in CRITERIA.items()}
    matrix = ahp.build_pairwise_matrix(test_weights)
    cons = ahp.check_consistency(matrix)
    print(f'     CR值: {cons["CR"]:.4f}')
    print(f'     一致性: {"通过" if cons["consistent"] else "不通过"}')
    print('     ✓ 通过')
except Exception as e:
    print(f'     ✗ 失败: {e}')
    all_ok = False
    import traceback
    traceback.print_exc()

# 测试6: 供水多边形
print('\n  6. 供水多边形生成:')
try:
    from services.hydro_reconstructor.restoration_model import generate_supply_polygon

    poly = generate_supply_polygon(114.0, 34.0, 200, '渠', simplified=False)
    simple_poly = generate_supply_polygon(114.0, 34.0, 200, '渠', simplified=True)
    print(f'     详细模式顶点数: {len(list(poly.exterior.coords))}')
    print(f'     简化模式顶点数: {len(list(simple_poly.exterior.coords))}')
    print(f'     面积: {poly.area:.6f} 度²')
    print('     ✓ 通过')
except Exception as e:
    print(f'     ✗ 失败: {e}')
    all_ok = False
    import traceback
    traceback.print_exc()

print()
print('=' * 60)
if all_ok:
    print('✅ 所有测试通过！重构验证成功。')
else:
    print('❌ 部分测试失败，请检查错误信息。')
print('=' * 60)
