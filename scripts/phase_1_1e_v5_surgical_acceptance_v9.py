from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v8.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


# Prefer a specific quarter binding over a nested generic fiscal-year token.
old_explicit = '''    if explicit:\n        preceding = [item for item in explicit if item[0] == 0 and item[2].end <= anchor]\n'''
new_explicit = '''    if explicit:\n        quarter_bindings = [item[2] for item in explicit if item[2].kind is GuidancePeriodKind.QUARTER]\n        if quarter_bindings:\n            explicit = [\n                item for item in explicit\n                if not (\n                    item[2].kind is GuidancePeriodKind.FULL_YEAR\n                    and any(q.start <= item[2].start and item[2].end <= q.end for q in quarter_bindings)\n                )\n            ]\n        preceding = [item for item in explicit if item[0] == 0 and item[2].end <= anchor]\n'''
text = replace_once(text, old_explicit, new_explicit, "quarter specificity")

# Allow a comma in phrases such as "Fourth Quarter, ending December 31, 2025".
old_qending = 'r"\\b(first|second|third|fourth)\\s+quarter\\s+ending\\s+"'
new_qending = 'r"\\b(first|second|third|fourth)\\s+quarter\\s*,?\\s*ending\\s+"'
text = replace_once(text, old_qending, new_qending, "quarter ending punctuation")

old_headings = r'''_DOCUMENT_SECTION_HEADINGS = (
    (re.compile(r"\bfiscal\s+(20\d{2})\s+full[- ]year\s+(?:guidance|outlook)\b", re.I), "FY"),
    (re.compile(r"\bfull[- ]year\s+(20\d{2})(?:\s+(?:guidance|outlook))?\b", re.I), "FY"),
    (re.compile(r"\b(?:FY|fiscal\s+year)\s*(20\d{2})\s+(?:guidance|outlook)\b", re.I), "FY"),
    (re.compile(r"\bfiscal\s+(20\d{2})\s+(first|second|third|fourth)\s+quarter\s+(?:guidance|outlook)\b", re.I), "QY"),
    (re.compile(r"\b(first|second|third|fourth)\s+quarter\s+(20\d{2})(?:\s+(?:guidance|outlook))?\b", re.I), "QW"),
)
'''
new_headings = r'''_DOCUMENT_SECTION_HEADINGS = (
    (re.compile(r"\bfiscal\s+(20\d{2})\s+full[- ]year\s+(?:guidance|outlook)\b", re.I), "FY"),
    (re.compile(r"\bfull[- ]year\s+(20\d{2})(?:\s+(?:guidance|outlook))?\b", re.I), "FY"),
    (re.compile(r"\b(?:FY|fiscal\s+year)\s*(20\d{2})\s+(?:guidance|outlook)\b", re.I), "FY"),
    (re.compile(r"\b(20\d{2})\s+(?:annual|financial)\s+(?:guidance|outlook)(?:\s+update)?\b", re.I), "FY"),
    (re.compile(r"\bfiscal\s+(20\d{2})\s+(first|second|third|fourth)\s+quarter\s+(?:guidance|outlook)\b", re.I), "QY"),
    (re.compile(r"\b(first|second|third|fourth)\s+quarter(?:\s+of)?\s+fiscal(?:\s+year)?\s+(20\d{2})(?:\s+(?:guidance|outlook))?\b", re.I), "QW"),
    (re.compile(r"\b(first|second|third|fourth)\s+quarter\s+(20\d{2})(?:\s+(?:guidance|outlook))?\b", re.I), "QW"),
    (re.compile(r"\bQ([1-4])\s*(?:FY|fiscal(?:\s+year)?)?\s*'?\s*(20\d{2})(?:\s+(?:guidance|outlook))?\b", re.I), "QN"),
)
'''
text = replace_once(text, old_headings, new_headings, "document heading grammar")

old_heading_else = '''                else:\n                    q = quarter_map[match.group(1).lower()]\n                    year = _normalize_year(match.group(2))\n                    binding = _PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), absolute_start, absolute_end)\n'''
new_heading_else = '''                else:\n                    token = match.group(1)\n                    q = token if token.isdigit() else quarter_map[token.lower()]\n                    year = _normalize_year(match.group(2))\n                    binding = _PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), absolute_start, absolute_end)\n'''
text = replace_once(text, old_heading_else, new_heading_else, "numeric quarter heading")

