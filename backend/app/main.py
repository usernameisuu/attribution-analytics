"""Application entry point and HTTP-wide boundaries."""
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .access import DB
from .config import settings
from .event_api import router as event_router
from .modules.analysis.api import router as analysis_router
from .modules.analysis.archive_api import router as archive_router
from .modules.identity.api import router as identity_router
from .modules.analysis.metric_drafts_api import router as metric_drafts_router
from .modules.analysis.briefs_api import router as briefs_router
from .pipeline_api import router as pipeline_router

app = FastAPI(title="经营归因分析系统", version="0.2.0")
app.include_router(pipeline_router)
app.include_router(event_router)
app.include_router(identity_router)
app.include_router(analysis_router)
app.include_router(archive_router)
app.include_router(metric_drafts_router)
app.include_router(briefs_router)


@app.middleware("http")
async def request_boundary(request: Request, call_next):
    request_id = str(uuid4())
    request.state.request_id = request_id
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        config = settings()
        allowed_origins = {origin.rstrip("/") for origin in [config.public_origin, *config.additional_public_origins] if origin}
        if request.headers.get("origin") not in allowed_origins:
            return JSONResponse({"code": "ORIGIN_REJECTED", "message": "请求来源无效", "request_id": request_id}, status_code=403)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse({"code": f"HTTP_{exc.status_code}", "message": exc.detail,
                         "request_id": request.state.request_id}, status_code=exc.status_code)


@app.get("/api/v1/health")
def health(db: DB):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "capabilities": {"deterministic_analysis": True, "datasets": True,
            "durable_queue": True, "model_gateway": True, "model_configuration": "worker_only",
            "sandbox": False, "statistics": False, "daily_welch_check": True}}
