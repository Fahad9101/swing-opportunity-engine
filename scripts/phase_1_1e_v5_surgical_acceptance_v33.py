from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v32.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()

old = '''    tail = clause[value.end():]\n'''
new = '''    tail = clause[value.end:]\n'''
if text.count(old) != 1:
    raise RuntimeError(f"v33 value.end property fix: expected one match, found {text.count(old)}")
text = text.replace(old, new, 1)

old_start = '''    start = value.end() + match.start("year")\n    end = value.end() + match.end("year")\n'''
new_start = '''    start = value.end + match.start("year")\n    end = value.end + match.end("year")\n'''
if text.count(old_start) != 1:
    raise RuntimeError(f"v33 value.end offset fix: expected one match, found {text.count(old_start)}")
text = text.replace(old_start, new_start, 1)

path.write_text(text)