helper_marker = "\ndef _ambiguous_parallel_period_table(clause: str) -> bool:\n"
helper = r'''
_DIRECT_GUIDANCE_METRIC = {
    GuidanceMetric.REVENUE: r"(?:total\s+|consolidated\s+)?(?:revenue|net\s+sales)",
    GuidanceMetric.EBITDA: r"(?:(?:adjusted|non[- ]GAAP)\s+)?EBITDA",
    GuidanceMetric.FCF: r"(?:free\s+cash\s+flow|FCF)",
    GuidanceMetric.EPS: r"(?:(?:adjusted|non[- ]GAAP|GAAP)\s+)?(?:diluted\s+)?(?:EPS|earnings\s+per\s+(?:common\s+)?share)",
    GuidanceMetric.GROSS_MARGIN: r"(?:(?:adjusted|non[- ]GAAP)\s+)?gross(?:\s+profit)?\s+margin",
    GuidanceMetric.OPERATING_MARGIN: r"(?:(?:adjusted|non[- ]GAAP)\s+)?operating\s+margin",
}


def _direct_guidance_period(clause: str, anchor: int, mention) -> _PeriodBinding | None:
    metric_pattern = _DIRECT_GUIDANCE_METRIC.get(mention.metric)
    if not metric_pattern:
        return None
    left = max(0, anchor - 190)
    right = min(len(clause), anchor + len(mention.text) + 190)
    local = clause[left:right]
    candidates: list[tuple[int, _PeriodBinding]] = []
    patterns = [
        re.compile(rf"\b(20\d{{2}})\s+{metric_pattern}\s+(?:guidance|outlook)\b", re.I),
        re.compile(rf"\b(?:guidance|outlook)\s+(?:for\s+)?(?:full[- ]year\s+|fiscal(?:\s+year)?\s+)?(20\d{{2}})\b[^.;]{{0,90}}\b{metric_pattern}\b", re.I),
    ]
    for pattern in patterns:
        for match in pattern.finditer(local):
            year = _normalize_year(match.group(1))
            start, end = left + match.start(), left + match.end()
            distance = _span_gap(start, end, anchor, anchor + len(mention.text))
            candidates.append((distance, _PeriodBinding(f"FY{year}", GuidancePeriodKind.FULL_YEAR, match.group(0), start, end)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], -item[1].end))
    best_distance = candidates[0][0]
    tied = [item[1] for item in candidates if item[0] == best_distance]
    periods = {item.period for item in tied}
    return tied[0] if len(periods) == 1 else None


def _normalize_margin_level(clause: str, anchor: int, mention, value):
    if value is None or mention.metric not in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}:
        return value
    if value.unit is not GuidanceUnit.PERCENT or value.value_kind is not GuidanceValueKind.DELTA:
        return value
    metric_end = anchor + len(mention.text)
    if value.start < anchor:
        local = clause[value.start:metric_end]
    else:
        local = clause[anchor:value.end]
    # A directly stated margin percentage is a level. Keep true change language
    # ("margin expansion/increase of X%") as a delta.
    if re.search(r"\bmargin\b[^.;]{0,55}(?:approximately|about|around|of|at|between|range)?[^.;]{0,24}\d+(?:\.\d+)?\s*%", local, re.I) and not re.search(
        r"\bmargin\s+(?:increase|decrease|expansion|contraction|improvement|decline)\s+(?:of|by)\b",
        local,
        re.I,
    ):
        return _ValueBinding(value.low, value.high, value.unit, GuidanceValueKind.ABSOLUTE_LEVEL, value.text, value.start, value.end)
    return value

'''
if "def _direct_guidance_period(" not in text:
    text = replace_once(text, helper_marker, "\n" + helper + helper_marker.lstrip("\n"), "insert v9 period/margin helpers")

