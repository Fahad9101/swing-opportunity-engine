from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v10.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()
old = '''            if period is None:\n                period = section_period\n            if period is None and (explicit_forward or local_action is not GuidanceAction.NONE or _action(segment) is not GuidanceAction.NONE):\n                period = _document_heading_period(text, segment, clause, anchor, mention)\n'''
new = '''            if period is None:\n                period = section_period\n            directional_section = {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM}\n            if period is None and (local_action in directional_section or _action(segment) in directional_section):\n                period = _document_heading_period(text, segment, clause, anchor, mention)\n'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"narrow document heading recovery: expected one match, found {count}")
path.write_text(text.replace(old, new, 1))
