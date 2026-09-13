from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v29.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()

old = '''        if re.search(
            r"\\b(?:had|previously)\\s+(?:expected|projected|forecast|guided|anticipated)\\b",
            bridge,
            re.I,
        ):
            return "current_value_crosses_historical_expectation"
'''
new = '''        historical = re.search(
            r"\\b(?:had|previously)\\s+(?:expected|projected|forecast|guided|anticipated)\\b",
            bridge,
            re.I,
        )
        if historical is not None:
            after_historical = bridge[historical.end():]
            if not re.search(r"\\b(?:now|currently|today)\\b", after_historical, re.I):
                return "current_value_crosses_historical_expectation"
'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"v30 previous-now exemption: expected one match, found {count}")
path.write_text(text.replace(old, new, 1))

# Explicit previous -> now language must retain both roles. The repository also
# has a pre-existing consolidation test for this invariant; this focused test
# keeps the v29 semantic filter itself from regressing it later.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_previous_then_now_pair_survives_historical_crossing_guard_v30():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "PREVNOW30",
        "Fiscal 2026 Revenue guidance was previously expected at $480 million and is now expected at $500 million.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert any(f.role.value == "CURRENT" and f.low == 500.0 for f in revenue), [(f.role.value, f.low) for f in revenue]
    assert any(f.role.value == "QUOTED_PRIOR" and f.low == 480.0 for f in revenue), [(f.role.value, f.low) for f in revenue]
''')
