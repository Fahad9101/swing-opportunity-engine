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


# Narrow section-period fallback. This does not alter the existing period scorer.
# It is used only when the local clause has no safe period, or when a following
# period heading would have to cross a sentence boundary after the bound value.
helper_marker = "\ndef _ambiguous_parallel_period_table(clause: str) -> bool:\n"
helper = r'''
def _section_period_binding(segment: str, clause: str, anchor: int, mention) -> _PeriodBinding | None:
    clause_start = segment.find(clause)
    if clause_start < 0:
        return None
    absolute_anchor = clause_start + anchor
    candidates: list[tuple[int, int, _PeriodBinding]] = []

    def add(binding: _PeriodBinding, priority: int) -> None:
        if binding.end > absolute_anchor:
            return
        distance = absolute_anchor - binding.end
        if distance > 900:
            return
        candidates.append((distance, priority, binding))

    for pattern in _CANONICAL_FULL_YEAR:
        for match in pattern.finditer(segment):
            year = _normalize_year(match.group(1))
            add(_PeriodBinding(f"FY{year}", GuidancePeriodKind.FULL_YEAR, match.group(0), match.start(), match.end()), 1)

    for pattern in _CANONICAL_QUARTER:
        for match in pattern.finditer(segment):
            token = match.group(1)
            q = token if token.isdigit() else _QUARTER_WORD[token.lower()]
            year = _normalize_year(match.group(2))
            add(_PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), match.start(), match.end()), 0)

    fiscal_year_first_quarter = re.compile(
        r"\bfiscal(?:\s+year)?\s*(20\d{2})\s+(first|second|third|fourth)\s+quarter\b",
        re.I,
    )
    for match in fiscal_year_first_quarter.finditer(segment):
        year = _normalize_year(match.group(1))
        q = _QUARTER_WORD[match.group(2).lower()]
        add(_PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), match.start(), match.end()), 0)

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], -item[2].end))
    nearest_distance = candidates[0][0]
    nearest = [item for item in candidates if item[0] == nearest_distance]
    nearest.sort(key=lambda item: item[1])
    best_priority = nearest[0][1]
    best = [item for item in nearest if item[1] == best_priority]
    periods = {item[2].period for item in best}
    return best[0][2] if len(periods) == 1 else None


def _following_period_crosses_sentence_boundary(clause: str, anchor: int, mention, value, period: _PeriodBinding | None) -> bool:
    if period is None or period.start <= anchor:
        return False
    start = anchor + len(mention.text)
    if value is not None:
        start = max(start, value.end)
    if period.start <= start:
        return False
    between = clause[start:period.start]
    return bool(re.search(r"(?<!\d)\.(?!\d)|[!?•]", between))


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
    if rebound.start < mention_end and value.start >= mention_end:
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

'''
if helper.strip() not in text:
    text = replace_once(text, helper_marker, "\n" + helper + helper_marker.lstrip("\n"), "insert v4 helpers")

old_values = '''            value = owned_value or _bind_value(clause, mention, anchor)\n            explicit_prior = previous_now_prior or directional_prior\n'''
new_values = '''            value = owned_value or _bind_value(clause, mention, anchor)\n            value = _prefer_same_sentence_value(clause, anchor, mention, value)\n            explicit_prior = previous_now_prior or directional_prior\n'''
text = replace_once(text, old_values, new_values, "same-sentence value preference")

old_historical = '''            if value is not None and _value_is_historical_actual(clause, anchor, value):\n                rejected.append({"reason": "historical_actual", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
new_historical = '''            if value is not None and (_value_is_historical_actual(clause, anchor, value) or _value_precedes_forward_heading(clause, anchor, value)):\n                rejected.append({"reason": "historical_actual", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
text = replace_once(text, old_historical, new_historical, "forward-heading actual guard")

old_period = '''            period = _canonical_period_binding(clause, anchor, mention)\n            if period is None and role is GuidanceFactRole.QUOTED_PRIOR:\n                period = _unique_explicit_period_from_segment(segment)\n            if period is None:\n                rejected.append({"reason": "ambiguous_or_missing_period", "metric": mention.metric.value, "evidence": clause[:500]}); continue\n'''
new_period = '''            period = _canonical_period_binding(clause, anchor, mention)\n            if _following_period_crosses_sentence_boundary(clause, anchor, mention, value, period):\n                period = None\n            if period is None:\n                period = _section_period_binding(segment, clause, anchor, mention)\n            if period is None and role is GuidanceFactRole.QUOTED_PRIOR:\n                period = _unique_explicit_period_from_segment(segment)\n            if period is None:\n                rejected.append({"reason": "ambiguous_or_missing_period", "metric": mention.metric.value, "evidence": clause[:500]}); continue\n'''
text = replace_once(text, old_period, new_period, "section period fallback")

path.write_text(text)

# Add regressions for the three remaining repair mechanisms.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_same_sentence_value_wins_over_later_metric_value():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPELIKE",
        "Fiscal 2026 Full Year Outlook. HPE is raising its free cash flow guidance and now expects free cash flow to be at least $3.5 billion. The company had expected to generate at least $3.00 in non-GAAP diluted net EPS and more than $3.5 billion in free cash flow by FY28.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert fcf
    assert not any(f.low == 3.0 and f.unit.value == "USD" for f in fcf)


def test_full_year_section_heading_is_inherited_by_guidance_bullet():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETALIKE",
        "Increasing 2026 Guidance. Full Year 2026 • Increasing revenue guidance to a range of $1,811 million to $1,824 million. • Increasing free cash flow guidance to a range of $254.8 million to $255.8 million, up $20.3 million at the midpoint from the prior guidance of $235.0 million.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf" and f.fiscal_period == "FY2026"]
    assert any((f.low, f.high) == (254.8, 255.8) for f in fcf)


def test_following_period_heading_does_not_steal_prior_sentence_guidance():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEPERIOD",
        "Fiscal 2026 Full Year Outlook. HPE is raising its free cash flow guidance and now expects free cash flow to be at least $3.75 billion. Fiscal 2027 Outlook Framework. The company expects revenue growth of 8% to 12%.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert any(f.fiscal_period == "FY2026" and f.low == 3.75 for f in fcf)
    assert not any(f.fiscal_period == "FY2027" and f.low == 3.75 for f in fcf)


def test_historical_result_before_raising_guidance_heading_is_rejected():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "SPXCLIKE",
        "Adjusted EBITDA of $102.6 million, up 11.5% Raising 2025 Guidance. We are raising our full-year 2025 guidance for Adjusted EBITDA to a range of $470 to $495 million.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda" and f.fiscal_period == "FY2025"]
    assert any((f.low, f.high) == (470.0, 495.0) for f in ebitda)
    assert not any(f.low == 102.6 and f.high == 102.6 for f in ebitda)
''')
