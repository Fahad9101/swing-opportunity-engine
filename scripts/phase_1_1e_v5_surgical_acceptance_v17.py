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

def _value_starts_inside_period_token_v17(clause: str, value) -> bool:
    """Reject ranges whose first numeric token is actually part of Q/FY syntax.

    Example: ``4Q24 and $164.1M`` must never become a money range ``24-164.1M``.
    """
    if value is None:
        return False
    prefix = clause[max(0, value.start - 10):value.start]
    return bool(re.search(r"(?:\b[1-4]Q|\bQ[1-4]|\bFY)\s*$", prefix, re.I))


def _local_result_actual_v17(clause: str, anchor: int, mention, value) -> bool:
    """Recognize locally-owned reported results even when nearby text mentions guidance.

    The guard is intentionally metric/value local. It avoids treating a revenue
    result as forward guidance merely because the press-release title separately
    says that EPS guidance was raised.
    """
    if value is None:
        return False
    pivot = min(anchor, value.start)
    boundaries = [
        clause.rfind("•", 0, pivot),
        clause.rfind(";", 0, pivot),
        clause.rfind(".", 0, pivot),
        clause.rfind("!", 0, pivot),
        clause.rfind("?", 0, pivot),
    ]
    left = max(boundaries)
    left = 0 if left < 0 else left + 1
    local_before = clause[left:value.start]
    local_after = clause[value.end:min(len(clause), value.end + 120)]
    local_forward = bool(_FORWARD_SIGNAL.search(local_before))

    # Result-style tails are strong evidence when the value's own local cell has
    # no forward cue. This covers ``Revenue: $X, up Y%`` and comparison language.
    if not local_forward and re.match(
        r"\s*(?:,|;)?\s*(?:(?:up|down)\s+\d+(?:\.\d+)?\s*%|"
        r"compared\s+(?:to|with)\b|versus\b|vs\.?\b)",
        local_after,
        re.I,
    ):
        return True

    # Immediate realized-result verbs/labels. ``expects to deliver`` remains
    # forward because the local forward cue prevents this branch.
    if not local_forward and re.search(
        r"\b(?:record(?:ed)?|reports?|reported|deliver(?:s|ed|ing)?|generated|"
        r"achieved|realized)\b[^.;•!?]{0,90}$",
        local_before,
        re.I,
    ):
        return True

    # A nearby Financial Results heading owns the value unless a fresh forward
    # cue appears after that heading and before this metric/value.
    wider = clause[max(0, pivot - 260):value.start]
    result_markers = list(re.finditer(r"\b(?:financial\s+results|quarterly\s+results|results)\b", wider, re.I))
    if result_markers:
        latest = result_markers[-1]
        if not _FORWARD_SIGNAL.search(wider[latest.end():]):
            return True
    return False


def _following_period_is_reference_v17(clause: str, value, period: _PeriodBinding | None) -> bool:
    """A period mentioned after a value can be a reference, not its target period."""
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


def _ambiguous_compact_multi_period_table_v17(clause: str, anchor: int, mention, value) -> bool:
    """Fail closed when one flattened compact value is preceded by Q and FY columns.

    Nested phrases such as ``Second Quarter of Fiscal Year 2026`` count only as
    a quarter, not as two competing columns.
    """
    if value is None:
        return False
    left = max(0, anchor - 220)
    right = min(len(clause), value.end + 40)
    local = clause[left:right]
    if not re.search(r"\bguidance\b", local, re.I):
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

    # The competing headers must both belong to the compact cell immediately
    # preceding the metric/value, rather than distant prose elsewhere.
    nearest_q = min(value.start - end for _, end in quarters)
    nearest_fy = min(value.start - end for _, end in full_years)
    return nearest_q <= 180 and nearest_fy <= 180

