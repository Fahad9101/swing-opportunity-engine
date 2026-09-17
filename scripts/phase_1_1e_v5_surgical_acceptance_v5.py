from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v3.py")
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
_SECTION_FULL_YEAR_HEADINGS = (
    re.compile(r"(?:^|[.;:•])\s*(?:initial\s+|updated\s+|revised\s+|increasing\s+|raising\s+)?full[- ]year\s+(20\d{2})(?:\s+(?:guidance|outlook))?\b", re.I),
    re.compile(r"(?:^|[.;:•])\s*fiscal\s+(20\d{2})\s+full[- ]year\s+(?:guidance|outlook)\b", re.I),
    re.compile(r"(?:^|[.;:•])\s*(?:FY|fiscal\s+year)\s*(20\d{2})\s+(?:guidance|outlook)\b", re.I),
)


def _nearest_section_heading_period(segment: str, clause: str, anchor: int, mention) -> _PeriodBinding | None:
    clause_start = segment.find(clause)
    if clause_start < 0:
        return None
    absolute_anchor = clause_start + anchor
    candidates: list[_PeriodBinding] = []
    for pattern in _SECTION_FULL_YEAR_HEADINGS:
        for match in pattern.finditer(segment):
            if match.end() > absolute_anchor:
                continue
            if absolute_anchor - match.end() > 420:
                continue
            year = _normalize_year(match.group(1))
            candidates.append(
                _PeriodBinding(
                    f"FY{year}", GuidancePeriodKind.FULL_YEAR,
                    match.group(0).strip(" .;:•"), match.start(), match.end(),
                )
            )
    if not candidates:
        return None
    best = max(candidates, key=lambda item: item.end)
    between = segment[best.end:absolute_anchor]
    # Do not inherit a full-year heading across another explicit quarter/year heading.
    if re.search(
        r"\b(?:Q[1-4]\s*(?:FY)?\s*'?20\d{2}|(?:first|second|third|fourth)\s+quarter(?:\s+of)?\s+(?:fiscal(?:\s+year)?\s*)?20\d{2}|"
        r"(?:FY|fiscal(?:\s+year)?|full[- ]year)\s*'?20\d{2})\b",
        between,
        re.I,
    ):
        return None
    return best


def _selected_following_period_crosses_sentence(clause: str, anchor: int, mention, value, period: _PeriodBinding | None) -> bool:
    if period is None or period.start <= anchor:
        return False
    start = anchor + len(mention.text)
    if value is not None:
        start = max(start, value.end)
    if period.start <= start:
        return False
    return bool(re.search(r"(?<!\d)\.(?!\d)|[!?•]", clause[start:period.start]))


def _prefer_same_sentence_value(clause: str, anchor: int, mention, value):
    if value is None:
        return None
    mention_end = anchor + len(mention.text)
    tail = clause[mention_end:]
    boundary = re.search(r"(?<!\d)\.(?!\d)(?=\s|$)|[!?•]", tail)
    if boundary is None:
        return value
    sentence_end = mention_end + boundary.start()
    if value.start <= sentence_end:
        return value
    local_clause = clause[:sentence_end]
    rebound = _bind_value(local_clause, mention, anchor)
    if rebound is None:
        return value
    return rebound


def _value_precedes_forward_heading(clause: str, anchor: int, value) -> bool:
    if value is None:
        return False
    heading = re.compile(
        r"\b(?:raising|increasing|updating|updated|lowering|reducing|maintaining|reaffirming)\s+"
        r"(?:(?:full[- ]year|fiscal(?:\s+year)?|FY)\s*)?(?:20\d{2}|\d{2})?\s*"
        r"(?:guidance|outlook)\b",
        re.I,
    )
    for match in heading.finditer(clause):
        if anchor < match.start() and value.end <= match.start() and match.start() - value.end <= 140:
            return True
    return False


def _value_is_guidance_delta_not_level(clause: str, value) -> bool:
    if value is None or value.value_kind is not GuidanceValueKind.ABSOLUTE_LEVEL:
        return False
    before = clause[max(0, value.start - 70):value.start]
    # "raising the midpoint ... by $25m" and "guidance by $33m to $1.818b"
    # describe a delta, not an absolute guidance range/level.
    return bool(
        re.search(
            r"\b(?:rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|boost(?:s|ed|ing)?|up)\b"
            r"[^.;]{0,55}\bby\s*$",
            before,
            re.I,
        )
    )

