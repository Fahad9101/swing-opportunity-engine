from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v12.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()

old = '''            direct_period = _direct_guidance_period(clause, anchor, mention)\n            period = direct_period or _canonical_period_binding(clause, anchor, mention)\n            section_period = _nearest_section_heading_period(segment, clause, anchor, mention)\n            if period is not None and direct_period is None and (\n                _selected_following_period_crosses_sentence(clause, anchor, mention, value, period)\n                or _following_period_is_new_outlook_heading(clause, anchor, mention, value, period)\n            ):\n                period = None\n'''
new = '''            canonical_period = _canonical_period_binding(clause, anchor, mention)\n            direct_period = _direct_guidance_period(clause, anchor, mention)\n            period = canonical_period\n            # A direct metric/year guidance phrase may override only an earlier\n            # competing period. This repairs result-period bleed into later\n            # guidance (e.g. Q1-2024 results -> 2025 revenue guidance) without\n            # stealing a later, more-specific quarter or forward-year period.\n            if direct_period is not None and (canonical_period is None or canonical_period.end <= direct_period.start):\n                period = direct_period\n            section_period = _nearest_section_heading_period(segment, clause, anchor, mention)\n            if period is not None and period is not direct_period and (\n                _selected_following_period_crosses_sentence(clause, anchor, mention, value, period)\n                or _following_period_is_new_outlook_heading(clause, anchor, mention, value, period)\n            ):\n                period = None\n'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"narrow direct period precedence: expected one match, found {count}")
path.write_text(text.replace(old, new, 1))

# Population-regression guards for the three tickers v12 reintroduced.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_direct_full_year_phrase_does_not_steal_later_quarter_period_v13():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ALKTV13",
        "2025 revenue guidance remains $443 million to $447 million. Second Quarter 2025 Outlook: revenue $109 million to $110.5 million.",
    ))
    quarter = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 109.0]
    assert quarter
    assert all(f.fiscal_period == "Q2FY2025" for f in quarter), [(f.fiscal_period, f.low, f.high) for f in quarter]


def test_direct_fy26_phrase_does_not_steal_later_fy27_period_v13():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEV13",
        "Fiscal 2026 revenue guidance is $11.5 billion to $12.1 billion. Fiscal 2027 Outlook: revenue is expected to be $12.2 billion.",
    ))
    forward = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 12.2]
    assert forward
    assert all(f.fiscal_period == "FY2027" for f in forward), [(f.fiscal_period, f.low, f.high) for f in forward]


def test_direct_full_year_phrase_does_not_steal_q2fy26_period_v13():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETAV13",
        "2026 revenue guidance is $1.779 billion to $1.792 billion. Q2 FY2026 Outlook: revenue $419 million to $422 million.",
    ))
    quarter = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 419.0]
    assert quarter
    assert all(f.fiscal_period == "Q2FY2026" for f in quarter), [(f.fiscal_period, f.low, f.high) for f in quarter]
''')
