from pathlib import Path

# Apply the validated v4 repair batch first.
import phase_1_1e_semantic_repair_v4  # noqa: F401,E402

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()
old = '''    marker_context = before[max(0, latest_actual.start() - 80):latest_actual.end()]\n    if re.search(r"\\b(?:guidance|outlook|forecast)\\b", marker_context, re.I):\n        return False\n    after_actual = before[latest_actual.end():]\n'''
new = '''    after_actual = before[latest_actual.end():]\n'''
if text.count(old) != 1:
    raise RuntimeError(f"historical-result refinement: expected one match, found {text.count(old)}")
path.write_text(text.replace(old, new, 1))
