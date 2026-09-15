from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v19.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
text = test_path.read_text()
old = 'Full Year 2025 Guidance Revenue $2.00 to $2.15 billion EPS $6.75 to $7.25.'
new = 'Full Year 2025 Guidance Revenue of $2.00 to $2.15 billion EPS of $6.75 to $7.25.'
count = text.count(old)
if count != 1:
    raise RuntimeError(f"v20 compact regression fixture: expected one match, found {count}")
test_path.write_text(text.replace(old, new, 1))
