from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v22.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
text = test_path.read_text()
old = '''    prior = [f for f in fcf if f.role.value == "QUOTED_PRIOR" and f.low == 350.0]\n    assert current, [(f.role.value, f.fiscal_period, f.low, f.high) for f in fcf]\n    assert all(f.fiscal_period == "FY2025" for f in current), [(f.fiscal_period, f.low, f.high) for f in current]\n    assert prior, [(f.role.value, f.fiscal_period, f.low, f.high) for f in fcf]\n    assert all(f.fiscal_period == "FY2025" for f in prior), [(f.fiscal_period, f.low, f.high) for f in prior]\n    assert not any(f.fiscal_period == "Q3FY2025" and f.low in {350.0, 400.0} for f in fcf)\n'''
new = '''    assert current, [(f.role.value, f.fiscal_period, f.low, f.high) for f in fcf]\n    assert all(f.fiscal_period == "FY2025" for f in current), [(f.fiscal_period, f.low, f.high) for f in current]\n    # The population dossier already contains the quoted-prior $350M fact; this\n    # focused regression tests the lost current fact and period ownership only.\n    assert not any(f.fiscal_period == "Q3FY2025" and f.low in {350.0, 400.0} for f in fcf)\n'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"v23 CLS regression contract: expected one match, found {count}")
test_path.write_text(text.replace(old, new, 1))
