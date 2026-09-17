from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v11.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


helper_marker = "\ndef _ambiguous_parallel_period_table(clause: str) -> bool:\n"
helper = r'''
_OTHER_METRIC_OWNER_PATTERNS = {
    GuidanceMetric.REVENUE: re.compile(r"\b(?:revenue|net\s+sales|sales)\b", re.I),
    GuidanceMetric.EBITDA: re.compile(r"\b(?:adjusted\s+)?EBITDA\b", re.I),
    GuidanceMetric.FCF: re.compile(r"\b(?:free\s+cash\s+flow|FCF)\b", re.I),
    GuidanceMetric.EPS: re.compile(r"\b(?:diluted\s+)?(?:EPS|earnings\s+per\s+(?:common\s+)?share)\b", re.I),
    GuidanceMetric.GROSS_MARGIN: re.compile(r"\bgross(?:\s+profit)?\s+margin\b", re.I),
    GuidanceMetric.OPERATING_MARGIN: re.compile(r"\boperating\s+margin\b", re.I),
}


def _value_crosses_other_metric_owner(clause: str, anchor: int, mention, value) -> bool:
    if value is None or value.start >= anchor:
        return False
    between = clause[value.end:anchor]
    for metric, pattern in _OTHER_METRIC_OWNER_PATTERNS.items():
        if metric is mention.metric:
            continue
        if pattern.search(between):
            return True
    return False


def _local_preliminary_actual(clause: str, anchor: int, mention, value) -> bool:
    if value is None:
        return False
    left = max(clause.rfind("•", 0, anchor), clause.rfind(".", 0, anchor), clause.rfind(";", 0, anchor))
    left = 0 if left < 0 else left + 1
    right_candidates = [x for x in (clause.find("•", value.end), clause.find(".", value.end), clause.find(";", value.end)) if x >= 0]
    right = min(right_candidates) if right_candidates else len(clause)
    local = clause[left:right]
    return bool(
        re.search(r"\bpreliminary\s+unaudited\b", local, re.I)
        and re.search(r"\b(?:first|second|third|fourth)\s+quarter\b", local, re.I)
        and re.search(r"\b(?:revenue|net\s+sales|sales|EPS|earnings)\b", local, re.I)
    )


def _following_period_is_new_outlook_heading(clause: str, anchor: int, mention, value, period: _PeriodBinding | None) -> bool:
    if period is None or value is None or period.start <= value.end:
        return False
    between = clause[value.end:period.start]
    if between.strip(" \t\r\n:;-–—•"):
        return False
    tail = clause[period.start:min(len(clause), period.end + 45)]
    return bool(re.search(r"\b(?:outlook|guidance)\b\s*:?") .search(tail) if False else re.search(r"\b(?:outlook|guidance)\b\s*:?") )


def _period_is_presentation_footer(clause: str, period: _PeriodBinding | None) -> bool:
    if period is None:
        return False
    local = clause[max(0, period.start - 12):min(len(clause), period.end + 40)]
    return bool(re.search(r"\bearnings\s+presentation\b", local, re.I))

'''
# Correct a small construction artifact in the raw helper string before insertion.
helper = helper.replace(
    'return bool(re.search(r"\\b(?:outlook|guidance)\\b\\s*:?") .search(tail) if False else re.search(r"\\b(?:outlook|guidance)\\b\\s*:?") )',
    'return bool(re.search(r"\\b(?:outlook|guidance)\\b\\s*:?", tail, re.I))',
)
if "def _value_crosses_other_metric_owner(" not in text:
    text = replace_once(text, helper_marker, "\n" + helper + helper_marker.lstrip("\n"), "insert v12 semantic guards")

old_reversed = '''            if value is not None and value.low > value.high:\n                rejected.append({"reason": "invalid_reversed_range", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if _value_is_guidance_delta_not_level(clause, value):\n'''
new_reversed = '''            if value is not None and value.low > value.high:\n                rejected.append({"reason": "invalid_reversed_range", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if _value_crosses_other_metric_owner(clause, anchor, mention, value):\n                rejected.append({"reason": "metric_value_cross_owner", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if _value_is_guidance_delta_not_level(clause, value):\n'''
text = replace_once(text, old_reversed, new_reversed, "v12 cross-owner guard")

