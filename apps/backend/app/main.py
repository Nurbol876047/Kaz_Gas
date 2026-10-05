import asyncio
import hashlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import select

from app.api import router
from app.subscribers import router as subscriber_router, internal as subscriber_internal
from app.auth import redis
from app.config import get_settings
from app.database import Session, engine, utcnow
from app.ddos_monitor import DDoSMetrics, detect_ddos
from app.models import Admin, AdminSession
from app.prometheus import collect_ddos_metrics, is_available


# ---------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------

HTTP_REQUESTS_TOTAL = Counter(
    "utility_http_requests_total",
    "Total number of HTTP requests received by the backend",
    ["method", "path", "status"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "utility_http_request_duration_seconds",
    "HTTP request processing duration in seconds",
    ["method", "path"],
)

MONITORING_WEBSOCKET_CONNECTIONS = Gauge(
    "utility_monitoring_websocket_connections",
    "Current number of monitoring WebSocket connections",
)


# ---------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------

@asynccontextmanager
async def lifespan(app):
    yield
    await redis.aclose()
    await engine.dispose()


settings = get_settings()

app = FastAPI(
    title="Utility Desk API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs"
    if settings.environment != "production"
    else None,
    redoc_url=None,
    openapi_url="/openapi.json"
    if settings.environment != "production"
    else None,
)


# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=[
        "GET",
        "POST",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ],
    allow_headers=[
        "Content-Type",
        "X-CSRF-Token",
        "Last-Event-ID",
    ],
)


# ---------------------------------------------------------
# HTTP security + Prometheus request metrics
# ---------------------------------------------------------

@app.middleware("http")
async def security_headers(request: Request, call_next):
    length = request.headers.get("content-length")

    if length and (
        not length.isdigit()
        or int(length)
        > settings.max_photo_bytes + 64 * 1024
    ):
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            path=request.url.path,
            status="413",
        ).inc()

        return JSONResponse(
            {"detail": "Request too large"},
            status_code=413,
        )

    method = request.method
    path = request.url.path

    with HTTP_REQUEST_DURATION_SECONDS.labels(
        method=method,
        path=path,
    ).time():
        response = await call_next(request)

    HTTP_REQUESTS_TOTAL.labels(
        method=method,
        path=path,
        status=str(response.status_code),
    ).inc()

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers.setdefault(
        "Cache-Control",
        "no-store",
    )

    return response


# ---------------------------------------------------------
# Prometheus scrape endpoint
# ---------------------------------------------------------

@app.get(
    "/metrics",
    include_in_schema=False,
)
async def prometheus_metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


# ---------------------------------------------------------
# Monitoring WebSocket
# ---------------------------------------------------------

@app.websocket("/ws/monitoring")
async def monitoring_websocket(
    websocket: WebSocket,
):
    token = websocket.cookies.get("session", "")

    if not token:
        await websocket.close(code=1008)
        return

    token_hash = hashlib.sha256(
        token.encode()
    ).hexdigest()

    async with Session() as db:
        record = (
            await db.execute(
                select(
                    AdminSession,
                    Admin,
                )
                .join(Admin)
                .where(
                    AdminSession.token_hash
                    == token_hash,
                    AdminSession.expires_at
                    > utcnow(),
                    Admin.active.is_(True),
                )
            )
        ).first()

        if not record:
            await websocket.close(code=1008)
            return

    await websocket.accept()
    MONITORING_WEBSOCKET_CONNECTIONS.inc()

    try:
        while True:
            prometheus_up = await is_available()

            if not prometheus_up:
                await websocket.send_json(
                    {
                        "type": "monitoring",
                        "status": "degraded",
                        "prometheus": "down",
                        "ddos": {
                            "status": "unknown",
                            "warning_count": 0,
                            "attack_count": 0,
                            "unavailable_count": 6,
                            "warning_signals": [],
                            "attack_signals": [],
                            "unavailable_signals": [
                                "prometheus",
                            ],
                        },
                        "metrics": None,
                    }
                )

                await asyncio.sleep(5)
                continue

            raw_metrics = await collect_ddos_metrics()

            if raw_metrics is None:
                await websocket.send_json(
                    {
                        "type": "monitoring",
                        "status": "degraded",
                        "prometheus": "up",
                        "ddos": {
                            "status": "unknown",
                            "warning_count": 0,
                            "attack_count": 0,
                            "unavailable_count": 1,
                            "warning_signals": [],
                            "attack_signals": [],
                            "unavailable_signals": [
                                "current_rps",
                            ],
                        },
                        "metrics": None,
                    }
                )

                await asyncio.sleep(5)
                continue

            metrics = DDoSMetrics(
                current_rps=raw_metrics[
                    "current_rps"
                ],
                average_rps_7d=raw_metrics[
                    "average_rps_7d"
                ],
                syn_recv=raw_metrics[
                    "syn_recv"
                ],
                error_rate_429_503=raw_metrics[
                    "error_rate_429_503"
                ],
                inbound_traffic_percent=raw_metrics[
                    "inbound_traffic_percent"
                ],
                requests_per_ip_minute=raw_metrics[
                    "requests_per_ip_minute"
                ],
                unique_ip_spike_ratio=raw_metrics[
                    "unique_ip_spike_ratio"
                ],
            )

            result = detect_ddos(metrics)

            monitoring_status = (
                "degraded"
                if result.status.value == "unknown"
                else "connected"
            )

            await websocket.send_json(
                {
                    "type": "monitoring",
                    "status": monitoring_status,
                    "prometheus": "up",
                    "ddos": {
                        "status": result.status.value,
                        "warning_count":
                            result.warning_count,
                        "attack_count":
                            result.attack_count,
                        "unavailable_count":
                            result.unavailable_count,
                        "warning_signals":
                            result.warning_signals,
                        "attack_signals":
                            result.attack_signals,
                        "unavailable_signals":
                            result.unavailable_signals,
                    },
                    "metrics": raw_metrics,
                }
            )

            await asyncio.sleep(5)

    except WebSocketDisconnect:
        pass

    finally:
        MONITORING_WEBSOCKET_CONNECTIONS.dec()


# ---------------------------------------------------------
# API routes
# ---------------------------------------------------------

app.include_router(
    router,
    prefix="/api",
)
app.include_router(subscriber_router)
app.include_router(subscriber_internal)
