from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from app.services.guidance_canonical_differential_service import (
    canonical_guidance_differential_report,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Offline differential audit of legacy vs canonical guidance evidence."
    )
    result.add_argument("validation_json", type=Path)
    result.add_argument(
        "--rules",
        type=Path,
        default=Path("config/soe_v1_1_rules.yaml"),
    )
    result.add_argument("--output", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    validation = json.loads(args.validation_json.read_text(encoding="utf-8"))
    rules = yaml.safe_load(args.rules.read_text(encoding="utf-8"))
    rules_hash = str(validation.get("candidate_rules_hash") or "canonical-differential")

    report = canonical_guidance_differential_report(
        validation,
        rules,
        rules_hash=rules_hash,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print(
        "canonical guidance differential: "
        f"tickers={report['tickers_with_guidance_payload']} "
        f"legacy_records={report['legacy_record_count']} "
        f"canonical_facts={report['canonical_fact_count']} "
        f"quarantined={report['quarantined_fact_count']} "
        f"divergences={report['classification_divergence_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
