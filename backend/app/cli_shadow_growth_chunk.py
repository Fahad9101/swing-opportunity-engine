from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.cli_shadow_validation_guarded import install_guards
from app.persistence.database import init_database
from app.services.shadow_chunk_service import (
    build_shadow_chunk_context,
    partition_targets,
    serialize_growth_result,
)
from app.services.shadow_enrichment_service import ShadowStructuralEnricher


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one same-snapshot SOE-1.1E growth-enrichment chunk")
    parser.add_argument("--capture-meta", required=True)
    parser.add_argument("--chunk-index", type=int, required=True)
    parser.add_argument("--chunk-count", type=int, required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    install_guards()
    init_database()
    meta = json.loads(Path(args.capture_meta).read_text(encoding="utf-8"))
    scan_run_id = str(meta["scan_run_id"])
    context = build_shadow_chunk_context(scan_run_id)
    targets = partition_targets(
        context.growth_targets,
        chunk_index=args.chunk_index,
        chunk_count=args.chunk_count,
    )

    items = []
    enricher = ShadowStructuralEnricher(
        rules=context.candidate_rules,
        rules_hash=context.candidate_hash,
    )
    try:
        for index, ticker in enumerate(targets, start=1):
            print(
                f"[1.1E growth chunk {args.chunk_index + 1}/{args.chunk_count} "
                f"{index}/{len(targets)}] {ticker}",
                flush=True,
            )
            result = await enricher.enrich(
                context.capture["instruments"][ticker],
                context.capture["fundamentals"].get(ticker),
                list(context.capture["events"].get(ticker, [])),
                need_guidance=True,
                need_distress=True,
                need_catalyst=False,
            )
            items.append(serialize_growth_result(result))
    finally:
        enricher.close()

    payload = {
        "phase": "1.1E",
        "scan_run_id": scan_run_id,
        "fingerprint": context.fingerprint,
        "baseline_rules_hash": context.baseline_hash,
        "candidate_rules_hash": context.candidate_hash,
        "growth_target_count": len(context.growth_targets),
        "chunk_index": args.chunk_index,
        "chunk_count": args.chunk_count,
        "selected_count": len(targets),
        "items": items,
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "chunk_index": args.chunk_index,
                "chunk_count": args.chunk_count,
                "selected_count": len(targets),
                "fingerprint": context.fingerprint,
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
