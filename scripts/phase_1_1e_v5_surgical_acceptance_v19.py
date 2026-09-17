from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v16.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


helper_marker = "\ndef _ambiguous_parallel_period_table(clause: str) -> bool:\n"
helpers = r'''

def _value_starts_inside_period_token_v19(clause: str, value) -> bool:
    """Reject a money range whose first numeric token is actually Q/FY syntax."""
    if value is None:
        return False
    prefix = clause[max(0, value.start - 10):value.start]
    return bool(re.search(r"(?:\b[1-4]Q|\bQ[1-4]|\bFY)\s*$", prefix, re.I))


def _syntactic_cross_metric_owner_v19(clause: str, anchor: int, mention, value) -> bool:
    """Reject only explicit cross-metric ownership of the selected value.

    This deliberately avoids the broad proximity/locality rule that over-pruned
    compact guidance tables in v18. Another metric must be syntactically tied
    to the value, e.g. ``EPS of $3.00`` or ``$3.00 in non-GAAP diluted net EPS``.
    """
    if value is None:
        return False
    for owner, pattern in _VALUE_OWNER_PATTERNS:
        if owner is mention.metric:
            continue
        for match in pattern.finditer(clause):
            # Other metric immediately owns a following value.
            if match.end() <= value.start:
                bridge = clause[match.end():value.start]
                if len(bridge) <= 36 and re.fullmatch(
                    r"\s*(?:(?:of|is|at|to|range\s+of)\s*)?[:=,-]?\s*",
                    bridge,
                    re.I,
                ):
                    return True
            # Value explicitly described as belonging to another metric.
            elif match.start() >= value.end:
                bridge = clause[value.end:match.start()]
                if len(bridge) <= 48 and re.fullmatch(
                    r"\s*(?:in|for|per|of)\s+(?:(?:non[- ]?gaap|adjusted)\s+)?(?:(?:diluted|net)\s+){0,2}",
                    bridge,
                    re.I,
                ):
                    return True
    return False


def _following_period_is_reference_v19(clause: str, value, period: _PeriodBinding | None) -> bool:
    """A period after the value can be a comparison/reference, not its target."""
    if value is None or period is None or period.start <= value.end:
        return False
    bridge = clause[value.end:period.start]
    tail = clause[period.end:min(len(clause), period.end + 100)]
    if re.search(
        r"\b(?:unchanged\s+from|compared\s+(?:with|to)|from\s+(?:the\s+)?prior|"
        r"previous(?:ly)?|as\s+reported|reported|results?|reference(?:d)?)\b",
        bridge[-160:],
        re.I,
    ):
        return True
    if re.match(
        r"\s*(?:earnings\s+(?:release|materials?|presentation)|conference\s+call|"
        r"results?|release|materials?|presentation)\b",
        tail,
        re.I,
    ):
        return True
    return False


def _ambiguous_current_guidance_columns_v19(clause: str, anchor: int, mention, value) -> bool:
    """Fail closed only for flattened Current Guidance Q/FY column headers."""
    if value is None:
        return False
    left = max(0, anchor - 220)
    local = clause[left:min(len(clause), value.end + 40)]
    if not re.search(r"\bcurrent\s+guidance\b", local, re.I):
        return False

    quarters: list[tuple[int, int]] = []
    full_years: list[tuple[int, int]] = []
    for pattern in _CANONICAL_QUARTER:
        for match in pattern.finditer(local):
            if left + match.end() <= value.start:
                quarters.append((left + match.start(), left + match.end()))
    for pattern in _CANONICAL_FULL_YEAR:
        for match in pattern.finditer(local):
            if left + match.end() > value.start:
                continue
            span = (left + match.start(), left + match.end())
            if any(qs <= span[0] and span[1] <= qe for qs, qe in quarters):
                continue
            full_years.append(span)
    if not quarters or not full_years:
        return False
    nearest_q = min(value.start - end for _, end in quarters)
    nearest_fy = min(value.start - end for _, end in full_years)
    return nearest_q <= 140 and nearest_fy <= 140

'''
if "def _value_starts_inside_period_token_v19(" not in text:
    text = replace_once(text, helper_marker, helpers + helper_marker, "insert v19 evidence guards")