old_value_norm = '''            value = _prefer_same_sentence_value(clause, anchor, mention, value)\n            explicit_prior = previous_now_prior or directional_prior\n'''
new_value_norm = '''            value = _prefer_same_sentence_value(clause, anchor, mention, value)\n            value = _normalize_margin_level(clause, anchor, mention, value)\n            explicit_prior = previous_now_prior or directional_prior\n'''
text = replace_once(text, old_value_norm, new_value_norm, "margin absolute normalization")

old_period = '''            period = _canonical_period_binding(clause, anchor, mention)\n            section_period = _nearest_section_heading_period(segment, clause, anchor, mention)\n            if period is not None and _selected_following_period_crosses_sentence(clause, anchor, mention, value, period):\n                period = None\n            if period is None:\n                period = section_period\n            if period is None and (local_action in directional_section or _action(segment) in directional_section):\n                period = _document_heading_period(text, segment, clause, anchor, mention)\n            if period is None and role is GuidanceFactRole.QUOTED_PRIOR:\n                period = _unique_explicit_period_from_segment(segment)\n            if period is None:\n                rejected.append({"reason": "ambiguous_or_missing_period", "metric": mention.metric.value, "evidence": clause[:500]}); continue\n'''
new_period = '''            period = _canonical_period_binding(clause, anchor, mention)\n            section_period = _nearest_section_heading_period(segment, clause, anchor, mention)\n            if period is not None and _selected_following_period_crosses_sentence(clause, anchor, mention, value, period):\n                period = None\n            if period is None:\n                period = _direct_guidance_period(clause, anchor, mention)\n            if period is None:\n                period = section_period\n            if period is None and (explicit_forward or local_action is not GuidanceAction.NONE or _action(segment) is not GuidanceAction.NONE):\n                period = _document_heading_period(text, segment, clause, anchor, mention)\n            if period is None and role is GuidanceFactRole.QUOTED_PRIOR:\n                period = _unique_explicit_period_from_segment(segment)\n            if period is None:\n                rejected.append({"reason": "ambiguous_or_missing_period", "metric": mention.metric.value, "evidence": clause[:500]}); continue\n'''
text = replace_once(text, old_period, new_period, "v9 period recovery")

path.write_text(text)

# Add regressions for the period-specificity and valid-guidance losses found by
# the rich v5-v7 differential audit.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_nested_fiscal_year_does_not_steal_quarter_heading_v9():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "JBLQ",
        "Second Quarter of Fiscal Year 2026 Outlook: Net revenue $7.5 billion to $8.0 billion.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert any(f.fiscal_period == "Q2FY2026" and f.low == 7.5 for f in revenue)
    assert not any(f.fiscal_period == "FY2026" and f.low == 7.5 for f in revenue)


def test_direct_year_metric_guidance_beats_later_results_period_v9():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CORTY",
        "First quarter financial results were strong. We are reiterating our 2025 revenue guidance of $900 to $950 million. First quarter 2025 revenue was $157.2 million.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 900.0]
    assert any(f.fiscal_period == "FY2025" for f in revenue)
    assert not any(f.fiscal_period.startswith("Q1") for f in revenue)


def test_strict_heading_recovery_applies_to_initiated_guidance_v9():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "PWRY",
        "Full Year 2026 Guidance. Quanta expects EBITDA to range between $3.09 billion and $3.25 billion and adjusted EBITDA to range between $3.34 billion and $3.50 billion.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert any(f.fiscal_period == "FY2026" and f.low == 3.34 and f.high == 3.50 for f in ebitda)


def test_quarter_ending_with_comma_is_authoritative_v9():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "SHAKQ",
        "For the Fourth Quarter, ending December 31, 2025, the Company continues to expect total revenue of $406 million to $412 million.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert any(f.fiscal_period == "Q4FY2025" and f.low == 406.0 for f in revenue)


def test_direct_margin_percentage_is_absolute_level_v9():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "DXCMM",
        "Full Year 2025 Guidance. Non-GAAP Gross Profit Margin of approximately 62%. The reduction relative to prior guidance reflects supply dynamics.",
    ))
    margins = [f for f in ex.facts if f.metric.value == "gross_margin"]
    assert any(f.fiscal_period == "FY2025" and f.value_kind.value == "ABSOLUTE_LEVEL" for f in margins)
''')