'''
if "def _nearest_section_heading_period(" not in text:
    text = replace_once(text, helper_marker, "\n" + helper + helper_marker.lstrip("\n"), "insert narrow v5 helpers")

old_values = '''            value = owned_value or _bind_value(clause, mention, anchor)\n            explicit_prior = previous_now_prior or directional_prior\n'''
new_values = '''            value = owned_value or _bind_value(clause, mention, anchor)\n            value = _prefer_same_sentence_value(clause, anchor, mention, value)\n            explicit_prior = previous_now_prior or directional_prior\n'''
text = replace_once(text, old_values, new_values, "same-sentence value preference")

old_reversed = '''            if value is not None and value.low > value.high:\n                rejected.append({"reason": "invalid_reversed_range", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
new_reversed = '''            if value is not None and value.low > value.high:\n                rejected.append({"reason": "invalid_reversed_range", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if _value_is_guidance_delta_not_level(clause, value):\n                rejected.append({"reason": "guidance_delta_not_absolute_level", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
text = replace_once(text, old_reversed, new_reversed, "guidance delta guard")

old_historical = '''            if value is not None and _value_is_historical_actual(clause, anchor, value):\n                rejected.append({"reason": "historical_actual", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
new_historical = '''            if value is not None and (_value_is_historical_actual(clause, anchor, value) or _value_precedes_forward_heading(clause, anchor, value)):\n                rejected.append({"reason": "historical_actual", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
text = replace_once(text, old_historical, new_historical, "forward-heading actual guard")

old_period = '''            period = _canonical_period_binding(clause, anchor, mention)\n            if period is None and role is GuidanceFactRole.QUOTED_PRIOR:\n                period = _unique_explicit_period_from_segment(segment)\n            if period is None:\n                rejected.append({"reason": "ambiguous_or_missing_period", "metric": mention.metric.value, "evidence": clause[:500]}); continue\n'''
new_period = '''            period = _canonical_period_binding(clause, anchor, mention)\n            section_period = _nearest_section_heading_period(segment, clause, anchor, mention)\n            if period is None:\n                period = section_period\n            elif section_period is not None and _selected_following_period_crosses_sentence(clause, anchor, mention, value, period):\n                period = section_period\n            if period is None and role is GuidanceFactRole.QUOTED_PRIOR:\n                period = _unique_explicit_period_from_segment(segment)\n            if period is None:\n                rejected.append({"reason": "ambiguous_or_missing_period", "metric": mention.metric.value, "evidence": clause[:500]}); continue\n'''
text = replace_once(text, old_period, new_period, "heading-only period inheritance")

path.write_text(text)

# Focused regressions for the narrow v5-only additions.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_same_sentence_value_wins_over_later_metric_value_v5():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPELIKE",
        "Fiscal 2026 Full Year Outlook. HPE is raising its free cash flow guidance and now expects free cash flow to be at least $3.5 billion. The company had expected to generate at least $3.00 in non-GAAP diluted net EPS and more than $3.5 billion in free cash flow by FY28.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert any(f.fiscal_period == "FY2026" and f.low == 3.5 for f in fcf)
    assert not any(f.low == 3.0 and f.unit.value == "USD" for f in fcf)


def test_heading_only_full_year_period_inheritance_v5():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETALIKE",
        "Increasing 2026 Guidance. Full Year 2026 • Increasing revenue guidance to a range of $1,811 million to $1,824 million. • Increasing free cash flow guidance to a range of $254.8 million to $255.8 million, up $20.3 million at the midpoint from the prior guidance of $235.0 million.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf" and f.fiscal_period == "FY2026"]
    assert any((f.low, f.high) == (254.8, 255.8) for f in fcf)


def test_following_outlook_heading_does_not_steal_prior_sentence_v5():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEPERIOD",
        "Fiscal 2026 Full Year Outlook. HPE is raising its free cash flow guidance and now expects free cash flow to be at least $3.75 billion. Fiscal 2027 Outlook Framework. The company expects revenue growth of 8% to 12%.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert any(f.fiscal_period == "FY2026" and f.low == 3.75 for f in fcf)
    assert not any(f.fiscal_period == "FY2027" and f.low == 3.75 for f in fcf)


def test_historical_result_before_raising_guidance_heading_is_rejected_v5():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "SPXCLIKE",
        "Adjusted EBITDA of $102.6 million, up 11.5% Raising 2025 Guidance. We are raising our full-year 2025 guidance for Adjusted EBITDA to a range of $470 to $495 million.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda" and f.fiscal_period == "FY2025"]
    assert any((f.low, f.high) == (470.0, 495.0) for f in ebitda)
    assert not any(f.low == 102.6 and f.high == 102.6 for f in ebitda)


def test_guidance_delta_is_not_misread_as_absolute_range_v5():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETADELTA",
        "Increasing full year 2026 revenue guidance by $33 million to $1,818 million at the midpoint, up from prior guidance of $1,785 million reflecting Y/Y growth of 39%.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert not any(f.low == 33.0 and f.high == 1818.0 for f in revenue)
''')