old_locality = '''            if value is not None and owned_value is None and not _value_has_local_metric_owner(clause, anchor, mention, value):\n                rejected.append({"reason": "metric_value_locality", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
new_locality = '''            if value is not None and _syntactic_cross_metric_owner_v19(clause, anchor, mention, value):\n                rejected.append({"reason": "syntactic_cross_metric_owner", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if value is not None and owned_value is None and not _value_has_local_metric_owner(clause, anchor, mention, value):\n                rejected.append({"reason": "metric_value_locality", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if value is not None and _value_starts_inside_period_token_v19(clause, value):\n                rejected.append({"reason": "period_token_numeric_fragment", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if _ambiguous_current_guidance_columns_v19(clause, anchor, mention, value):\n                rejected.append({"reason": "ambiguous_current_guidance_columns", "metric": mention.metric.value, "value_text": value.text if value is not None else None, "evidence": clause[:500]}); continue\n'''
text = replace_once(text, old_locality, new_locality, "v19 conservative value guards")

old_period_guard = '''            compact_forward_period_owned = _compact_forward_period_is_owned(clause, compact_forward_value, period)\n            if period is not None and period is not direct_period and not compact_forward_period_owned and (\n                _selected_following_period_crosses_sentence(clause, anchor, mention, value, period)\n                or _following_period_is_new_outlook_heading(clause, anchor, mention, value, period)\n            ):\n                period = None\n'''
new_period_guard = '''            compact_forward_period_owned = _compact_forward_period_is_owned(clause, compact_forward_value, period)\n            if period is not None and period is not direct_period and not compact_forward_period_owned and (\n                _selected_following_period_crosses_sentence(clause, anchor, mention, value, period)\n                or _following_period_is_new_outlook_heading(clause, anchor, mention, value, period)\n                or _following_period_is_reference_v19(clause, value, period)\n            ):\n                period = None\n'''
text = replace_once(text, old_period_guard, new_period_guard, "v19 reference period guard")

path.write_text(text)

# Population-derived regression guards. These test evidence mechanics only.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_eps_value_explicitly_owned_after_value_cannot_be_fcf_v19():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPE19",
        "Fiscal 2026 Full Year Outlook. Free cash flow guidance is higher than prior expectations. The company had expected to generate at least $3.00 in non-GAAP diluted net EPS.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert not any(f.low == 3.0 for f in fcf), [(f.low, f.high, f.fiscal_period) for f in fcf]


def test_compact_revenue_then_eps_keeps_each_own_value_v19():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "STRL19",
        "Full Year 2025 Guidance Revenue $2.00 to $2.15 billion EPS $6.75 to $7.25.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    eps = [f for f in ex.facts if f.metric.value == "eps"]
    assert any((f.low, f.high) == (2.0, 2.15) for f in revenue), [(f.low, f.high) for f in revenue]
    assert any((f.low, f.high) == (6.75, 7.25) for f in eps), [(f.low, f.high) for f in eps]


def test_quarter_token_digits_cannot_start_money_range_v19():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "IOVA19",
        "2025 guidance follows prior results. Total Product Revenue of $73.7M in 4Q24 and $164.1M in FY24.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert not any(f.low == 24.0 and f.high == 164.1 for f in revenue), [(f.low, f.high, f.fiscal_period) for f in revenue]


def test_following_conference_call_quarter_cannot_steal_annual_eps_v19():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "WAB19",
        "Adjusted EPS guidance is $8.35 to $8.95. First Quarter 2025 Conference Call.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps" and f.low == 8.35]
    assert not any(f.fiscal_period == "Q1FY2025" for f in eps), [(f.low, f.high, f.fiscal_period) for f in eps]


def test_reference_quarter_cannot_own_unchanged_guidance_value_v19():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETA19",
        "Revenue guidance remains $1,289 million to $1,292 million, unchanged from the third quarter 2025 earnings release.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 1289.0]
    assert not any(f.fiscal_period == "Q3FY2025" for f in revenue), [(f.low, f.high, f.fiscal_period) for f in revenue]


def test_flattened_current_q1_and_fy_columns_fail_closed_v19():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ATI19",
        "Current Guidance Q1 2026 Fiscal Year 2026 Adjusted EBITDA (b) $216M - $226M.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert not any((f.low, f.high) == (216.0, 226.0) for f in ebitda), [(f.low, f.high, f.fiscal_period) for f in ebitda]


def test_quarter_guidance_with_growth_tail_remains_forward_v19():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "U19",
        "Q2 2026 Guidance • Strategic Revenue of $455 million to $465 million, up 29% - 32% year-over-year.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert any((f.low, f.high) == (455.0, 465.0) for f in revenue), [(f.low, f.high, f.fiscal_period) for f in revenue]
''')
