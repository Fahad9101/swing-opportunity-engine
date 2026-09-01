import json
import warnings
from pathlib import Path


def test_emit_conflict_snapshot_for_audit():
    path = Path("validation-results/milestone-1.1a/guidance_validation.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = {
        item["ticker"]: {
            "classification": item["classification"],
            "rule_path": item["rule_path"],
            "current": item["current"],
            "prior": item["prior"],
            "reasons": item["reasons"],
        }
        for item in payload["tickers"]
        if item["ticker"] in {"UPS", "CVS"}
    }
    warnings.warn("GUIDANCE_CONFLICT_AUDIT=" + json.dumps(rows, sort_keys=True), stacklevel=1)
    assert set(rows) == {"UPS", "CVS"}
