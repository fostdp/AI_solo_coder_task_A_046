/**
 * Hydro Profile - 水文与结构剖面图表模块
 * 职责：水文趋势图、结构剖面图、Canvas绘图工具
 * 依赖：无外部依赖，纯Canvas绘图
 */

class HydroChart {
    /**
     * 水文变化趋势图
     * @param {string|HTMLCanvasElement} canvas - Canvas元素或ID
     * @param {Object} options - 配置项
     */
    constructor(canvas, options = {}) {
        this.canvas = typeof canvas === 'string' ? document.getElementById(canvas) : canvas;
        if (!this.canvas) throw new Error('Canvas not found');

        this.ctx = this.canvas.getContext('2d');
        this.options = {
            padding: { top: 20, right: 60, bottom: 36, left: 50 },
            colors: {
                rainfall: '#4299e1',
                runoff: '#38b2ac',
                temperature: '#ed8936',
                grid: '#e2e8f0',
                text: '#718096'
            },
            ...options
        };
    }

    _resize() {
        const container = this.canvas.parentElement;
        if (container) {
            this.canvas.width = container.clientWidth;
            this.canvas.height = container.clientHeight;
        }
        this.W = this.canvas.width;
        this.H = this.canvas.height;
    }

    render(trendData) {
        this._resize();
        const { ctx, W, H, options } = this;
        const { padding, colors } = options;

        ctx.clearRect(0, 0, W, H);

        const chartW = W - padding.left - padding.right;
        const chartH = H - padding.top - padding.bottom;

        const trend = trendData || [];
        if (trend.length < 2) {
            ctx.font = '13px sans-serif';
            ctx.fillStyle = colors.text;
            ctx.textAlign = 'center';
            ctx.fillText('数据不足', W / 2, H / 2);
            return;
        }

        const sampleRate = Math.max(1, Math.floor(trend.length / 40));
        const sampled = trend.filter((_, i) => i % sampleRate === 0);

        const years = sampled.map(d => d.year);
        const rains = sampled.map(d => d.rainfall);
        const runoffs = sampled.map(d => d.runoff);
        const temps = sampled.map(d => d.temperature || 15);

        const yearMin = Math.min(...years);
        const yearMax = Math.max(...years);
        const rainMin = Math.min(...rains) * 0.9;
        const rainMax = Math.max(...rains) * 1.1;
        const runMin = Math.min(...runoffs) * 0.9;
        const runMax = Math.max(...runoffs) * 1.1;
        const tempMin = Math.min(...temps) - 2;
        const tempMax = Math.max(...temps) + 2;

        // 网格
        ctx.strokeStyle = colors.grid;
        ctx.lineWidth = 1;
        for (let i = 0; i <= 5; i++) {
            const y = padding.top + chartH * (i / 5);
            ctx.beginPath();
            ctx.moveTo(padding.left, y);
            ctx.lineTo(W - padding.right, y);
            ctx.stroke();

            const val = rainMax - (rainMax - rainMin) * (i / 5);
            ctx.fillStyle = colors.text;
            ctx.font = '10px sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText(val.toFixed(0), padding.left - 6, y + 3);
        }

        for (let i = 0; i <= 5; i++) {
            const x = padding.left + chartW * (i / 5);
            ctx.beginPath();
            ctx.moveTo(x, padding.top);
            ctx.lineTo(x, padding.top + chartH);
            ctx.stroke();

            const yr = yearMin + (yearMax - yearMin) * (i / 5);
            ctx.fillStyle = colors.text;
            ctx.font = '10px sans-serif';
            ctx.textAlign = 'center';
            const yrStr = yr < 0 ? `前${Math.abs(yr)}` : `${yr}`;
            ctx.fillText(yrStr, x, padding.top + chartH + 18);
        }

        // 比例尺
        const xScale = (year) => padding.left + chartW * ((year - yearMin) / (yearMax - yearMin));
        const yRain = (v) => padding.top + chartH * (1 - (v - rainMin) / (rainMax - rainMin));
        const yRun = (v) => padding.top + chartH * (1 - (v - runMin) / (runMax - runMin));
        const yTemp = (v) => padding.top + chartH * (1 - (v - tempMin) / (tempMax - tempMin));

        // 降雨线
        ctx.strokeStyle = colors.rainfall;
        ctx.lineWidth = 2;
        ctx.beginPath();
        rains.forEach((v, i) => {
            const x = xScale(years[i]);
            const y = yRain(v);
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.stroke();

        // 径流线
        ctx.strokeStyle = colors.runoff;
        ctx.lineWidth = 2;
        ctx.beginPath();
        runoffs.forEach((v, i) => {
            const x = xScale(years[i]);
            const y = yRun(v);
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.stroke();

        // 气温线（虚线）
        ctx.strokeStyle = colors.temperature;
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        temps.forEach((v, i) => {
            const x = xScale(years[i]);
            const y = yTemp(v);
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.setLineDash([]);

        // 右侧径流刻度
        for (let i = 0; i <= 3; i++) {
            const y = padding.top + chartH * (i / 3);
            const val = runMax - (runMax - runMin) * (i / 3);
            ctx.fillStyle = '#319795';
            ctx.font = '9px sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(val.toFixed(0) + ' 径流', W - padding.right + 4, y + 3);
        }

        // X轴标签
        ctx.fillStyle = '#2d3748';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('年份', W / 2, H - 4);
    }
}


class CrossSectionChart {
    /**
     * 结构剖面图
     * @param {string|HTMLCanvasElement} canvas - Canvas元素或ID
     * @param {Object} options - 配置项
     */
    constructor(canvas, options = {}) {
        this.canvas = typeof canvas === 'string' ? document.getElementById(canvas) : canvas;
        if (!this.canvas) throw new Error('Canvas not found');

        this.ctx = this.canvas.getContext('2d');
        this.options = {
            padding: { top: 20, right: 30, bottom: 40, left: 50 },
            colors: {
                ground: '#6b4226',
                groundFill: 'rgba(139, 119, 101, 0.25)',
                structure: '#2d3748',
                structureTop: '#8b5a2b',
                structureBottom: '#5c3317',
                water: '#3182ce',
                waterFill: 'rgba(66, 153, 225, 0.35)',
                grid: '#cbd5e0',
                text: '#718096'
            },
            ...options
        };
    }

    _resize() {
        const container = this.canvas.parentElement;
        if (container) {
            this.canvas.width = container.clientWidth;
            this.canvas.height = container.clientHeight;
        }
        this.W = this.canvas.width;
        this.H = this.canvas.height;
    }

    render(sectionData) {
        this._resize();
        const { ctx, W, H, options } = this;
        const { padding, colors } = options;

        ctx.clearRect(0, 0, W, H);

        const chartW = W - padding.left - padding.right;
        const chartH = H - padding.top - padding.bottom;

        const cs = sectionData || {};
        const xAxis = cs.x_axis || cs.x_normalized || [];
        const nPts = xAxis.length || (cs.ground_profile || []).length;

        if (nPts < 2) {
            ctx.font = '13px sans-serif';
            ctx.fillStyle = colors.text;
            ctx.textAlign = 'center';
            ctx.fillText('剖面数据不足', W / 2, H / 2);
            return;
        }

        const ground = cs.ground_profile || [];
        const structure = cs.structure_profile || [];
        const water = cs.water_profile || [];

        const allY = [
            ...ground,
            ...structure.map(v => v ?? 0),
            ...water.map(v => v ?? 0)
        ].filter(v => !isNaN(v));

        const yMin = Math.min(...allY) * 1.1;
        const yMax = Math.max(...allY) * 1.1 + 0.5;

        // 网格
        ctx.strokeStyle = colors.grid;
        ctx.lineWidth = 0.5;
        for (let i = 0; i <= 6; i++) {
            const y = padding.top + chartH * (i / 6);
            ctx.beginPath();
            ctx.moveTo(padding.left, y);
            ctx.lineTo(W - padding.right, y);
            ctx.stroke();

            const val = yMax - (yMax - yMin) * (i / 6);
            ctx.fillStyle = colors.text;
            ctx.font = '10px sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText(val.toFixed(1) + 'm', padding.left - 5, y + 3);
        }

        for (let i = 0; i <= 5; i++) {
            const x = padding.left + chartW * (i / 5);
            ctx.beginPath();
            ctx.moveTo(x, padding.top);
            ctx.lineTo(x, padding.top + chartH);
            ctx.stroke();
        }

        // 坐标映射
        const xScale = (i) => padding.left + chartW * (i / (nPts - 1));
        const yScale = (v) => {
            if (v === null || v === undefined || isNaN(v)) return null;
            return padding.top + chartH * (1 - (v - yMin) / (yMax - yMin));
        };

        // 水体层
        const waterPoints = water.map((v, i) => ({ x: xScale(i), y: yScale(v) })).filter(p => p.y !== null);
        if (waterPoints.length >= 2) {
            const groundPts = ground.map((v, i) => ({ x: xScale(i), y: yScale(v) }));

            ctx.fillStyle = colors.waterFill;
            ctx.beginPath();

            let started = false;
            waterPoints.forEach((wp, idx) => {
                const gp = groundPts.find(g => Math.abs(g.x - wp.x) < 2);
                if (gp) {
                    if (!started) {
                        ctx.moveTo(wp.x, Math.min(wp.y, gp.y));
                        started = true;
                    } else {
                        ctx.lineTo(wp.x, Math.min(wp.y, gp.y));
                    }
                }
            });

            for (let i = waterPoints.length - 1; i >= 0; i--) {
                const wp = waterPoints[i];
                const gp = groundPts.find(g => Math.abs(g.x - wp.x) < 2);
                if (gp) ctx.lineTo(wp.x, gp.y);
            }

            ctx.closePath();
            ctx.fill();

            // 水面线
            ctx.strokeStyle = colors.water;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            waterPoints.forEach((p, i) => {
                i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y);
            });
            ctx.stroke();
        }

        // 结构层
        const structPts = structure.map((v, i) => ({ x: xScale(i), y: yScale(v) }));
        const validStruct = structPts.filter(p => p.y !== null);

        if (validStruct.length >= 2) {
            const structGrad = ctx.createLinearGradient(0, padding.top, 0, padding.top + chartH);
            structGrad.addColorStop(0, colors.structureTop);
            structGrad.addColorStop(1, colors.structureBottom);
            ctx.fillStyle = structGrad;

            let firstIdx = structPts.findIndex(p => p.y !== null);
            let lastIdx = -1;
            for (let i = structPts.length - 1; i >= 0; i--) {
                if (structPts[i].y !== null) { lastIdx = i; break; }
            }

            if (firstIdx >= 0 && lastIdx >= 0) {
                const groundLeftY = yScale(ground[firstIdx] ?? yMin);
                ctx.beginPath();
                ctx.moveTo(structPts[firstIdx].x, Math.max(structPts[firstIdx].y, groundLeftY));

                for (let i = firstIdx; i <= lastIdx; i++) {
                    if (structPts[i].y !== null) ctx.lineTo(structPts[i].x, structPts[i].y);
                }

                const groundRightY = yScale(ground[lastIdx] ?? yMin);
                ctx.lineTo(structPts[lastIdx].x, Math.max(structPts[lastIdx].y, groundRightY));

                for (let i = lastIdx; i >= firstIdx; i--) {
                    const gy = yScale(ground[i] ?? yMin);
                    ctx.lineTo(structPts[i].x, Math.max(gy, structPts[i].y ?? groundLeftY));
                }
                ctx.closePath();
                ctx.fill();
            }

            // 结构线
            ctx.strokeStyle = colors.structure;
            ctx.lineWidth = 2;
            ctx.beginPath();
            let started = false;
            validStruct.forEach((p) => {
                if (p.y !== null) {
                    if (!started) { ctx.moveTo(p.x, p.y); started = true; }
                    else ctx.lineTo(p.x, p.y);
                }
            });
            ctx.stroke();
        }

        // 地面层
        const groundPts = ground.map((v, i) => ({ x: xScale(i), y: yScale(v) }));
        if (groundPts.length >= 2) {
            ctx.fillStyle = colors.groundFill;
            ctx.beginPath();
            ctx.moveTo(groundPts[0].x, H - padding.bottom);
            groundPts.forEach(p => ctx.lineTo(p.x, p.y));
            ctx.lineTo(groundPts[groundPts.length - 1].x, H - padding.bottom);
            ctx.closePath();
            ctx.fill();

            ctx.strokeStyle = colors.ground;
            ctx.lineWidth = 2.5;
            ctx.beginPath();
            groundPts.forEach((p, i) => {
                i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y);
            });
            ctx.stroke();
        }

        // 坐标轴标签
        ctx.fillStyle = '#2d3748';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('横剖面 (m) →', W / 2, H - 8);

        ctx.save();
        ctx.translate(12, H / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText('高程 (m)', 0, 0);
        ctx.restore();

        // 图例
        const legendY = 6;
        const legends = [
            { color: colors.structureTop, label: '水工结构' },
            { color: colors.waterFill, label: '水体', border: true, borderColor: colors.water },
            { color: colors.ground, label: '地面' }
        ];

        let lx = padding.left;
        ctx.font = '10px sans-serif';
        legends.forEach(l => {
            ctx.fillStyle = l.color;
            ctx.fillRect(lx, legendY, 12, 10);
            if (l.border) {
                ctx.strokeStyle = l.borderColor || '#333';
                ctx.lineWidth = 1;
                ctx.strokeRect(lx, legendY, 12, 10);
            }
            ctx.fillStyle = '#2d3748';
            ctx.textAlign = 'left';
            ctx.fillText(l.label, lx + 16, legendY + 9);
            lx += ctx.measureText(l.label).width + 40;
        });
    }
}


/**
 * 便捷函数 - 直接在指定Canvas上绘制水文图
 */
function drawHydroChart(canvasId, hydroData) {
    try {
        const chart = new HydroChart(canvasId);
        chart.render(hydroData.trend || hydroData);
    } catch (e) {
        console.warn('绘制水文图失败:', e);
    }
}


/**
 * 便捷函数 - 直接在指定Canvas上绘制剖面图
 */
function drawCrossSection(canvasId, sectionData) {
    try {
        const chart = new CrossSectionChart(canvasId);
        chart.render(sectionData.cross_section || sectionData);
    } catch (e) {
        console.warn('绘制剖面图失败:', e);
    }
}
