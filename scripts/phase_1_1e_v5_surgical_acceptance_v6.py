from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v5.py")
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
_DOCUMENT_SECTION_HEADINGS = (
    (re.compile(r"\bfiscal\s+(20\d{2})\s+full[- ]year\s+(?:guidance|outlook)\b", re.I), "FY"),
    (re.compile(r"\bfull[- ]year\s+(20\d{2})(?:\s+(?:guidance|outlook))?\b", re.I), "FY"),
    (re.compile(r"\b(?:FY|fiscal\s+year)\s*(20\d{2})\s+(?:guidance|outlook)\b", re.I), "FY"),
    (re.compile(r"\bfiscal\s+(20\d{2})\s+(first|second|third|fourth)\s+quarter\s+(?:guidance|outlook)\b", re.I), "QY"),
    (re.compile(r"\b(first|second|third|fourth)\s+quarter\s+(20\d{2})(?:\s+(?:guidance|outlook))?\b", re.I), "QW"),
)


def _document_heading_period(text: str, segment: str, clause: str, anchor: int, mention) -> _PeriodBinding | None:
    flat = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    needle = re.sub(r"\s+", " ", segment).strip()
    clause_start = segment.find(clause)
    if not needle or clause_start < 0:
        return None
    starts: list[int] = []
    pos = 0
    while len(starts) < 8:
        found = flat.find(needle, pos)
        if found < 0:
            break
        starts.append(found)
        pos = found + 1
    if not starts:
        return None

    resolved: list[_PeriodBinding] = []
    quarter_map = {"first": "1", "second": "2", "third": "3", "fourth": "4"}
    for segment_start in starts:
        metric_abs = segment_start + clause_start + anchor
        window_start = max(0, metric_abs - 750)
        prefix = flat[window_start:metric_abs]
        headings: list[tuple[int, _PeriodBinding]] = []
        for pattern, kind in _DOCUMENT_SECTION_HEADINGS:
            for match in pattern.finditer(prefix):
                absolute_start = window_start + match.start()
                absolute_end = window_start + match.end()
                if kind == "FY":
                    year = _normalize_year(match.group(1))
                    binding = _PeriodBinding(f"FY{year}", GuidancePeriodKind.FULL_YEAR, match.group(0), absolute_start, absolute_end)
                elif kind == "QY":
                    year = _normalize_year(match.group(1))
                    q = quarter_map[match.group(2).lower()]
                    binding = _PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), absolute_start, absolute_end)
                else:
                    q = quarter_map[match.group(1).lower()]
                    year = _normalize_year(match.group(2))
                    binding = _PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), absolute_start, absolute_end)
                headings.append((absolute_end, binding))
        if not headings:
            continue
        headings.sort(key=lambda item: item[0], reverse=True)
        nearest = headings[0][1]
        if metric_abs - nearest.end > 750:
            continue
        resolved.append(nearest)
    periods = {item.period for item in resolved}
    if len(periods) != 1:
        return None
    return resolved[0]


def _metric_value_crosses_sentence(clause: str, anchor: int, mention, value) -> bool:
    if value is None:
        return False
    metric_start = anchor
    metric_end = anchor + len(mention.text)
    if value.start >= metric_end:
        between = clause[metric_end:value.start]
    elif value.end <= metric_start:
        between = clause[value.end:metric_start]
    else:
        return False
    return bool(re.search(r"(?<!\d)\.(?!\d)(?=\s|$)|[!?•]", between))


def _money_metric_margin_percent(clause: str, mention, value) -> bool:
    if value is None or value.unit is not GuidanceUnit.PERCENT:
        return False
    if mention.metric not in {GuidanceMetric.REVENUE, GuidanceMetric.EBITDA, GuidanceMetric.FCF}:
        return False
    before = clause[max(0, value.start - 65):value.start]
    return bool(re.search(r"\bmargin(?:\s+(?:of|at))?\s*$", before, re.I))

