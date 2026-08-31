from fastapi import APIRouter

from app.core.errors import SOEError
from app.orchestration.scan_pipeline import scan_manager
from app.persistence.database import SessionLocal
from app.persistence.repositories import ScanRepository


router = APIRouter(tags=["market"])


@router.get("/market-regime")
def market_regime() -> dict:
    state = scan_manager.latest_completed()
    if state is not None and state.market_regime is not None:
        return state.market_regime.model_dump(mode="json")
    with SessionLocal() as session:
        persisted = ScanRepository(session).latest_market_regime()
    if persisted is None: raise SOEError("NO_COMPLETED_SCAN", "No completed market-regime scan is available.", status_code=404)
    return persisted