'''
if "def _value_starts_inside_period_token_v17(" not in text:
    text = replace_once(text, helper_marker, helpers + helper_marker, "insert v17 evidence guards")

# Owned/suffix values must obey the same metric-locality invariant as ordinary
# values. If the owned candidate crosses into another metric, try the ordinary
# binder once so a valid value on the correct side of the metric is preserved.
old_locality = '''            if value is not None and owned_value is None and not _value_has_local_metric_owner(clause, anchor, mention, value):\n                rejected.append({"reason": "metric_value_locality", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
new_locality = '''            if value is not None and not _value_has_local_metric_owner(clause, anchor, mention, value):\n                rebound = _bind_value(clause, mention, anchor)\n                rebound = _prefer_same_sentence_value(clause, anchor, mention, rebound)\n                rebound = _normalize_margin_level(clause, anchor, mention, rebound)\n                if rebound is not None and rebound != value and _value_has_local_metric_owner(clause, anchor, mention, rebound):\n                    value = rebound\n                    owned_value = None\n                else:\n                    rejected.append({"reason": "metric_value_locality", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if value is not None and _value_starts_inside_period_token_v17(clause, value):\n                rejected.append({"reason": "period_token_numeric_fragment", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if _ambiguous_compact_multi_period_table_v17(clause, anchor, mention, value):\n                rejected.append({"reason": "ambiguous_compact_multi_period_table", "metric": mention.metric.value, "value_text": value.text if value is not None else None, "evidence": clause[:500]}); continue\n'''
text = replace_once(text, old_locality, new_locality, "v17 enforce locality for owned values")

old_historical = '''            if value is not None and (_value_is_historical_actual(clause, anchor, value) or _value_precedes_forward_heading(clause, anchor, value) or _local_preliminary_actual(clause, anchor, mention, value)):\n                rejected.append({"reason": "historical_actual", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
new_historical = '''            if value is not None and (_value_is_historical_actual(clause, anchor, value) or _value_precedes_forward_heading(clause, anchor, value) or _local_preliminary_actual(clause, anchor, mention, value) or _local_result_actual_v17(clause, anchor, mention, value)):\n                rejected.append({"reason": "historical_actual", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
text = replace_once(text, old_historical, new_historical, "v17 result-local actual guard")

old_period_guard = '''            compact_forward_period_owned = _compact_forward_period_is_owned(clause, compact_forward_value, period)\n            if period is not None and period is not direct_period and not compact_forward_period_owned and (\n                _selected_following_period_crosses_sentence(clause, anchor, mention, value, period)\n                or _following_period_is_new_outlook_heading(clause, anchor, mention, value, period)\n            ):\n                period = None\n'''
new_period_guard = '''            compact_forward_period_owned = _compact_forward_period_is_owned(clause, compact_forward_value, period)\n            if period is not None and period is not direct_period and not compact_forward_period_owned and (\n                _selected_following_period_crosses_sentence(clause, anchor, mention, value, period)\n                or _following_period_is_new_outlook_heading(clause, anchor, mention, value, period)\n                or _following_period_is_reference_v17(clause, value, period)\n            ):\n                period = None\n'''
text = replace_once(text, old_period_guard, new_period_guard, "v17 following reference period guard")

path.write_text(text)

# Population-derived regressions. These target generic evidence mechanics, not
# ticker-specific production branches.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_suffix_owned_revenue_range_cannot_be_stolen_by_eps_v17():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "STRL17",
        "Full Year 2025 Guidance. Revenue of $2.00 to $2.15 billion EPS of $6.75 to $7.25.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps"]
    assert not any((f.low, f.high) == (2.0, 2.15) for f in eps), [(f.low, f.high, f.fiscal_period) for f in eps]
    assert any((f.low, f.high) == (6.75, 7.25) for f in eps), [(f.low, f.high, f.fiscal_period) for f in eps]


def test_eps_value_cannot_be_stolen_by_fcf_even_when_owned_path_exists_v17():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPE17",
        "Fiscal 2026 Full Year Outlook. Free cash flow guidance remains higher. The company had expected to generate at least $3.00 in non-GAAP diluted net EPS.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert not any(f.low == 3.0 for f in fcf), [(f.low, f.high, f.fiscal_period) for f in fcf]


def test_quarter_token_digits_cannot_start_money_range_v17():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "IOVA17",
        "2025 guidance follows prior results. Total Product Revenue of $73.7M in 4Q24 and $164.1M in FY24.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert not any(f.low == 24.0 and f.high == 164.1 for f in revenue), [(f.low, f.high, f.fiscal_period) for f in revenue]


def test_financial_results_revenue_is_actual_despite_nearby_outlook_v17():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEACT17",
        "Higher outlook for fiscal 2026 and fiscal 2027. Third Quarter Fiscal 2026 Financial Results • Revenue: $12.2 billion, up 34% year-over-year. Fiscal 2027 revenue outlook is $13.0 billion.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert not any(f.low == 12.2 for f in revenue), [(f.low, f.high, f.fiscal_period) for f in revenue]


def test_record_revenue_is_actual_not_forward_guidance_v17():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEREC17",
        "Higher outlook for fiscal 2026 and fiscal 2027 - Record revenue of $12.2 billion, up 34% year-over-year.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert not any(f.low == 12.2 for f in revenue), [(f.low, f.high, f.fiscal_period) for f in revenue]


def test_following_conference_call_quarter_cannot_steal_annual_eps_value_v17():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "WAB17",
        "Adjusted EPS guidance is $8.35 to $8.95. First Quarter 2025 Conference Call.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps" and f.low == 8.35]
    assert not any(f.fiscal_period == "Q1FY2025" for f in eps), [(f.low, f.high, f.fiscal_period) for f in eps]


def test_reference_quarter_in_unchanged_from_phrase_cannot_own_value_v17():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETAREF17",
        "Revenue guidance remains $1,289 million to $1,292 million, unchanged from the third quarter 2025 earnings release.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 1289.0]
    assert not any(f.fiscal_period == "Q3FY2025" for f in revenue), [(f.low, f.high, f.fiscal_period) for f in revenue]


def test_flattened_q1_and_fy_guidance_columns_fail_closed_v17():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ATI17",
        "Current Guidance Q1 2026 Fiscal Year 2026 Adjusted EBITDA (b) $216M - $226M.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert not any((f.low, f.high) == (216.0, 226.0) for f in ebitda), [(f.low, f.high, f.fiscal_period) for f in ebitda]


def test_nested_quarter_of_fiscal_year_is_not_false_multi_period_table_v17():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "JBL17",
        "Second Quarter of Fiscal Year 2026 Outlook: Net revenue $7.5 billion to $8.0 billion.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert any(f.fiscal_period == "Q2FY2026" and f.low == 7.5 for f in revenue), [(f.low, f.high, f.fiscal_period) for f in revenue]


def test_strl_compact_trailing_fy_ebitda_remains_valid_v17():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "STRLKEEP17",
        "Net Income of $222 million to $239 million • Diluted EPS of $7.15 to $7.65 • EBITDA (1) of $381 million to $403 million Full Year 2025 Adjusted Guidance",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert any(f.fiscal_period == "FY2025" and (f.low, f.high) == (381.0, 403.0) for f in ebitda), [(f.low, f.high, f.fiscal_period) for f in ebitda]
''')
