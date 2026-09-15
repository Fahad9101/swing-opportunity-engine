from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v23.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()

old = '''            if absolute_anchor - match.end() > 420:\n                continue\n            year = _normalize_year(match.group(1))\n'''
new = '''            heading_distance = absolute_anchor - match.end()\n            # Flattened annual-outlook bullet lists can place the final metric\n            # slightly beyond the ordinary 420-character locality window.\n            # Extend locality only for the explicit ``YYYY Annual/Financial\n            # Guidance/Outlook`` section form; generic FY headings remain at\n            # the original 420-character boundary.\n            annual_table_heading = bool(re.search(\n                r"\\b20\\d{2}\\s+(?:annual|financial)\\s+(?:guidance|outlook)(?:\\s+update)?\\b",\n                match.group(0),\n                re.I,\n            ))\n            max_heading_distance = 650 if annual_table_heading else 420\n            if heading_distance > max_heading_distance:\n                continue\n            year = _normalize_year(match.group(1))\n'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"v24 annual section locality: expected one match, found {count}")
path.write_text(text.replace(old, new, 1))

# Boundary regression: an explicit annual section heading may own a final
# guidance bullet beyond 420 characters, while the metric itself remains
# explicitly forward-looking.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_explicit_annual_heading_can_own_late_fcf_bullet_v24():
    filler = " assumptions" * 42
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CLSV24",
        "2025 Annual Outlook Update" + filler + " non-GAAP free cash flow outlook of $400 million.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 400.0]
    assert fcf, ex.rejected_candidates
    assert all(f.fiscal_period == "FY2025" for f in fcf), [(f.fiscal_period, f.low, f.high) for f in fcf]
''')
