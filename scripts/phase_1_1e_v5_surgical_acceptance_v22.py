from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v21.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()

old = '''_SECTION_FULL_YEAR_HEADINGS = (\n    re.compile(r"(?:^|[.;:•])\\s*(?:initial\\s+|updated\\s+|revised\\s+|increasing\\s+|raising\\s+)?full[- ]year\\s+(20\\d{2})(?:\\s+(?:guidance|outlook))?\\b", re.I),\n    re.compile(r"(?:^|[.;:•])\\s*fiscal\\s+(20\\d{2})\\s+full[- ]year\\s+(?:guidance|outlook)\\b", re.I),\n    re.compile(r"(?:^|[.;:•])\\s*(?:FY|fiscal\\s+year)\\s*(20\\d{2})\\s+(?:guidance|outlook)\\b", re.I),\n)\n'''
new = '''_SECTION_FULL_YEAR_HEADINGS = (\n    re.compile(r"(?:^|[.;:•])\\s*(?:initial\\s+|updated\\s+|revised\\s+|increasing\\s+|raising\\s+)?full[- ]year\\s+(20\\d{2})(?:\\s+(?:guidance|outlook))?\\b", re.I),\n    re.compile(r"(?:^|[.;:•])\\s*fiscal\\s+(20\\d{2})\\s+full[- ]year\\s+(?:guidance|outlook)\\b", re.I),\n    re.compile(r"(?:^|[.;:•])\\s*(?:FY|fiscal\\s+year)\\s*(20\\d{2})\\s+(?:guidance|outlook)\\b", re.I),\n    re.compile(r"(?:^|[.;:•])\\s*(20\\d{2})\\s+(?:annual|financial)\\s+(?:guidance|outlook)(?:\\s+update)?\\b", re.I),\n)\n'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"v22 strict annual section heading grammar: expected one match, found {count}")
path.write_text(text.replace(old, new, 1))

# Population-derived CLS regression: the annual section heading owns the FCF
# bullet; the trailing Q3 reference must not steal its period.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_annual_outlook_section_owns_fcf_before_trailing_q3_reference_v22():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CLSV22",
        "2025 Annual Outlook Update • Non-GAAP free cash flow of $400 million (previous outlook $350 million). Our Q3 2025 Guidance and 2025 Annual Outlook Update assume current conditions.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    current = [f for f in fcf if f.role.value == "CURRENT" and f.low == 400.0]
    prior = [f for f in fcf if f.role.value == "QUOTED_PRIOR" and f.low == 350.0]
    assert current, [(f.role.value, f.fiscal_period, f.low, f.high) for f in fcf]
    assert all(f.fiscal_period == "FY2025" for f in current), [(f.fiscal_period, f.low, f.high) for f in current]
    assert prior, [(f.role.value, f.fiscal_period, f.low, f.high) for f in fcf]
    assert all(f.fiscal_period == "FY2025" for f in prior), [(f.fiscal_period, f.low, f.high) for f in prior]
    assert not any(f.fiscal_period == "Q3FY2025" and f.low in {350.0, 400.0} for f in fcf)
''')
