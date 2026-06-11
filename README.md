# 古代水利工程遗迹功能复原与可持续性评估系统

> 基于微服务架构的古代水利工程遗迹管理系统，集成水力模型复原、AHP群决策评估、MQTT告警推送。

## 🏗️ 系统架构

```
                    ┌───────────────────────────────────────────────┐
                    │              Web 前端 (Vue/原生JS)            │
                    │   water_heritage_map.js + hydro_profile.js   │
                    └────────────────────────┬──────────────────────┘
                                             │ HTTP (Gzip)
                    ┌────────────────────────▼──────────────────────┐
                    │           Nginx (端口 8080 / Gzip)            │
                    └────────────────────────┬──────────────────────┘
                                             │ 反向代理
                    ┌────────────────────────▼──────────────────────┐
                    │           API Gateway :8000 (httpx)           │
                    │         统一入口 / 请求聚合 / 健康检查          │
                    └────┬──────┬───────┬────────────────────────┬──┘
                         │      │       │                        │
              ┌──────────▼┐ ┌───▼────┐ ┌▼───────────────┐ ┌──────▼───────┐
              │heritage   │ │hydro_  │ │sustainability_ │ │ alarm_       │
              │_loader    │ │recon-  │ │evaluator       │ │ publisher    │
              │:8001      │ │structor│ │:8003           │ │:8004         │
              │(数据管理)  │ │:8002   │ │(AHP评估)       │ │(MQTT告警)    │
              └─────┬─────┘ └───┬────┘ └───────┬────────┘ └──────┬───────┘
                    │           │              │                  │
                    └───────────┴──────┬───────┴──────────────────┘
                                       │  Redis Pub/Sub
                              ┌────────▼────────┐
                              │   事件消息总线    │
                              │  (频道事件驱动)   │
                              └─────────────────┘
         ┌──────────────────────┬──────────────────┬──────────────────────┐
 ┌───────▼───────┐     ┌────────▼───────┐   ┌──────▼────────┐    ┌────────▼───────┐
 │ PostgreSQL 16 │     │   Redis 7      │   │   Mosquitto   │    │  数据模拟器      │
 │   + PostGIS   │     │  (AOF持久化)   │   │   (MQTT v5)   │    │ (参数化生成)    │
 │  (空间索引)   │     └────────────────┘   │ (持久会话)    │    └────────────────┘
 └───────────────┘                          └───────────────┘
```

### 核心特性

- **微服务架构**：4个业务微服务 + 1个API网关，通过 Redis Pub/Sub 解耦
- **高性能空间查询**：PostGIS + GiST/BRIN 空间索引，百万级数据亚秒查询
- **参数化数据模拟**：按朝代、类型、种子生成测试数据
- **HTTP压缩**：Nginx Gzip，JS/CSS压缩率 >70%
- **生产级部署**：gunicorn + uvicorn worker，连接池，健康检查
- **可靠MQTT**：持久会话、QoS 1、遗嘱消息、死信队列、离线消息

---

## 📁 项目结构

