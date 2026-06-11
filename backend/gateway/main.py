"""
API 网关
统一入口，聚合各微服务API
端口：8000
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import logging
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import httpx

from common.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_gateway")

app = FastAPI(
    title="古代水利工程遗迹系统 - API网关",
    description="统一API入口，聚合遗迹数据、水力复原、可持续性评估、告警推送服务",
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 微服务地址
SERVICES = {
    "heritage": f"http://localhost:{settings.HERITAGE_LOADER_PORT}",
    "hydro": f"http://localhost:{settings.HYDRO_RECONSTRUCTOR_PORT}",
    "sustainability": f"http://localhost:{settings.SUSTAINABILITY_EVALUATOR_PORT}",
    "alarm": f"http://localhost:{settings.ALARM_PUBLISHER_PORT}",
}


async def forward_request(service: str, path: str, method: str = "GET",
                           params: dict = None, json_data: dict = None):
    """转发请求到后端微服务"""
    base_url = SERVICES.get(service)
    if not base_url:
        raise HTTPException(status_code=500, detail=f"未知服务: {service}")

    url = f"{base_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            if method == "GET":
                response = await client.get(url, params=params)
            elif method == "POST":
                response = await client.post(url, params=params, json=json_data)
            elif method == "PUT":
                response = await client.put(url, params=params, json=json_data)
            elif method == "DELETE":
                response = await client.delete(url, params=params)
            else:
                raise HTTPException(status_code=405, detail="不支持的方法")

            if response.status_code >= 400:
                raise HTTPException(status_code=response.status_code, detail=response.json())
            return response.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"服务不可用: {service}")
    except Exception as e:
        logger.error(f"转发请求失败: {e}")
        raise HTTPException(status_code=500, detail=f"网关错误: {str(e)}")


@app.get("/")
async def root():
    return {
        "app": settings.APP_NAME,
        "version": "3.0.0",
        "architecture": "微服务架构",
        "services": {
            "heritage_loader": f"{SERVICES['heritage']}/health",
            "hydro_reconstructor": f"{SERVICES['hydro']}/health",
            "sustainability_evaluator": f"{SERVICES['sustainability']}/health",
            "alarm_publisher": f"{SERVICES['alarm']}/health",
        },
        "endpoints": {
            "sites": "/api/sites",
            "hydrology": "/api/hydrology",
            "restoration": "/api/restoration/{site_id}",
            "assessment": "/api/assessment/{site_id}",
            "supply_ranges": "/api/supply-ranges",
            "cross_section": "/api/cross-section/{site_id}",
            "alerts": "/api/alerts",
            "comprehensive": "/api/sites/{id}/comprehensive",
        }
    }


@app.get("/health")
async def health_check():
    """网关健康检查"""
    statuses = {}
    all_ok = True
    for name, base_url in SERVICES.items():
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{base_url}/health")
                statuses[name] = "ok" if r.status_code == 200 else "error"
                if r.status_code != 200:
                    all_ok = False
        except Exception:
            statuses[name] = "unavailable"
            all_ok = False

    return {
        "status": "ok" if all_ok else "degraded",
        "gateway": "healthy",
        "services": statuses,
    }


# ==============================================
# 遗迹数据 API
# ==============================================

@app.get("/api/sites")
async def list_sites(
    skip: int = 0,
    limit: int = 100,
    site_type: Optional[str] = None,
    dynasty: Optional[str] = None,
    preservation_status: Optional[str] = None,
    min_irrigation_area: Optional[float] = None,
    max_irrigation_area: Optional[float] = None,
    min_longitude: Optional[float] = None,
    max_longitude: Optional[float] = None,
    min_latitude: Optional[float] = None,
    max_latitude: Optional[float] = None,
):
    params = {
        "skip": skip, "limit": limit,
        "site_type": site_type, "dynasty": dynasty,
        "preservation_status": preservation_status,
        "min_irrigation_area": min_irrigation_area,
        "max_irrigation_area": max_irrigation_area,
        "min_longitude": min_longitude, "max_longitude": max_longitude,
        "min_latitude": min_latitude, "max_latitude": max_latitude,
    }
    params = {k: v for k, v in params.items() if v is not None}
    return await forward_request("heritage", "/sites", "GET", params=params)


@app.get("/api/sites/{site_id}")
async def get_site(site_id: int):
    return await forward_request("heritage", f"/sites/{site_id}")


@app.post("/api/sites")
async def create_site(request: Request):
    body = await request.json()
    return await forward_request("heritage", "/sites", "POST", json_data=body)


@app.put("/api/sites/{site_id}")
async def update_site(site_id: int, request: Request):
    body = await request.json()
    return await forward_request("heritage", f"/sites/{site_id}", "PUT", json_data=body)


@app.delete("/api/sites/{site_id}")
async def delete_site(site_id: int):
    return await forward_request("heritage", f"/sites/{site_id}", "DELETE")


@app.get("/api/sites/{site_id}/comprehensive")
async def get_comprehensive(site_id: int):
    """获取综合信息（聚合三个服务的数据）"""
    results = {}

    # 并行请求
    import asyncio
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            site_task = client.get(f"{SERVICES['heritage']}/sites/{site_id}")
            resto_task = client.get(f"{SERVICES['hydro']}/restore/{site_id}")
            assess_task = client.get(f"{SERVICES['sustainability']}/assess/{site_id}")

            responses = await asyncio.gather(site_task, resto_task, assess_task,
                                             return_exceptions=True)

            site_resp, resto_resp, assess_resp = responses

            results["site"] = site_resp.json() if not isinstance(site_resp, Exception) and site_resp.status_code == 200 else None

            results["restoration"] = resto_resp.json() if not isinstance(resto_resp, Exception) and resto_resp.status_code == 200 else None

            results["assessment"] = assess_resp.json() if not isinstance(assess_resp, Exception) and assess_resp.status_code == 200 else None

        except Exception as e:
            logger.error(f"综合信息查询失败: {e}")

    if not results.get("site"):
        raise HTTPException(status_code=404, detail="遗迹不存在")

    return results


# ==============================================
# 水文 API
# ==============================================

@app.get("/api/hydrology")
async def list_hydrology(region: Optional[str] = None,
                          start_year: Optional[int] = None,
                          end_year: Optional[int] = None,
                          skip: int = 0, limit: int = 100):
    params = {"region": region, "start_year": start_year, "end_year": end_year,
              "skip": skip, "limit": limit}
    params = {k: v for k, v in params.items() if v is not None}
    return await forward_request("heritage", "/hydrology", "GET", params=params)


@app.get("/api/hydrology/by-site/{site_id}")
async def get_hydrology_for_site(site_id: int, period: str = "contemporary"):
    return await forward_request("heritage", f"/hydrology/by-site/{site_id}",
                                  "GET", params={"period": period})


# ==============================================
# 功能复原 API
# ==============================================

@app.post("/api/restoration/{site_id}")
async def restore_site(site_id: int, async_mode: bool = True):
    return await forward_request("hydro", f"/restore/{site_id}", "POST",
                                  params={"async_mode": async_mode})


@app.get("/api/restoration/{site_id}")
async def get_restoration(site_id: int):
    return await forward_request("hydro", f"/restore/{site_id}")


@app.post("/api/restoration/{site_id}/monte-carlo")
async def monte_carlo(site_id: int, n_samples: int = 1000, seed: int = 42):
    return await forward_request("hydro", f"/monte-carlo/{site_id}", "POST",
                                  params={"n_samples": n_samples, "seed": seed})


@app.post("/api/parameter-estimation/{site_id}")
async def param_estimation(site_id: int):
    return await forward_request("hydro", f"/parameter-estimation/{site_id}", "POST")


@app.get("/api/supply-ranges")
async def supply_ranges(
    min_longitude: Optional[float] = None,
    max_longitude: Optional[float] = None,
    min_latitude: Optional[float] = None,
    max_latitude: Optional[float] = None,
    simplified: bool = False,
    skip: int = 0, limit: int = 100,
):
    params = {
        "min_longitude": min_longitude, "max_longitude": max_longitude,
        "min_latitude": min_latitude, "max_latitude": max_latitude,
        "simplified": simplified, "skip": skip, "limit": limit,
    }
    params = {k: v for k, v in params.items() if v is not None}
    return await forward_request("hydro", "/supply-ranges", "GET", params=params)


@app.get("/api/cross-section/{site_id}")
async def cross_section(site_id: int):
    return await forward_request("hydro", f"/cross-section/{site_id}")


@app.post("/api/batch/restore")
async def batch_restore():
    return await forward_request("hydro", "/batch/restore", "POST")


# ==============================================
# 可持续性评估 API
# ==============================================

@app.post("/api/assessment/{site_id}")
async def assess_site(site_id: int, async_mode: bool = True):
    return await forward_request("sustainability", f"/assess/{site_id}", "POST",
                                  params={"async_mode": async_mode})


@app.get("/api/assessment/{site_id}")
async def get_assessment(site_id: int):
    return await forward_request("sustainability", f"/assess/{site_id}")


@app.get("/api/experts")
async def get_experts():
    return await forward_request("sustainability", "/experts")


@app.get("/api/aggregated-weights")
async def get_aggregated_weights():
    return await forward_request("sustainability", "/aggregated-weights")


@app.get("/api/criteria")
async def get_criteria():
    return await forward_request("sustainability", "/criteria")


@app.get("/api/rankings")
async def get_rankings(by: str = "total", limit: int = 20,
                        min_grade: Optional[str] = None):
    params = {"by": by, "limit": limit, "min_grade": min_grade}
    params = {k: v for k, v in params.items() if v is not None}
    return await forward_request("sustainability", "/rankings", "GET", params=params)


@app.post("/api/batch/assess")
async def batch_assess():
    return await forward_request("sustainability", "/batch/assess", "POST")


# ==============================================
# 告警 API
# ==============================================

@app.get("/api/alerts")
async def list_alerts(site_id: Optional[int] = None,
                       alert_level: Optional[str] = None,
                       acknowledged: Optional[bool] = None,
                       skip: int = 0, limit: int = 100):
    params = {"site_id": site_id, "alert_level": alert_level,
              "acknowledged": acknowledged, "skip": skip, "limit": limit}
    params = {k: v for k, v in params.items() if v is not None}
    return await forward_request("alarm", "/alerts", "GET", params=params)


@app.get("/api/alerts/{alert_id}")
async def get_alert(alert_id: int):
    return await forward_request("alarm", f"/alerts/{alert_id}")


@app.put("/api/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int):
    return await forward_request("alarm", f"/alerts/{alert_id}/acknowledge", "PUT")


@app.get("/api/mqtt/status")
async def mqtt_status():
    return await forward_request("alarm", "/mqtt/status")


@app.post("/api/mqtt/reconnect")
async def mqtt_reconnect():
    return await forward_request("alarm", "/mqtt/reconnect", "POST")


@app.get("/api/mqtt/dead-letter")
async def get_dead_letter(limit: int = 100):
    return await forward_request("alarm", "/mqtt/dead-letter", "GET", params={"limit": limit})


# ==============================================
# 统计 & 辅助
# ==============================================

@app.get("/api/statistics")
async def get_statistics():
    return await forward_request("heritage", "/statistics")


@app.get("/api/dynasties")
async def get_dynasties():
    return await forward_request("heritage", "/dynasties")


@app.get("/api/regions")
async def get_regions():
    return await forward_request("heritage", "/regions")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.GATEWAY_PORT)
