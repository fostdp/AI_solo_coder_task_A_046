# 多阶段构建 - 后端基础镜像
FROM python:3.11-slim AS base

WORKDIR /app

# 系统依赖（psycopg2/shapely需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libgeos-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Python依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 生产环境需要的gunicorn
RUN pip install --no-cache-dir gunicorn==21.2.0

# ===== 网关服务 =====
FROM base AS gateway
COPY backend/common /app/common
COPY backend/gateway /app/gateway
WORKDIR /app
EXPOSE 8000
CMD ["gunicorn", \
    "-k", "uvicorn.workers.UvicornWorker", \
    "--workers", "4", \
    "--threads", "4", \
    "--worker-connections", "1000", \
    "--timeout", "120", \
    "--keep-alive", "5", \
    "--bind", "0.0.0.0:8000", \
    "--access-logfile", "-", \
    "--error-logfile", "-", \
    "gateway.main:app"]

# ===== heritage_loader 服务 =====
FROM base AS heritage_loader
COPY backend/common /app/common
COPY backend/services/heritage_loader /app/services/heritage_loader
WORKDIR /app
EXPOSE 8001
CMD ["gunicorn", \
    "-k", "uvicorn.workers.UvicornWorker", \
    "--workers", "2", \
    "--timeout", "120", \
    "--bind", "0.0.0.0:8001", \
    "services.heritage_loader.main:app"]

# ===== hydro_reconstructor 服务 =====
FROM base AS hydro_reconstructor
COPY backend/common /app/common
COPY backend/services/hydro_reconstructor /app/services/hydro_reconstructor
WORKDIR /app
EXPOSE 8002
CMD ["gunicorn", \
    "-k", "uvicorn.workers.UvicornWorker", \
    "--workers", "4", \
    "--timeout", "300", \
    "--bind", "0.0.0.0:8002", \
    "services.hydro_reconstructor.main:app"]

# ===== sustainability_evaluator 服务 =====
FROM base AS sustainability_evaluator
COPY backend/common /app/common
COPY backend/services/sustainability_evaluator /app/services/sustainability_evaluator
WORKDIR /app
EXPOSE 8003
CMD ["gunicorn", \
    "-k", "uvicorn.workers.UvicornWorker", \
    "--workers", "4", \
    "--timeout", "300", \
    "--bind", "0.0.0.0:8003", \
    "services.sustainability_evaluator.main:app"]

# ===== alarm_publisher 服务 =====
FROM base AS alarm_publisher
COPY backend/common /app/common
COPY backend/services/alarm_publisher /app/services/alarm_publisher
WORKDIR /app
EXPOSE 8004
CMD ["gunicorn", \
    "-k", "uvicorn.workers.UvicornWorker", \
    "--workers", "2", \
    "--timeout", "120", \
    "--bind", "0.0.0.0:8004", \
    "services.alarm_publisher.main:app"]

# ===== 数据模拟器服务 =====
FROM base AS simulator
COPY backend/common /app/common
COPY backend/scripts /app/scripts
COPY backend/services /app/services
WORKDIR /app
CMD ["python", "-m", "scripts.run_simulator"]
