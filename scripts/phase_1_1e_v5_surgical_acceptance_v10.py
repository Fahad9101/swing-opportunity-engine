from __future__ import annotations

from pathlib import Path

V9 = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v9.py")
source = V9.read_text()
needle = '            if period is None:\\n                period = section_period\\n            if period is None and (local_action in directional_section or _action(segment) in directional_section):\\n'
replacement = '            if period is None:\\n                period = section_period\\n            directional_section = {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM}\\n            if period is None and (local_action in directional_section or _action(segment) in directional_section):\\n'
count = source.count(needle)
if count != 1:
    raise RuntimeError(f"v9 matcher repair: expected one match, found {count}")
source = source.replace(needle, replacement, 1)
exec(compile(source, str(V9), "exec"), {"__name__": "__main__", "__file__": str(V9)})
