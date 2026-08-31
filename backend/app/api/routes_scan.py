from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter

from app.core.errors import SOEError
from app.orchestration.scan_pipeline import run_full_scan, scan_manager


router = APIRouter(tags=["scans"])
_tasks: set[asyncio.Task] = set()


@router.post("/scans", status_code=202)
async def start_scan() -> dict:
    state = scan_manager.create()
    task = asyncio.create_task(run_full_scan(state.scan_run_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"scan_run_id": str(state.scan_run_id), "status": state.status, "model_version": state.model_version}


@router.get("/scans/{scan_run_id}")
def scan_status(scan_run_id: UUID) -> dict:
    state = scan_manager.get(scan_run_id)
    if state is None: raise SOEError("SCAN_NOT_FOUND", "The requested scan does not exist.", status_code=404)
    return {"scan_run_id": str(state.scan_run_id), "status": state.status, "stage": state.stage, "progress": state.progress, "universe_count": state.universe_count, "universal_pass_count": state.universal_pass_count, "scanner_match_counts": state.scanner_match_counts, "candidate_count": state.candidate_count, "error_count": state.error_count, "model_version": state.model_version, "rules_hash": state.rules_hash, "errors": state.errors}
