from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api.routes_health import router as health_router
from app.api.routes_market import router as market_router
from app.api.routes_opportunities import router as opportunities_router
from app.api.routes_scan import router as scan_router
from app.core.config import get_settings
from app.core.constants import MODEL_NAME, MODEL_VERSION
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.persistence.database import init_database


@asynccontextmanager
async def lifespan(application: FastAPI):
    init_database()
    yield


configure_logging(get_settings().log_level)
app = FastAPI(title=MODEL_NAME, version=MODEL_VERSION, lifespan=lifespan)
install_error_handlers(app)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


for router in (health_router, scan_router, opportunities_router, market_router):
    app.include_router(router, prefix="/api/v1")
