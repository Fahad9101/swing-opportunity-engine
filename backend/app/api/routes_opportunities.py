from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.errors import SOEError
from app.domain.enums import ScannerType
from app.orchestration.scan_pipeline import scan_manager
from app.persistence.database import SessionLocal
from app.persistence.repositories import ScanRepository


router = APIRouter(tags=["opportunities"])


@router.get("/opportunities")
def opportunities(scanner: ScannerType | None = None, sector: str | None = None, min_opportunity: float = Query(0, ge=0, le=100), biotech: bool | None = None, limit: int = Query(20, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict:
    state = scan_manager.latest_completed()
    with SessionLocal() as session:
        persisted = ScanRepository(session).latest_opportunities()
    items = persisted or ([item.model_dump(mode="json") for item in state.opportunities] if state else [])
    if not items: raise SOEError("NO_COMPLETED_SCAN", "No completed scan is available.", status_code=404)
    if scanner is not None:
        items = [item for item in items if scanner.value in [item["primary_scanner"], *item["secondary_scanners"]]]
    if min_opportunity:
        items = [item for item in items if item["scores"]["opportunity_score"] >= min_opportunity]
    if sector is not None:
        items = [item for item in items if item["sector"].casefold() == sector.casefold()]
    if biotech is not None:
        items = [item for item in items if item["is_biotech"] is biotech]
    selected = items[offset: offset + limit]
    return {"scan_run_id": str(state.scan_run_id) if state else None, "count": len(items), "limit": limit, "offset": offset, "data": selected}