old_historical = '''            if value is not None and (_value_is_historical_actual(clause, anchor, value) or _value_precedes_forward_heading(clause, anchor, value)):\n                rejected.append({"reason": "historical_actual", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
new_historical = '''            if value is not None and (_value_is_historical_actual(clause, anchor, value) or _value_precedes_forward_heading(clause, anchor, value) or _local_preliminary_actual(clause, anchor, mention, value)):\n                rejected.append({"reason": "historical_actual", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
text = replace_once(text, old_historical, new_historical, "v12 local actual guard")

old_period = '''            period = _canonical_period_binding(clause, anchor, mention)\n            section_period = _nearest_section_heading_period(segment, clause, anchor, mention)\n            if period is not None and _selected_following_period_crosses_sentence(clause, anchor, mention, value, period):\n                period = None\n            if period is None:\n                period = _direct_guidance_period(clause, anchor, mention)\n            if period is None:\n                period = section_period\n'''
new_period = '''            direct_period = _direct_guidance_period(clause, anchor, mention)\n            period = direct_period or _canonical_period_binding(clause, anchor, mention)\n            section_period = _nearest_section_heading_period(segment, clause, anchor, mention)\n            if period is not None and direct_period is None and (\n                _selected_following_period_crosses_sentence(clause, anchor, mention, value, period)\n                or _following_period_is_new_outlook_heading(clause, anchor, mention, value, period)\n            ):\n                period = None\n            if period is None:\n                period = section_period\n            if _period_is_presentation_footer(clause, period):\n                period = section_period if section_period is not None and not _period_is_presentation_footer(clause, section_period) else None\n'''
text = replace_once(text, old_period, new_period, "v12 direct-period precedence")

path.write_text(text)

# Regression cases taken from the remaining v11 evidence dossier.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_direct_guidance_year_overrides_preceding_results_year_v12():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ATROV12",
        "Full year 2024 preliminary unaudited revenue was approximately $796 million. Initial 2025 revenue guidance established at $820 million to $860 million.",
    ))
    rev = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 820.0]
    assert rev
    assert all(f.fiscal_period == "FY2025" for f in rev), [(f.fiscal_period, f.low, f.high) for f in rev]


def test_results_quarter_cannot_steal_direct_guidance_year_v12():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CORTV12",
        "Revenue of $157.2 million, compared to $146.8 million in first quarter 2024. Reiterated 2025 revenue guidance of $900 to $950 million.",
    ))
    rev = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 900.0]
    assert rev
    assert all(f.fiscal_period == "FY2025" for f in rev), [(f.fiscal_period, f.low, f.high) for f in rev]


def test_compact_revenue_range_cannot_bind_to_ebitda_v12():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "KRMNV12",
        "Raised full-year 2025 guidance to: $452 - $458 million revenue: 32% YoY increase to midpoint $138.5 - $141.5 million adjusted EBITDA.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert any((f.low, f.high) == (138.5, 141.5) for f in ebitda)
    assert not any((f.low, f.high) == (452.0, 458.0) for f in ebitda)


def test_actual_eps_before_new_quarter_outlook_heading_does_not_inherit_quarter_v12():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "JBLV12",
        "Fiscal Year 2025 Outlook: Core diluted earnings per share (Non-GAAP): $9.75 First Quarter of Fiscal Year 2026 Outlook: Net revenue $7.7 billion to $8.3 billion.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps" and f.low == 9.75]
    assert not any(f.fiscal_period == "Q1FY2026" for f in eps)


def test_presentation_footer_is_not_guidance_period_v12():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "FRPTV12",
        "2027 Targets: Adjusted Gross Margin Target 48% Q3 2025 Earnings Presentation 26.",
    ))
    margins = [f for f in ex.facts if f.metric.value == "gross_margin" and f.low == 0.48]
    assert not any(f.fiscal_period == "Q3FY2025" for f in margins)
''')