```
AI_solo_coder_task_A_046/
├── backend/
│   ├── common/                 # 共享模块
│   │   ├── config.py           # 统一配置 + Redis频道
│   │   ├── database.py         # SQLAlchemy连接池
│   │   ├── models.py           # 6个数据模型
│   │   ├── schemas.py          # Pydantic Schema
│   │   ├── redis_client.py     # Redis Pub/Sub客户端
│   │   └── params/             # 参数外置目录
│   │       ├── hydraulic_params.py   # 水力模型参数
│   │       └── ahp_params.py         # AHP评估参数
│   ├── services/               # 微服务
│   │   ├── heritage_loader/    # 遗迹数据管理 (端口 8001)
│   │   ├── hydro_reconstructor/ # 水力复原 (端口 8002)
│   │   ├── sustainability_evaluator/ # AHP评估 (端口 8003)
│   │   └── alarm_publisher/    # MQTT告警 (端口 8004)
│   ├── gateway/                # API网关 (端口 8000)
│   ├── scripts/
│   │   └── run_simulator.py    # 数据模拟器 CLI
│   ├── requirements.txt
│   ├── test_algorithms.py      # 算法回归测试
│   └── test_refactor.py        # 模块导入测试
├── frontend/
│   ├── index.html
│   └── js/
│       ├── water_heritage_map.js    # 地图模块
│       ├── hydro_profile.js         # 水文/剖面图模块
│       ├── supply-range-renderer.js # 灌溉区渲染器
│       └── app.js                   # 应用协调层
├── deploy/
│   ├── nginx/                  # Nginx配置 (Gzip + 反向代理)
│   ├── mosquitto/              # MQTT Broker配置
│   └── sql/                    # PostGIS空间索引
├── scripts/                    # 数据库初始化SQL (共享挂载)
├── Dockerfile                  # 多阶段构建
├── docker-compose.yml          # 服务编排
├── .env.example                # 环境变量模板
└── README.md
```

---

## 🚀 快速部署

### 环境要求

- Docker >= 24.0
- Docker Compose >= 2.20
- 至少 4GB 可用内存
- 10GB 可用磁盘

### 一键启动

```bash
# 1. 克隆项目后，进入目录
cd AI_solo_coder_task_A_046

# 2. 配置环境变量（可选，默认值即可运行）
cp .env.example .env
# 编辑 .env 修改密码

# 3. 启动所有服务
docker compose up -d --build

# 4. 等待所有服务健康检查通过（约30秒）
docker compose ps

# 5. 生成测试数据（300处遗迹 + 水文）
docker compose --profile simulator run --rm simulator

# 6. 打开浏览器访问
#    前端: http://localhost:8080
#    API:  http://localhost:8080/api/health
```

### 服务端口

| 服务 | 容器端口 | 暴露端口 | 说明 |
|------|---------|---------|------|
| **前端 (Nginx)** | - | 8080 | Web界面 + API代理 + Gzip |
| **API Gateway** | 8000 | - | 内部网关 |
| **heritage_loader** | 8001 | - | 内部 |
| **hydro_reconstructor** | 8002 | - | 内部 |
| **sustainability_evaluator** | 8003 | - | 内部 |
| **alarm_publisher** | 8004 | - | 内部 |
| **PostgreSQL** | 5432 | 5432 | 数据库（可直连调试） |
| **Redis** | 6379 | 6379 | 消息总线 |
| **Mosquitto MQTT** | 1883/9001 | 1883/9001 | MQTT + WebSocket |

### 常用命令

```bash
# 查看所有服务状态
docker compose ps

# 查看某个服务日志
docker compose logs -f gateway
docker compose logs -f hydro-reconstructor

# 重启某个服务
docker compose restart alarm-publisher

# 停止所有服务
docker compose down

# 停止并清理数据（⚠️ 会删除数据库）
docker compose down -v

# 仅更新网关（不重建其他服务）
docker compose up -d --build gateway
```

---

## 🧪 数据模拟器

生成不同年代、不同类型的遗迹数据和水文重建数据。

### Docker 方式（推荐）

```bash
# 默认: 300处遗迹，全朝代，全类型
docker compose --profile simulator run --rm simulator

# 自定义参数
docker compose --profile simulator run --rm simulator \
    python -m scripts.run_simulator \
    --sites 500 \
    --dynasty 唐 \
    --type 渠,堰 \
    --seed 123
```

### 本地 CLI 方式（需要 Python + 数据库依赖）

