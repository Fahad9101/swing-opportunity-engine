from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v28.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


helper_marker = "\ndef _suppress_document_fragments(facts: Iterable[TypedGuidanceFact], rejected: list[dict]) -> list[TypedGuidanceFact]:\n"
helpers = r'''
_LOCAL_FISCAL_YEAR_QUARTER_V29 = re.compile(
    r"\bFiscal(?:\s+Year)?\s+(?P<year>20\d{2})\s+"
    r"(?P<word>First|Second|Third|Fourth)\s+Quarter\b",
    re.I,
)
_LOCAL_QFY_V29 = re.compile(
    r"\bQ(?P<q>[1-4])\s*(?:FY)?\s*'?(?P<year>(?:20)?\d{2})\b",
    re.I,
)
_LOCAL_NQ_V29 = re.compile(
    r"\b(?P<q>[1-4])Q\s*'?(?P<year>(?:20)?\d{2})\b",
    re.I,
)


def _local_explicit_quarter_before_value_v29(clause: str, value) -> _PeriodBinding | None:
    """Recover only a locally explicit quarter that directly owns the value."""
    if value is None:
        return None
    candidates: list[_PeriodBinding] = []
    for match in _LOCAL_FISCAL_YEAR_QUARTER_V29.finditer(clause):
        if match.end() > value.start or value.start - match.end() > 190:
            continue
        local = clause[max(0, match.start() - 80):value.start]
        if not re.search(r"\b(?:outlook|guidance|estimat(?:e|es|ed)|expects?)\b", local, re.I):
            continue
        after_period = clause[match.end():value.start]
        if re.search(r"\bfinancial\s+results\b", after_period, re.I):
            continue
        q = _QUARTER_WORD[match.group("word").lower()]
        year = _normalize_year(match.group("year"))
        candidates.append(_PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), match.start(), match.end()))

    for pattern in (_LOCAL_QFY_V29, _LOCAL_NQ_V29):
        for match in pattern.finditer(clause):
            if match.end() > value.start or value.start - match.end() > 150:
                continue
            local = clause[max(0, match.start() - 100):value.start]
            if not re.search(r"\b(?:outlook|guidance|forecast|estimat(?:e|es|ed)|expects?)\b", local, re.I):
                continue
            q = match.group("q")
            year = _normalize_year(match.group("year"))
            candidates.append(_PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), match.start(), match.end()))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item.end)


def _semantic_alias_reason_v29(fact: TypedGuidanceFact) -> str | None:
    if not fact.provenance:
        return None
    evidence = fact.provenance[0].evidence
    clause = evidence.full_text or ""
    if not clause:
        return None

    ms, me = evidence.metric_start, evidence.metric_end
    vs, ve = evidence.value_start, evidence.value_end
    ps, pe = evidence.period_start, evidence.period_end

    if fact.metric is GuidanceMetric.EPS and ve is not None:
        if re.match(r"\s*(?:million|billion|thousand|mm|bn)\b", clause[ve:ve + 24], re.I):
            return "eps_money_scale_cross_metric"

    if fact.role is GuidanceFactRole.CURRENT and me is not None and vs is not None and vs > me:
        bridge = clause[me:vs]
        if re.search(
            r"\b(?:had|previously)\s+(?:expected|projected|forecast|guided|anticipated)\b",
            bridge,
            re.I,
        ):
            return "current_value_crosses_historical_expectation"

        fresh = list(re.finditer(
            r"\b(?:rais(?:e|es|ed|ing)|revis(?:e|es|ed|ing)|updat(?:e|es|ed|ing)|"
            r"lower(?:s|ed|ing)?|reaffirm(?:s|ed|ing)?)\b[^.;•]{0,80}"
            r"\b(?:guidance|outlook)\b",
            bridge,
            re.I,
        ))
        if fresh:
            marker = fresh[-1]
            result_side = bridge[:marker.start()]
            if len(bridge) >= 96 and re.search(r"\b(?:up|down)\s+\d+(?:\.\d+)?%\s+YoY\b", result_side, re.I):
                return "result_metric_crosses_new_guidance_row"

    if fact.metric is GuidanceMetric.REVENUE and vs is not None and ve is not None:
        before = clause[max(0, ms - 180 if ms is not None else vs - 180):vs]
        after = clause[ve:min(len(clause), ve + 100)]
        if (
            re.search(r"\brecord\s+(?:total\s+)?revenue\b", before, re.I)
            and re.match(r"\s*,?\s*(?:up|down)\s+\d+(?:\.\d+)?%", after, re.I)
        ):
            return "realized_record_revenue"
        if (
            re.search(r"\bfinancial\s+results\b", before, re.I)
            and re.match(r"\s*,?\s*(?:up|down|compared\s+(?:to|with)|versus|vs\.?)\b", after, re.I)
        ):
            return "financial_results_actual"

        if me is not None:
            bridge = clause[me:vs]
            if re.search(r"\b(?:net\s+sales|revenue)?\s*growth\s+YoY\b", bridge, re.I):
                if fact.unit in {
                    GuidanceUnit.USD,
                    GuidanceUnit.USD_THOUSAND,
                    GuidanceUnit.USD_MILLION,
                    GuidanceUnit.USD_BILLION,
                }:
                    return "growth_row_money_neighbor"

    if ve is not None and ps is not None and ps > ve:
        bridge = clause[ve:ps]
        if re.search(r"\b(?:increase|growth|decrease|decline)\b[^.;•]{0,90}\bfrom\s*$", bridge, re.I):
            return "comparison_year_as_period"
        if re.search(r"[.!?•]\s*$", bridge):
            return "following_section_period_alias"

    if pe is not None and vs is not None and pe < vs:
        bridge = clause[pe:vs]
        if re.search(
            r"(?:^|[.!?•])\s*(?:FY\s*'?\d{2,4}|Fiscal(?:\s+Year)?\s+20\d{2}|20\d{2})"
            r"[^.;•]{0,35}\b(?:guidance|outlook)\b",
            bridge,
            re.I,
        ):
            return "stale_period_before_new_outlook"

    return None


def _suppress_semantic_aliases_v29(
    facts: Iterable[TypedGuidanceFact],
    rejected: list[dict],
) -> list[TypedGuidanceFact]:
    kept: list[TypedGuidanceFact] = []
    for fact in facts:
        reason = _semantic_alias_reason_v29(fact)
        if reason is None:
            kept.append(fact)
            continue
        rejected.append({
            "reason": reason,
            "metric": fact.metric.value,
            "period": fact.fiscal_period,
            "value": [fact.low, fact.high],
        })
    return kept

'''
if "def _suppress_semantic_aliases_v29(" not in text:
    text = replace_once(text, helper_marker, "\n" + helpers + helper_marker.lstrip("\n"), "insert v29 semantic guards")