'''
if "def _document_heading_period(" not in text:
    text = replace_once(text, helper_marker, "\n" + helper + helper_marker.lstrip("\n"), "insert v6 helpers")

old_delta_window = '    before = clause[max(0, value.start - 70):value.start]\n'
new_delta_window = '    before = clause[max(0, value.start - 140):value.start]\n'
text = replace_once(text, old_delta_window, new_delta_window, "widen delta lookback")

old_delta_return = '''    return bool(\n        re.search(\n            r"\\b(?:rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|boost(?:s|ed|ing)?|up)\\b"\n            r"[^.;]{0,55}\\bby\\s*$",\n            before,\n            re.I,\n        )\n    )\n'''
new_delta_return = '''    return bool(\n        re.search(\n            r"\\b(?:rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|boost(?:s|ed|ing)?)\\b"\n            r"[^.;]{0,120}\\bby\\s*$",\n            before,\n            re.I,\n        )\n        or re.search(r"\\b(?:up|down)\\s*$", before, re.I)\n    )\n'''
text = replace_once(text, old_delta_return, new_delta_return, "strengthen delta guard")

old_reversed_block = '''            if value is not None and value.low > value.high:\n                rejected.append({"reason": "invalid_reversed_range", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if _value_is_guidance_delta_not_level(clause, value):\n                rejected.append({"reason": "guidance_delta_not_absolute_level", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
new_reversed_block = '''            if value is not None and value.low > value.high:\n                rejected.append({"reason": "invalid_reversed_range", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if _value_is_guidance_delta_not_level(clause, value):\n                rejected.append({"reason": "guidance_delta_not_absolute_level", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if _metric_value_crosses_sentence(clause, anchor, mention, value):\n                rejected.append({"reason": "metric_value_cross_sentence", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if _money_metric_margin_percent(clause, mention, value):\n                rejected.append({"reason": "metric_margin_not_metric_level", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
text = replace_once(text, old_reversed_block, new_reversed_block, "v6 value guards")

old_period = '''            period = _canonical_period_binding(clause, anchor, mention)\n            section_period = _nearest_section_heading_period(segment, clause, anchor, mention)\n            if period is None:\n                period = section_period\n            elif section_period is not None and _selected_following_period_crosses_sentence(clause, anchor, mention, value, period):\n                period = section_period\n            if period is None and role is GuidanceFactRole.QUOTED_PRIOR:\n                period = _unique_explicit_period_from_segment(segment)\n            if period is None:\n                rejected.append({"reason": "ambiguous_or_missing_period", "metric": mention.metric.value, "evidence": clause[:500]}); continue\n'''
new_period = '''            period = _canonical_period_binding(clause, anchor, mention)\n            section_period = _nearest_section_heading_period(segment, clause, anchor, mention)\n            if period is not None and _selected_following_period_crosses_sentence(clause, anchor, mention, value, period):\n                period = None\n            if period is None:\n                period = section_period\n            directional_section = {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM}\n            if period is None and (local_action in directional_section or segment_action in directional_section):\n                period = _document_heading_period(text, segment, clause, anchor, mention)\n            if period is None and role is GuidanceFactRole.QUOTED_PRIOR:\n                period = _unique_explicit_period_from_segment(segment)\n            if period is None:\n                rejected.append({"reason": "ambiguous_or_missing_period", "metric": mention.metric.value, "evidence": clause[:500]}); continue\n'''
text = replace_once(text, old_period, new_period, "v6 document heading period recovery")

path.write_text(text)

test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_cross_sentence_eps_value_cannot_bind_to_fcf_v6():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPECROSS",
        "Fiscal 2026 Full Year Outlook. HPE is raising its free cash flow guidance and now expects free cash flow to be at least $3.5 billion. The updated FY26 outlook ranges for non-GAAP diluted net EPS and free cash flow are higher than projected. The company had expected to generate at least $3.00 in non-GAAP diluted net EPS.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert any(f.fiscal_period == "FY2026" and f.low == 3.5 for f in fcf), [(f.fiscal_period, f.low, f.high, f.unit.value, f.explicit_action.value) for f in fcf]
    assert not any(f.low == 3.0 for f in fcf)


def test_following_fy27_heading_cannot_capture_fy26_fcf_v6():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEFOLLOW",
        "Fiscal 2026 Full Year Outlook. HPE is raising its free cash flow guidance and now expects free cash flow to be at least $3.75 billion. Fiscal 2027 Outlook Framework. The company is raising its growth framework for FY27 and expects free cash flow to be at least $5.0 billion.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert any(f.fiscal_period == "FY2026" and f.low == 3.75 for f in fcf), [(f.fiscal_period, f.low, f.high, f.unit.value, f.explicit_action.value) for f in fcf]
    assert not any(f.fiscal_period == "FY2027" and f.low == 3.75 for f in fcf)


def test_money_metric_margin_percent_is_not_metric_growth_v6():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETAMARGIN",
        "Full Year 2026. Increasing free cash flow guidance to a range of $254.8 million to $255.8 million, up $20.3 million at the midpoint from prior guidance of $235.0 million. The revised guidance represents year-over-year growth of 55% and a free cash flow margin of 14.0% to 14.1%.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert any((f.low, f.high) == (254.8, 255.8) for f in fcf)
    assert not any(f.unit.value == "PERCENT" and f.low == 14.0 for f in fcf)


def test_long_lookback_midpoint_delta_is_not_revenue_level_v6():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETADELTA2",
        "After raising the midpoint of our 2026 revenue guidance last quarter by $25 million, we are again raising it by $30 million, representing growth of 37%.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert not any(f.low in {25.0, 30.0} for f in revenue)
''')