```bash
cd backend
python -m scripts.run_simulator --help

# 常见用法
python -m scripts.run_simulator                          # 默认300处
python -m scripts.run_simulator --sites 1000             # 1000处遗迹
python -m scripts.run_simulator --dynasty 宋              # 仅宋代（北宋+南宋）
python -m scripts.run_simulator --type 塘                 # 仅塘类
python -m scripts.run_simulator --dynasty 明 --type 井    # 明代井
python -m scripts.run_simulator --no-hydrology            # 不生成水文
python -m scripts.run_simulator --hydro-only              # 仅水文
python -m scripts.run_simulator --list-dynasties          # 列出所有朝代
python -m scripts.run_simulator --dry-run                 # 只生成不入库
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--sites` | int | 300 | 生成遗迹数量 |
| `--dynasty` | str | all | 朝代过滤：唐、宋、明、清等 |
| `--type` | str | all | 类型过滤：渠,堰,陂,塘,井（逗号分隔） |
| `--seed` | int | 42 | 随机种子（相同种子数据一致） |
| `--no-hydrology` | flag | - | 不生成水文数据 |
| `--hydro-only` | flag | - | 仅生成水文数据 |
| `--dry-run` | flag | - | 仅生成打印，不写入数据库 |
| `--list-dynasties` | flag | - | 列出所有支持的朝代 |

### 朝代列表

```
春秋(-770~-476)  战国(-475~-221)  秦(-221~-207)  西汉(-206~8)
东汉(25~220)     三国(220~280)     西晋(265~316)  东晋(317~420)
南北朝(420~589)  隋(581~618)       唐(618~907)    五代(907~960)
北宋(960~1127)   南宋(1127~1279)   元(1271~1368)  明(1368~1644)
清(1644~1912)
```

---

## 🔌 API 接口

所有 API 通过前端 Nginx 代理，统一入口 `http://localhost:8080/api`

### 遗迹数据管理 (heritage_loader)

```
GET    /api/sites                  # 遗迹列表（支持筛选/分页）
GET    /api/sites/{id}             # 遗迹详情
POST   /api/sites                  # 新增遗迹
PUT    /api/sites/{id}             # 更新遗迹
DELETE /api/sites/{id}             # 删除遗迹
GET    /api/sites/{id}/hydrology   # 关联水文数据
GET    /api/sites/stats            # 统计信息
GET    /api/dynasties              # 朝代字典
```

### 水力复原 (hydro_reconstructor)

```
POST   /api/restoration/restore/{id}       # 触发复原
GET    /api/restoration/{id}               # 复原结果
GET    /api/restoration/monte-carlo/{id}   # 蒙特卡洛分析
GET    /api/restoration/parameter-estimation/{id}  # 参数估计
GET    /api/supply-ranges                  # 灌溉区GeoJSON
GET    /api/cross-section/{id}             # 剖面图数据
POST   /api/batch/restore                  # 批量复原
```

### AHP评估 (sustainability_evaluator)

```
POST   /api/assessment/assess/{id}         # 触发评估
GET    /api/assessment/{id}                # 评估结果
GET    /api/experts                        # 专家配置
GET    /api/aggregated-weights             # 聚合权重
GET    /api/check-consistency              # 一致性检查
GET    /api/correct-consistency            # 一致性修正
GET    /api/rankings                       # 综合排名
POST   /api/batch/assess                   # 批量评估
```

### 告警推送 (alarm_publisher)

```
GET    /api/alerts                         # 告警列表
GET    /api/alerts/{id}                    # 告警详情
PUT    /api/alerts/{id}/confirm            # 确认告警
GET    /api/mqtt/status                    # MQTT连接状态
POST   /api/mqtt/reconnect                 # 重连MQTT
GET    /api/mqtt/dead-letter               # 死信队列
POST   /api/alerts/test                    # 发送测试告警
```

### 聚合接口 (Gateway)

```
GET    /api/sites/{id}/comprehensive       # 综合信息（遗迹+复原+评估）
GET    /health                              # 所有服务健康检查
```

---

## 📡 Redis Pub/Sub 事件频道

微服务间通过以下事件驱动协作：

