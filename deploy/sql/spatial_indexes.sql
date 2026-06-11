-- ============================================================
-- 古代水利工程遗迹系统 - 空间索引优化
-- PostgreSQL + PostGIS 高性能查询索引配置
-- ============================================================

-- 确保PostGIS扩展已启用
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

SET statement_timeout = '60s';
SET maintenance_work_mem = '128MB';
SET work_mem = '8MB';

-- ============================================================
-- 1. water_heritage_sites - 空间索引 + 复合索引
-- ============================================================

-- GiST空间索引 (地理范围查询、邻近查询核心)
CREATE INDEX IF NOT EXISTS idx_water_heritage_sites_geom
    ON water_heritage_sites USING GIST (geom);

-- BRIN索引 (按地理位置顺序存储的大表，替代BTREE)
-- 适用于时间序列或有序大表，占用空间仅为GiST的1%
CREATE INDEX IF NOT EXISTS idx_water_heritage_sites_geom_brin
    ON water_heritage_sites USING BRIN (longitude, latitude)
    WITH (pages_per_range = 128);

-- 朝代过滤索引
CREATE INDEX IF NOT EXISTS idx_water_heritage_sites_dynasty
    ON water_heritage_sites (dynasty_order);

-- 工程类型索引
CREATE INDEX IF NOT EXISTS idx_water_heritage_sites_type
    ON water_heritage_sites (site_type);

-- 保存状态索引
CREATE INDEX IF NOT EXISTS idx_water_heritage_sites_status
    ON water_heritage_sites (preservation_status);

-- 复合索引: 朝代+类型 (常见筛选组合)
CREATE INDEX IF NOT EXISTS idx_water_heritage_sites_dynasty_type
    ON water_heritage_sites (dynasty_order, site_type);

-- 灌溉面积范围查询
CREATE INDEX IF NOT EXISTS idx_water_heritage_sites_irrig_area
    ON water_heritage_sites (irrigation_area);

-- ============================================================
-- 2. paleo_hydrology_data - 时间序列索引
-- ============================================================

-- 年份+区域复合索引 (水文数据核心查询)
CREATE INDEX IF NOT EXISTS idx_paleo_hydrology_year_region
    ON paleo_hydrology_data (year, region);

-- 区域索引
CREATE INDEX IF NOT EXISTS idx_paleo_hydrology_region
    ON paleo_hydrology_data (region);

-- BRIN时间索引 (大表优化)
CREATE INDEX IF NOT EXISTS idx_paleo_hydrology_year_brin
    ON paleo_hydrology_data USING BRIN (year)
    WITH (pages_per_range = 256);

-- ============================================================
-- 3. functional_restorations - 复原结果索引
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_functional_restorations_site_id
    ON functional_restorations (site_id);

CREATE INDEX IF NOT EXISTS idx_functional_restorations_irrig_area
    ON functional_restorations (estimated_irrigation_area);

CREATE INDEX IF NOT EXISTS idx_functional_restorations_confidence
    ON functional_restorations (estimation_confidence);

-- ============================================================
-- 4. sustainability_assessments - 评估结果索引
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_sustainability_assessments_site_id
    ON sustainability_assessments (site_id);

CREATE INDEX IF NOT EXISTS idx_sustainability_assessments_grade
    ON sustainability_assessments (comprehensive_grade);

CREATE INDEX IF NOT EXISTS idx_sustainability_assessments_total_score
    ON sustainability_assessments (total_score DESC);

-- 潜力筛选索引
CREATE INDEX IF NOT EXISTS idx_sustainability_assessments_potential
    ON sustainability_assessments (restoration_potential, comprehensive_grade);

-- ============================================================
-- 5. alert_records - 告警记录索引
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_alert_records_site_id
    ON alert_records (site_id);

CREATE INDEX IF NOT EXISTS idx_alert_records_level
    ON alert_records (alert_level);

CREATE INDEX IF NOT EXISTS idx_alert_records_confirmed
    ON alert_records (is_confirmed);

CREATE INDEX IF NOT EXISTS idx_alert_records_created
    ON alert_records (created_at DESC);

-- ============================================================
-- 6. dynasty_dict - 主键已足够，无需额外索引
-- ============================================================

-- ============================================================
-- 7. 统计信息收集 (执行ANALYZE更新查询计划)
-- ============================================================

ANALYZE water_heritage_sites;
ANALYZE paleo_hydrology_data;
ANALYZE functional_restorations;
ANALYZE sustainability_assessments;
ANALYZE alert_records;
ANALYZE dynasty_dict;

-- ============================================================
-- 8. 空间参照系验证 (WGS84 EPSG:4326)
-- ============================================================

-- 验证空间参考系统
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM spatial_ref_sys WHERE srid = 4326
    ) THEN
        RAISE NOTICE 'WGS84 (EPSG:4326) 未在 spatial_ref_sys 中，PostGIS标准安装应已包含';
    END IF;
END $$;
