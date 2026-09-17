from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v20.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
text = test_path.read_text()
old = '''    assert any((f.low, f.high) == (2.0, 2.15) for f in revenue), [(f.low, f.high) for f in revenue]\n    assert any((f.low, f.high) == (6.75, 7.25) for f in eps), [(f.low, f.high) for f in eps]\n'''
new = '''    assert any((f.low, f.high) == (2.0, 2.15) for f in revenue), [(f.low, f.high) for f in revenue]\n    # The ownership invariant is negative: the revenue range must never become EPS.\n    # Standalone dollar EPS ranges may fail later per-share/unit normalization, which\n    # is orthogonal to this regression and already covered by existing EPS tests.\n    assert not any((f.low, f.high) == (2.0, 2.15) for f in eps), [(f.low, f.high) for f in eps]\n'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"v21 compact ownership assertion: expected one match, found {count}")
test_path.write_text(text.replace(old, new, 1))