| 频道 | 发布者 | 订阅者 | 说明 |
|------|--------|--------|------|
| `heritage:imported` | heritage_loader | hydro_reconstructor | 新遗迹导入 |
| `heritage:updated` | heritage_loader | alarm_publisher | 遗迹更新 |
| `heritage:deleted` | heritage_loader | - | 遗迹删除 |
| `restoration:requested` | gateway | hydro_reconstructor | 请求复原 |
| `restoration:completed` | hydro_reconstructor | sustainability_evaluator | 复原完成 |
| `restoration:failed` | hydro_reconstructor | - | 复原失败 |
| `assessment:requested` | gateway | sustainability_evaluator | 请求评估 |
| `assessment:completed` | sustainability_evaluator | - | 评估完成 |
| `assessment:failed` | sustainability_evaluator | - | 评估失败 |
| `alert:triggered` | heritage_loader | alarm_publisher | 触发告警 |
| `alert:published` | alarm_publisher | - | 告警已推送 |
| `batch:restore:requested` | gateway | hydro_reconstructor | 批量复原 |
| `batch:assess:requested` | gateway | sustainability_evaluator | 批量评估 |

---

## 🎯 性能优化要点

### PostgreSQL / PostGIS

| 优化项 | 说明 |
|--------|------|
| **GiST空间索引** | `geom` 字段建 GiST，地理范围查询加速 10~100x |
| **BRIN块索引** | `(longitude, latitude)` 建 BRIN，大表低占用 |
| **复合索引** | `(dynasty_order, site_type)` 常见筛选组合 |
| **连接池参数** | shared_buffers=256MB, max_connections=200 |
| **初始化脚本** | `init_database.sql` → `upgrade_v2.sql` → `spatial_indexes.sql` |

### Nginx / 前端

| 优化项 | 说明 |
|--------|------|
| **Gzip压缩** | level=6，JS/CSS/JSON/SVG均压缩，压缩率>70% |
| **静态缓存** | CSS/JS缓存30天，字体缓存1年，HTML不缓存 |
| **Keepalive** | upstream keepalive=32，复用后端连接 |
| **大响应支持** | client_max_body_size=50M，支持GeoJSON |

### FastAPI / gunicorn

| 优化项 | 说明 |
|--------|------|
| **UvicornWorker** | async worker，高并发 |
| **Worker数量** | gateway=4, hydro=4, assess=4, loader=2, alarm=2 |
| **连接池** | SQLAlchemy pool_size=5, max_overflow=10 |
| **请求超时** | 复原/评估服务 timeout=300s |

---

## 🧪 测试

### 算法回归测试（无外部依赖）

```bash
cd backend
python test_algorithms.py
```

测试内容：
- ✅ 宽顶堰流、曼宁公式、锥形库容、Dupuit井流
- ✅ 参数估计器（朝代技术因子、可靠度）
- ✅ AHP群决策（5专家几何平均、一致性检验）
- ✅ 蒙特卡洛不确定性分析（SRC敏感性、收敛检验）
- ✅ 保存状态折减系数

---

## 🔧 故障排查

### 所有服务都启动了但前端无数据

```bash
# 1. 检查是否生成了数据
docker compose --profile simulator run --rm simulator

# 2. 检查数据库
docker compose exec postgres psql -U water_heritage -c "SELECT count(*) FROM water_heritage_sites;"

# 3. 检查网关健康
curl http://localhost:8080/api/health
```

### MQTT 连接不上

```bash
# 检查mosquitto日志
docker compose logs mosquitto

# 检查连接状态
curl http://localhost:8080/api/mqtt/status

# 手动重连
curl -X POST http://localhost:8080/api/mqtt/reconnect
```

### 水力/评估接口超时

```bash
# hydro_reconstructor 服务日志
docker compose logs -f hydro-reconstructor

# sustainability_evaluator 服务日志
docker compose logs -f sustainability-evaluator
```

---

## 📄 License

内部项目