period_marker = "            if _period_is_presentation_footer(clause, period):\n"
period_insert = """            local_quarter_period_v29 = _local_explicit_quarter_before_value_v29(clause, value)\n            if local_quarter_period_v29 is not None:\n                period = local_quarter_period_v29\n"""
if "local_quarter_period_v29 =" not in text:
    text = replace_once(text, period_marker, period_insert + period_marker, "v29 local quarter ownership")

old_finish = """    facts = _suppress_document_fragments(facts, rejected)\n    return RawTypedGuidanceExtraction(ticker=document.ticker, document_id=document.document_id, facts=tuple(facts), rejected_candidates=tuple(rejected))\n"""
new_finish = """    facts = _suppress_document_fragments(facts, rejected)\n    facts = _suppress_semantic_aliases_v29(facts, rejected)\n    return RawTypedGuidanceExtraction(ticker=document.ticker, document_id=document.document_id, facts=tuple(facts), rejected_candidates=tuple(rejected))\n"""
text = replace_once(text, old_finish, new_finish, "v29 semantic alias suppression")
path.write_text(text)


test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_result_metric_cannot_cross_into_fresh_guidance_row_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "KRMN29",
        "August 7, 2025 $115.1 million Revenue, up 35% YoY $35.3 million Adjusted EBITDA, up 29% YoY "
        "30.7% Adjusted EBITDA Margin $719 million Funded Backlog, up 36% YoY "
        "Raised full-year 2025 guidance to: $452 - $458 million revenue; "
        "$138.5 - $141.5 million Adjusted EBITDA.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert any((f.low, f.high) == (138.5, 141.5) for f in ebitda), [(f.low, f.high, f.fiscal_period) for f in ebitda]
    assert not any((f.low, f.high) == (452.0, 458.0) for f in ebitda), [(f.low, f.high, f.fiscal_period) for f in ebitda]


