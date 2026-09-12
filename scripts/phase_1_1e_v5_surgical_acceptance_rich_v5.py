from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v5.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_replay_differential_service.py"
text = path.read_text()
old = '''                "quarantine_codes": dict(sorted(ticker_codes.items())),\n                "rejected_candidate_count": len(rejected),\n            }\n        )\n'''
new = '''                "quarantine_codes": dict(sorted(ticker_codes.items())),\n                "rejected_candidate_count": len(rejected),\n                "accepted_facts": [_fact_summary(fact) for fact in canonical.accepted],\n                "quarantined_facts": [_quarantine_summary(item) for item in canonical.quarantined],\n                "rejected_candidates": rejected,\n            }\n        )\n'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"rich complete-ticker report patch: expected one match, found {count}")
path.write_text(text.replace(old, new, 1))
