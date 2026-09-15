from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v6.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()
old = "local_action in directional_section or segment_action in directional_section"
new = "local_action in directional_section or _action(segment) in directional_section"
count = text.count(old)
if count != 1:
    raise RuntimeError(f"segment directional recovery: expected one match, found {count}")
path.write_text(text.replace(old, new, 1))
