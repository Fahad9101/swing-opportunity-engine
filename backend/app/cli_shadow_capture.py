from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.domain.enums import ScanStatus
from app.orchestration.scan_pipeline import run_full_scan, scan_manager
from app.persistence.database import init_database


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture the single SOE-1.1E full-market baseline snapshot")
    parser.add_argument("--provider", default="free_public")
    parser.add_argument(
        "--output-meta",
        default="validation-results/milestone-1.1e/capture_meta.json",
    )
    return parser.parse_args()


async def _capture(*, provider: str, output_meta: str | Path) -> int:
    init_database()
    state = scan_manager.create()
    state = await run_full_scan(state.scan_run_id, provider_name=provider)
    if state.status != ScanStatus.COMPLETED:
        raise RuntimeError(f"Baseline full-market capture failed: {state.errors[-10:]}")

    payload = {
        "phase": "1.1E",
        "scan_run_id": str(state.scan_run_id),
        "universe_count": int(state.universe_count),
        "provider": provider,
    }
    path = Path(output_meta)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
    return 0


def main() -> int:
    args = _parse_args()
    return asyncio.run(_capture(provider=args.provider, output_meta=args.output_meta))


if __name__ == "__main__":
    raise SystemExit(main())
