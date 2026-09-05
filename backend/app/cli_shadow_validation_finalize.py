from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from app import cli_shadow_validation
from app.cli_shadow_validation_guarded import consume_sec_row_errors, install_guards
from app.domain.enums import ScanStatus
from app.persistence.database import init_database
from app.services.shadow_chunk_service import build_shadow_chunk_context, merge_growth_chunks


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize chunked SOE-1.1E same-snapshot shadow validation")
    parser.add_argument("--capture-meta", required=True)
    parser.add_argument("--chunks-dir", required=True)
    parser.add_argument("--contract", default="validation/phase_1_1e_shadow_contract_v1.json")
    parser.add_argument("--output-dir", default="validation-results/milestone-1.1e")
    parser.add_argument("--provider", default="free_public")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    install_guards()
    init_database()

    capture_meta = json.loads(Path(args.capture_meta).read_text(encoding="utf-8"))
    scan_run_id = str(capture_meta["scan_run_id"])
    context = build_shadow_chunk_context(scan_run_id)

    chunk_paths = sorted(Path(args.chunks_dir).rglob("growth-*.json"))
    if not chunk_paths:
        raise RuntimeError("No growth chunk payloads were found")
    chunk_payloads = [json.loads(path.read_text(encoding="utf-8")) for path in chunk_paths]
    precomputed = merge_growth_chunks(
        chunk_payloads,
        expected_tickers=context.growth_targets,
        fingerprint=context.fingerprint,
        baseline_hash=context.baseline_hash,
        candidate_hash=context.candidate_hash,
    )

    print(
        json.dumps(
            {
                "reused_scan_run_id": scan_run_id,
                "captured_snapshot_fingerprint": context.fingerprint,
                "growth_targets": len(context.growth_targets),
                "growth_chunks": len(chunk_payloads),
                "precomputed_growth_results": len(precomputed),
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )

    real_enricher_class = cli_shadow_validation.ShadowStructuralEnricher

    class PrecomputedGrowthThenCatalystEnricher:
        """Serve exact precomputed growth evidence, then use live primary evidence for catalysts."""

        def __init__(self, *, rules, rules_hash, cache_dir=None):
            self._real = real_enricher_class(rules=rules, rules_hash=rules_hash, cache_dir=cache_dir)

        async def enrich(
            self,
            instrument,
            fundamental,
            events,
            *,
            need_guidance: bool,
            need_distress: bool,
            need_catalyst: bool,
        ):
            if need_guidance or need_distress:
                item = precomputed.get(instrument.ticker)
                if item is None:
                    raise RuntimeError(f"Missing precomputed growth enrichment for {instrument.ticker}")
                if need_catalyst:
                    overrides, rows, errors = await self.assess_earnings_catalysts(instrument.ticker, events)
                    item.catalyst_overrides.update(overrides)
                    item.catalysts.extend(rows)
                    item.errors.extend(errors)
                return item
            return await self._real.enrich(
                instrument,
                fundamental,
                events,
                need_guidance=need_guidance,
                need_distress=need_distress,
                need_catalyst=need_catalyst,
            )

        async def assess_earnings_catalysts(self, ticker, events):
            overrides, rows, errors = await self._real.assess_earnings_catalysts(ticker, events)
            errors.extend(consume_sec_row_errors(ticker))
            return overrides, rows, errors

        def close(self) -> None:
            self._real.close()

    class ReplayScanManager:
        def create(self):
            return SimpleNamespace(
                scan_run_id=scan_run_id,
                status=ScanStatus.COMPLETED,
                universe_count=int(capture_meta["universe_count"]),
                errors=[],
            )

    async def replay_full_scan(_scan_run_id, *, provider_name: str):
        if str(_scan_run_id) != scan_run_id:
            raise RuntimeError("Final reducer attempted to use a different scan_run_id")
        if provider_name != capture_meta.get("provider", provider_name):
            raise RuntimeError("Final reducer provider does not match capture provider")
        return SimpleNamespace(
            scan_run_id=scan_run_id,
            status=ScanStatus.COMPLETED,
            universe_count=int(capture_meta["universe_count"]),
            errors=[],
        )

    # Reuse the original 1.1E report/evaluation function while replacing only
    # the already-completed baseline market capture and growth-enrichment I/O.
    cli_shadow_validation.scan_manager = ReplayScanManager()
    cli_shadow_validation.run_full_scan = replay_full_scan
    cli_shadow_validation.ShadowStructuralEnricher = PrecomputedGrowthThenCatalystEnricher

    _, automated_pass = asyncio.run(
        cli_shadow_validation.run_shadow_validation(
            contract_path=args.contract,
            output_dir=args.output_dir,
            provider_name=args.provider,
        )
    )
    return 0 if automated_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
