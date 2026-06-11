-- ============================================================
-- 古代水利工程遗迹功能复原与可持续性评估系统
-- 数据库初始化脚本 (PostgreSQL + PostGIS)
-- ============================================================

-- 创建扩展
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- ============================================================
-- 1. 水利工程遗迹表
-- ============================================================
CREATE TABLE IF NOT EXISTS water_heritage_sites (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    dynasty VARCHAR(100) NOT NULL,
    dynasty_order INTEGER NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    geom GEOMETRY(Point, 4326),
    site_type VARCHAR(20) NOT NULL CHECK (site_type IN ('渠', '堰', '陂', '塘', '井')),
    dam_height DOUBLE PRECISION,
    canal_length DOUBLE PRECISION,
    irrigation_area DOUBLE PRECISION NOT NULL,
    preservation_status VARCHAR(20) NOT NULL CHECK (preservation_status IN ('完好', '部分损毁', '完全废弃')),
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sites_geom ON water_heritage_sites USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_sites_dynasty ON water_heritage_sites (dynasty_order);
CREATE INDEX IF NOT EXISTS idx_sites_type ON water_heritage_sites (site_type);
CREATE INDEX IF NOT EXISTS idx_sites_status ON water_heritage_sites (preservation_status);

-- ============================================================
-- 2. 古代水文重建数据表
-- ============================================================
CREATE TABLE IF NOT EXISTS paleo_hydrology_data (
    id SERIAL PRIMARY KEY,
    year INTEGER NOT NULL,
    region VARCHAR(100) NOT NULL,
    rainfall DOUBLE PRECISION NOT NULL,
    runoff DOUBLE PRECISION NOT NULL,
    temperature DOUBLE PRECISION,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_hydro_year ON paleo_hydrology_data (year);
CREATE INDEX IF NOT EXISTS idx_hydro_region ON paleo_hydrology_data (region);

-- ============================================================
-- 3. 功能复原结果表
-- ============================================================
CREATE TABLE IF NOT EXISTS functional_restoration (
    id SERIAL PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES water_heritage_sites(id) ON DELETE CASCADE,
    original_irrigation_capacity DOUBLE PRECISION NOT NULL,
    actual_irrigation_capacity DOUBLE PRECISION NOT NULL,
    water_supply_range_geom GEOMETRY(Polygon, 4326),
    supply_population INTEGER,
    restoration_notes TEXT,
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(site_id)
);

CREATE INDEX IF NOT EXISTS idx_restoration_site ON functional_restoration (site_id);
CREATE INDEX IF NOT EXISTS idx_restoration_geom ON functional_restoration USING GIST (water_supply_range_geom);

-- ============================================================
-- 4. 可持续性评估结果表
-- ============================================================
CREATE TABLE IF NOT EXISTS sustainability_assessment (
    id SERIAL PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES water_heritage_sites(id) ON DELETE CASCADE,
    structural_score DOUBLE PRECISION NOT NULL,
    hydrological_score DOUBLE PRECISION NOT NULL,
    economic_score DOUBLE PRECISION NOT NULL,
    cultural_score DOUBLE PRECISION NOT NULL,
    environmental_score DOUBLE PRECISION NOT NULL,
    total_score DOUBLE PRECISION NOT NULL,
    grade VARCHAR(2) NOT NULL,
    restoration_potential BOOLEAN NOT NULL,
    assessment_details JSONB,
    assessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(site_id)
);

CREATE INDEX IF NOT EXISTS idx_assessment_site ON sustainability_assessment (site_id);
CREATE INDEX IF NOT EXISTS idx_assessment_score ON sustainability_assessment (total_score);

-- ============================================================
-- 5. 告警记录表
-- ============================================================
CREATE TABLE IF NOT EXISTS alert_records (
    id SERIAL PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES water_heritage_sites(id) ON DELETE CASCADE,
    alert_type VARCHAR(50) NOT NULL,
    alert_level VARCHAR(20) NOT NULL CHECK (alert_level IN ('低', '中', '高', '紧急')),
    message TEXT NOT NULL,
    mqtt_topic VARCHAR(200),
    acknowledged BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alert_site ON alert_records (site_id);
CREATE INDEX IF NOT EXISTS idx_alert_level ON alert_records (alert_level);
CREATE INDEX IF NOT EXISTS idx_alert_time ON alert_records (created_at);

-- ============================================================
-- 6. 朝代字典表
-- ============================================================
CREATE TABLE IF NOT EXISTS dynasty_dict (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    start_year INTEGER NOT NULL,
    end_year INTEGER NOT NULL,
    "order" INTEGER NOT NULL UNIQUE
);

INSERT INTO dynasty_dict (name, start_year, end_year, "order") VALUES
('春秋', -770, -476, 1),
('战国', -475, -221, 2),
('秦', -221, -206, 3),
('西汉', -202, 8, 4),
('东汉', 25, 220, 5),
('三国', 220, 280, 6),
('西晋', 265, 316, 7),
('东晋', 317, 420, 8),
('南北朝', 420, 589, 9),
('隋', 581, 618, 10),
('唐', 618, 907, 11),
('五代', 907, 960, 12),
('北宋', 960, 1127, 13),
('南宋', 1127, 1279, 14),
('元', 1271, 1368, 15),
('明', 1368, 1644, 16),
('清', 1644, 1912, 17)
ON CONFLICT ("order") DO NOTHING;

-- ============================================================
-- 7. 触发器：自动更新时间戳
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sites_updated_at ON water_heritage_sites;
CREATE TRIGGER trg_sites_updated_at
BEFORE UPDATE ON water_heritage_sites
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- 8. 触发器：保存状态变为完全废弃时告警
-- ============================================================
CREATE OR REPLACE FUNCTION check_preservation_alert()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.preservation_status = '完全废弃' AND 
       (OLD.preservation_status IS NULL OR OLD.preservation_status != '完全废弃') THEN
        INSERT INTO alert_records (site_id, alert_type, alert_level, message, mqtt_topic)
        VALUES (
            NEW.id,
            '文物保护预警',
            '紧急',
            '水利遗迹【' || NEW.name || '】保存状态已恶化为完全废弃，请立即采取保护措施！',
            'heritage/alert/' || NEW.id
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_preservation_alert ON water_heritage_sites;
CREATE TRIGGER trg_preservation_alert
AFTER INSERT OR UPDATE ON water_heritage_sites
FOR EACH ROW EXECUTE FUNCTION check_preservation_alert();

-- ============================================================
-- 9. 视图：遗迹综合信息视图
-- ============================================================
CREATE OR REPLACE VIEW v_site_comprehensive AS
SELECT 
    s.*,
    ST_X(s.geom) AS lng,
    ST_Y(s.geom) AS lat,
    r.original_irrigation_capacity,
    r.actual_irrigation_capacity,
    r.water_supply_range_geom,
    a.total_score,
    a.grade,
    a.restoration_potential,
    d.name as dynasty_name,
    d.start_year as dynasty_start,
    d.end_year as dynasty_end
FROM water_heritage_sites s
LEFT JOIN functional_restoration r ON s.id = r.site_id
LEFT JOIN sustainability_assessment a ON s.id = a.site_id
LEFT JOIN dynasty_dict d ON s.dynasty_order = d."order";
