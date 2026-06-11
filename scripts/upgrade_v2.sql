-- ============================================================
-- 古代水利工程遗迹功能复原与可持续性评估系统 v2.0
-- 数据库升级脚本 (PostgreSQL + PostGIS)
-- 从 v1.0 升级到 v2.0
-- ============================================================

-- ============================================================
-- 1. 功能复原表 - 新增参数估计和不确定性分析字段
-- ============================================================
ALTER TABLE functional_restoration
ADD COLUMN IF NOT EXISTS parameter_estimation JSONB;

ALTER TABLE functional_restoration
ADD COLUMN IF NOT EXISTS uncertainty_analysis JSONB;

COMMENT ON COLUMN functional_restoration.parameter_estimation IS '参数估计结果（当结构参数缺失时的估计值）';
COMMENT ON COLUMN functional_restoration.uncertainty_analysis IS '蒙特卡洛不确定性分析结果';

-- ============================================================
-- 2. 可持续性评估表 - 新增群决策信息字段
-- ============================================================
ALTER TABLE sustainability_assessment
ADD COLUMN IF NOT EXISTS group_decision_info JSONB;

COMMENT ON COLUMN sustainability_assessment.group_decision_info IS 'AHP群决策信息（专家权重、一致性检验、分歧度等）';

-- ============================================================
-- 3. 告警记录表 - 新增MQTT消息追踪字段
-- ============================================================
ALTER TABLE alert_records
ADD COLUMN IF NOT EXISTS mqtt_message_id VARCHAR(100);

ALTER TABLE alert_records
ADD COLUMN IF NOT EXISTS mqtt_status VARCHAR(20);

COMMENT ON COLUMN alert_records.mqtt_message_id IS 'MQTT消息ID（用于追踪消息状态）';
COMMENT ON COLUMN alert_records.mqtt_status IS 'MQTT消息状态（pending/publishing/published/failed）';

-- ============================================================
-- 4. 更新视图 - 包含新字段
-- ============================================================
CREATE OR REPLACE VIEW v_site_comprehensive AS
SELECT 
    s.*,
    ST_X(s.geom) AS lng,
    ST_Y(s.geom) AS lat,
    r.original_irrigation_capacity,
    r.actual_irrigation_capacity,
    r.water_supply_range_geom,
    r.parameter_estimation,
    r.uncertainty_analysis,
    a.total_score,
    a.grade,
    a.restoration_potential,
    a.group_decision_info,
    d.name as dynasty_name,
    d.start_year as dynasty_start,
    d.end_year as dynasty_end
FROM water_heritage_sites s
LEFT JOIN functional_restoration r ON s.id = r.site_id
LEFT JOIN sustainability_assessment a ON s.id = a.site_id
LEFT JOIN dynasty_dict d ON s.dynasty_order = d."order";

-- ============================================================
-- 升级完成
-- ============================================================
DO $$
BEGIN
    RAISE NOTICE '数据库升级到 v2.0 完成';
    RAISE NOTICE '新增功能:';
    RAISE NOTICE '  1. 参数估计 (parameter_estimation)';
    RAISE NOTICE '  2. 蒙特卡洛不确定性分析 (uncertainty_analysis)';
    RAISE NOTICE '  3. AHP群决策信息 (group_decision_info)';
    RAISE NOTICE '  4. MQTT消息追踪 (mqtt_message_id, mqtt_status)';
END $$;