def test_historical_eps_value_cannot_become_current_fcf_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEFCF29",
        "FY26 free cash flow guidance is higher than what HPE projected by FY28. "
        "The company had expected to generate at least $3.00 in non-GAAP diluted net EPS.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert not any(f.low == 3.0 for f in fcf), [(f.low, f.high, f.fiscal_period) for f in fcf]


def test_eps_cannot_absorb_following_billion_scale_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEEPS29",
        "Fiscal 2025 guidance expected at least $3.00 in non-GAAP diluted net EPS and more than $3.5 billion in free cash flow.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps"]
    assert not any(f.low == 3.5 for f in eps), [(f.low, f.high, f.fiscal_period) for f in eps]


def test_fiscal_year_first_quarter_outlook_binds_q1_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEQ129",
        "Fiscal 2026 First Quarter Outlook HPE estimates revenue to be in the range of $9.0 billion to $9.4 billion. "
        "HPE estimates GAAP diluted net EPS to be in the range of $0.09 to $0.13.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 9.0]
    eps = [f for f in ex.facts if f.metric.value == "eps" and f.low == 0.09]
    assert revenue and all(f.fiscal_period == "Q1FY2026" for f in revenue), [(f.fiscal_period, f.low) for f in revenue]
    assert eps and all(f.fiscal_period == "Q1FY2026" for f in eps), [(f.fiscal_period, f.low) for f in eps]


def test_compound_q2_and_fy_heading_keeps_q2_value_quarter_bound_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "IOVA29",
        "Second Quarter 2026 and Full Year 2026 Guidance. "
        "Total product revenue guidance for 2Q26 is $86 million to $88 million and for FY26 is $350 million to $370 million.",
    ))
    q2 = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 86.0]
    assert q2 and all(f.fiscal_period == "Q2FY2026" for f in q2), [(f.fiscal_period, f.low, f.high) for f in q2]


def test_record_financial_result_revenue_is_not_guidance_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEACT29",
        "HPE reports fiscal 2026 third quarter results. Record results and demand drive higher outlook for fiscal 2026 and fiscal 2027 - "
        "Record revenue of $12.2 billion, up 34% year-over-year. "
        "Third Quarter Fiscal 2026 Financial Results • Revenue: $12.2 billion, up 34% from the prior-year period.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert not any(f.low == 12.2 for f in revenue), [(f.low, f.high, f.fiscal_period) for f in revenue]


def test_prior_quarter_reference_cannot_cross_fresh_annual_outlook_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ATRO29",
        "Reimbursements are expected to be received in the third quarter of 2026. "
        "2026 Outlook Astronics expects revenue to be $1.02 billion to $1.04 billion for the year.",
    ))
    annual = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 1.02]
    assert not any(f.fiscal_period == "Q3FY2026" for f in annual), [(f.fiscal_period, f.low, f.high) for f in annual]


def test_growth_comparison_year_is_not_guidance_period_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "FRPT29",
        "Full Year 2025 guidance: Net sales in the range of $1.12 billion to $1.15 billion, "
        "an increase of 15% to 18% from 2024, compared to previous guidance.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 1.12]
    assert not any(f.fiscal_period == "FY2024" for f in revenue), [(f.fiscal_period, f.low, f.high) for f in revenue]


def test_growth_yoy_row_cannot_absorb_neighbor_money_value_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "FRPTTAB29",
        "2025 guidance Updated Previous ~13% 13 - 16% Net Sales Growth YoY $190 - $195M $190M - $210M Adjusted EBITDA.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert not any((f.low, f.high) == (190.0, 195.0) for f in revenue), [(f.low, f.high, f.fiscal_period) for f in revenue]


def test_following_full_year_section_cannot_relabel_quarter_ebitda_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETA29",
        "Q2 2025 guidance: Increasing Adjusted EBITDA guidance to a range of $54.6 million to $55.2 million, "
        "up $500 thousand from prior guidance. The revised guidance represents an Adjusted EBITDA margin of 18.3% to 18.7%. "
        "Full Year 2025",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda" and f.low == 54.6]
    assert not any(f.fiscal_period == "FY2025" for f in ebitda), [(f.fiscal_period, f.low, f.high) for f in ebitda]
''')
