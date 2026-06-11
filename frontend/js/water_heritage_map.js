/**
 * Water Heritage Map - 水利遗迹地图模块
 * 职责：Leaflet地图初始化、六边形标记渲染、灌溉区渲染、筛选、搜索
 * 依赖：Leaflet.js、supply-range-renderer.js
 */

const STATUS_COLORS = {
    '完好': '#38a169',
    '部分损毁': '#d69e2e',
    '完全废弃': '#e53e3e'
};

const TYPE_NAMES = {
    '渠': '渠道',
    '堰': '堰坝',
    '陂': '陂塘',
    '塘': '水塘',
    '井': '水井'
};

class WaterHeritageMap {
    constructor(mapContainerId, options = {}) {
        this.mapContainerId = mapContainerId;
        this.map = null;
        this.sitesLayer = null;
        this.supplyRangesLayer = null;
        this.canvasLayer = null;
        this.supplyRangeRenderer = null;

        this.sites = [];
        this.filteredSites = [];
        this.supplyRanges = [];
        this.selectedSiteId = null;

        this.showSupplyRange = options.showSupplyRange ?? true;
        this.showHexagon = options.showHexagon ?? true;
        this.sizeByArea = options.sizeByArea ?? true;
        this.colorByStatus = options.colorByStatus ?? true;
        this.useHighPerformanceRenderer = options.useHighPerformanceRenderer ?? true;

        this.onSiteSelect = options.onSiteSelect || (() => {});

        this._init();
    }

