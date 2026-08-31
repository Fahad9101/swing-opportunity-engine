from fastapi import APIRouter
from sqlalchemy import text

from app.core.constants import MODEL_VERSION
from app.persistence.database import SessionLocal
from app.providers.provider_registry import get_provider


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    database_status = "ok"
    try:
        with SessionLocal() as session: session.execute(text("SELECT 1"))
    except Exception:
        database_status = "unavailable"
    provider = get_provider()
    return {"status": "ok" if database_status == "ok" else "degraded", "model_version": MODEL_VERSION, "database_status": database_status, "provider_status": {"name": provider.name, "status": "ok", "data_mode": "synthetic_fixture" if provider.name == "fixture" else "production"}}