    _init() {
        this.map = L.map(this.mapContainerId, {
            center: [34.0, 110.0],
            zoom: 5,
            minZoom: 4,
            maxZoom: 14
        });

        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 19
        }).addTo(this.map);

        const southWest = L.latLng(18, 73);
        const northEast = L.latLng(53, 135);
        this.map.setMaxBounds(L.latLngBounds(southWest, northEast));

        this.sitesLayer = L.layerGroup().addTo(this.map);
        this.supplyRangesLayer = L.layerGroup().addTo(this.map);

        if (this.useHighPerformanceRenderer && typeof SupplyRangeRenderer !== 'undefined') {
            this.supplyRangeRenderer = new SupplyRangeRenderer(this.map, {
                onClick: (range) => {
                    if (range.siteId) this.selectSite(range.siteId);
                }
            });
        }
    }

    // ========== 工具方法 ==========
    hexToRadius(irrigationArea) {
        if (!this.sizeByArea) return 14;
        if (irrigationArea < 10) return 10;
        if (irrigationArea < 100) return 14;
        if (irrigationArea < 1000) return 20;
        return 28;
    }

    getStatusColor(status, site) {
        if (!this.colorByStatus) {
            const dynColors = ['#2b6cb0', '#2c5282', '#1a365d', '#3182ce', '#4299e1'];
            return dynColors[((site.dynasty_order || 1) - 1) % dynColors.length];
        }
        return STATUS_COLORS[status] || '#718096';
    }

    createHexSVG(radius, color) {
        const size = radius * 2 + 8;
        const cx = size / 2;
        const cy = size / 2;
        const points = [];
        for (let i = 0; i < 6; i++) {
            const angle = (Math.PI / 3) * i - Math.PI / 2;
            const px = cx + radius * Math.cos(angle);
            const py = cy + radius * Math.sin(angle);
            points.push(`${px},${py}`);
        }
        return `
            <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" style="overflow:visible;pointer-events:none;">
                <polygon points="${points.join(' ')}" 
                         fill="${color}" 
                         fill-opacity="0.92"
                         stroke="white" 
                         stroke-width="2.5"
                         style="filter: drop-shadow(0 2px 6px rgba(0,0,0,0.25));"/>
            </svg>
        `;
    }

    createPopupContent(site) {
        const score = site.total_score ? `<div class="popup-row"><span class="popup-label">评分：</span><span class="popup-value">${site.total_score?.toFixed(1)} (${site.grade})</span></div>` : '';
        const pot = site.restoration_potential !== undefined ? `<div class="popup-row"><span class="popup-label">修复潜力：</span><span class="popup-value">${site.restoration_potential ? '✅ 有' : '❌ 无'}</span></div>` : '';

        const div = document.createElement('div');
        div.textContent = site.name || '';
        const escapedName = div.innerHTML;

        return `
            <div style="padding:4px;">
                <div class="popup-title">${escapedName}</div>
                <div class="popup-row"><span class="popup-label">朝代：</span><span class="popup-value">${site.dynasty}</span></div>
                <div class="popup-row"><span class="popup-label">类型：</span><span class="popup-value">${TYPE_NAMES[site.site_type] || site.site_type}</span></div>
                <div class="popup-row"><span class="popup-label">灌溉面积：</span><span class="popup-value">${site.irrigation_area.toFixed(1)} 亩</span></div>
                <div class="popup-row"><span class="popup-label">保存状态：</span><span class="popup-value" style="color:${STATUS_COLORS[site.preservation_status]}">${site.preservation_status}</span></div>
                ${score}
                ${pot}
                <button class="popup-btn" onclick="app.map.selectSite(${site.id});window.L._popupHandlersAdded=true;">查看详情</button>
            </div>
        `;
    }

    // ========== 渲染 ==========
    renderSites() {
        this.sitesLayer.clearLayers();
        this.supplyRangesLayer.clearLayers();

        const sitesToRender = this.filteredSites.length > 0 ? this.filteredSites : this.sites;

        if (this.showHexagon) {
            const hexLayer = L.layerGroup();
            sitesToRender.forEach(site => {
                const latlng = [site.latitude, site.longitude];
                const radius = this.hexToRadius(site.irrigation_area);
                const color = this.getStatusColor(site.preservation_status, site);

                const icon = L.divIcon({
                    className: 'hex-marker',
                    html: this.createHexSVG(radius, color),
                    iconSize: [radius * 2 + 4, radius * 2 + 4],
                    iconAnchor: [radius + 2, radius + 2]
                });

                const marker = L.marker(latlng, { icon: icon, site: site });
                marker.bindPopup(this.createPopupContent(site));
                marker.on('click', () => this.selectSite(site.id));
                marker.addTo(hexLayer);
            });
            hexLayer.addTo(this.sitesLayer);
        } else {
            sitesToRender.forEach(site => {
                const latlng = [site.latitude, site.longitude];
                const color = this.getStatusColor(site.preservation_status, site);
                const marker = L.circleMarker(latlng, {
                    radius: this.hexToRadius(site.irrigation_area) * 0.6,
                    fillColor: color,
                    color: 'white',
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 0.9
                });
                marker.bindPopup(this.createPopupContent(site));
                marker.on('click', () => this.selectSite(site.id));
                marker.addTo(this.sitesLayer);
            });
        }

        if (this.showSupplyRange && this.supplyRanges.length > 0) {
            this._renderSupplyRanges();
        }
    }

    _renderSupplyRanges() {
        if (this.supplyRangeRenderer) {
            this.supplyRangeRenderer.setRanges(this.supplyRanges);
            if (!this.showSupplyRange) {
                this.supplyRangeRenderer.hide();
            } else {
                this.supplyRangeRenderer.show();
            }
        } else {
            this.supplyRanges.forEach(f => {
                const layer = L.geoJSON(f, {
                    style: {
                        color: '#4299e1',
                        weight: 1.5,
                        fillColor: '#4299e1',
                        fillOpacity: 0.2,
                        dashArray: '4, 4'
                    }
                });
                const props = f.properties || {};
                layer.bindPopup(`
                    <strong>灌溉区范围</strong><br/>
                    实际灌溉能力: ${props.actual_capacity?.toFixed(2) || props.actual_irrigation_capacity?.toFixed(2) || 0} 亩<br/>
                    可服务人口: 约 ${props.supply_population || 0} 人
                `);
                layer.addTo(this.supplyRangesLayer);
            });
        }
    }

    // ========== 数据加载 ==========
    setSites(sites) {
        this.sites = sites;
        this.renderSites();
    }

    setSupplyRanges(ranges) {
        this.supplyRanges = ranges;
        if (this.showSupplyRange) {
            this._renderSupplyRanges();
        }
    }

    setSelected(siteId) {
        this.selectedSiteId = siteId;
        if (this.supplyRangeRenderer) {
            this.supplyRangeRenderer.setSelected(siteId);
        }
    }

    // ========== 筛选 ==========
    applyFilters(filters) {
        const { type, dynasty, status, minArea, maxArea } = filters;

        this.filteredSites = this.sites.filter(s => {
            if (type && s.site_type !== type) return false;
            if (dynasty && s.dynasty !== dynasty) return false;
            if (status && s.preservation_status !== status) return false;
            if (minArea !== undefined && !isNaN(minArea) && s.irrigation_area < minArea) return false;
            if (maxArea !== undefined && !isNaN(maxArea) && s.irrigation_area > maxArea) return false;
            return true;
        });

        this.renderSites();
        return this.filteredSites.length;
    }

    resetFilters() {
        this.filteredSites = [];
        this.renderSites();
    }

    // ========== 显示控制 ==========
    toggleSupplyRange(show) {
        this.showSupplyRange = show;
        if (this.supplyRangeRenderer) {
            if (show) {
                this.supplyRangeRenderer.show();
            } else {
                this.supplyRangeRenderer.hide();
            }
        } else {
            if (show) {
                this.supplyRangesLayer.addTo(this.map);
            } else {
                this.supplyRangesLayer.remove();
            }
        }
    }

    toggleHexagon(show) {
        this.showHexagon = show;
        this.renderSites();
    }

    setSizeByArea(enabled) {
        this.sizeByArea = enabled;
        this.renderSites();
    }

    setColorByStatus(enabled) {
        this.colorByStatus = enabled;
        this.renderSites();
    }

    // ========== 交互 ==========
    selectSite(siteId) {
        this.selectedSiteId = siteId;
        this.setSelected(siteId);

        const site = this.sites.find(s => s.id === siteId);
        if (site) {
            this.map.flyTo([site.latitude, site.longitude], 10, { duration: 0.8 });
        }

        this.onSiteSelect(siteId);
    }

    flyToSite(siteId) {
        const site = this.sites.find(s => s.id === siteId);
        if (site) {
            this.map.flyTo([site.latitude, site.longitude], 10, { duration: 0.8 });
        }
    }

    search(query) {
        if (!query) return [];
        const q = query.toLowerCase();
        return this.sites
            .filter(s => s.name.toLowerCase().includes(q))
            .slice(0, 10);
    }

    // ========== 辅助 ==========
    invalidateSize() {
        this.map.invalidateSize();
    }
}
