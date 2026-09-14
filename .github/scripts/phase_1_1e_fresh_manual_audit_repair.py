from __future__ import annotations

from pathlib import Path

EXTRACTOR = Path("backend/app/services/guidance_raw_canonical_extractor.py")
TESTS = Path("backend/tests/test_guidance_manual_audit_regressions.py")

V34_MARKER = "_RPO_ACCOUNTING_DISCLOSURE_V34"

V34_CODE = r'''

# Phase 1.1E fresh 100-case manual-audit hardening (v34). These guards remain
# evidence-conservative: ambiguous accounting disclosures, realized results,
# cross-period table bleed, and mechanical per-share restatements are rejected
# rather than converted into economic guidance changes. Frozen SOE thresholds,
# weights, and classifier rules are unchanged.
_RPO_ACCOUNTING_DISCLOSURE_V34 = re.compile(
    r"\\b(?:remaining\\s+performance\\s+obligations?|deferred\\s+revenue)\\b",
    re.I,
)
_RECOGNIZED_REVENUE_ACTUAL_V34 = re.compile(
    r"\\b(?:during|for)\\s+the\\s+(?:three|six|nine|twelve)\\s+months?\\s+ended\\b"
    r".{0,260}\\brecognized\\s+revenue\\b",
    re.I | re.S,
)
_OUTLOOK_CURRENT_ACTUAL_HEADER_V34 = re.compile(
    r"\\bOutlook\\s+(20\\d{2})\\s+(20\\d{2})\\b",
    re.I,
)
_QUARTER_RESULTS_HEADER_V34 = re.compile(
    r"\\b(?:First|Second|Third|Fourth)\\s+Quarter\\s+20\\d{2}(?:\\s+Results)?\\s*:?",
    re.I,
)
_GENERIC_FINANCIAL_GUIDANCE_HEADING_V34 = re.compile(
    r"\\bFinancial\\s+Guidance\\s+20\\d{2}\\s+Guidance\\b",
    re.I,
)
_STOCK_SPLIT_RESTATEMENT_V34 = re.compile(
    r"\\b(?:two[- ]for[- ]one|three[- ]for[- ]one|\\d+[- ]for[- ]\\d+)\\s+stock\\s+split\\b"
    r".{0,280}\\b(?:guidance|outlook)\\b.{0,180}\\b(?:pre[- ]split|post[- ]split|following)\\b"
    r"|\\bfollowing\\s+(?:the\\s+)?(?:two[- ]for[- ]one|three[- ]for[- ]one|\\d+[- ]for[- ]\\d+)\\s+stock\\s+split\\b"
    r".{0,260}\\b(?:guidance|outlook)\\b",
    re.I | re.S,
)
_NAMED_ENTITY_GENERATE_REVENUE_V34 = re.compile(
    r"\\bFor\\s+the\\s+full\\s+calendar\\s+year\\s+20\\d{2}\\s*,?\\s*"
    r"(?P<owner>[A-Z][A-Za-z0-9&.'-]{2,})\\s+expects?\\s+to\\s+generate\\s+revenue\\b",
    re.I,
)


def _fresh_manual_audit_reason_v34(fact: TypedGuidanceFact) -> str | None:
    if not fact.provenance:
        return None
    evidence = fact.provenance[0].evidence
    clause = evidence.full_text or ""
    if not clause:
        return None
    ms, me = evidence.metric_start, evidence.metric_end
    vs, ve = evidence.value_start, evidence.value_end

    # Remaining-performance-obligation and deferred-revenue schedules describe
    # accounting recognition, not management guidance.
    if fact.metric is GuidanceMetric.REVENUE and _RPO_ACCOUNTING_DISCLOSURE_V34.search(clause):
        if re.search(
            r"\\b(?:expects?\\s+to\\s+recognize|expected\\s+to\\s+be\\s+recognized|recognize[d]?\\s+as)\\s+revenue\\b"
            r"|\\brevenue\\s+is\\s+expected\\s+to\\s+be\\s+recognized\\b",
            clause,
            re.I,
        ):
            return "remaining_performance_obligation_not_guidance"

    # Realized recognized-revenue disclosures must not become annual guidance.
    if fact.metric is GuidanceMetric.REVENUE and _RECOGNIZED_REVENUE_ACTUAL_V34.search(clause):
        return "recognized_revenue_historical_actual"

    # In flattened Outlook YYYY YYYY tables, the second year is the historical
    # actual/comparator column. Do not bind it as current guidance.
    if fact.metric is GuidanceMetric.REVENUE:
        header = _OUTLOOK_CURRENT_ACTUAL_HEADER_V34.search(clause)
        if header and fact.fiscal_period == f"FY{header.group(2)}":
            return "outlook_historical_column_not_guidance"

    # Result bullets can inherit a nearby "raising full-year guidance" action.
    # Reject the realized quarter value rather than treating GAAP/adjusted actuals
    # as a same-snapshot guidance revision.
    if fact.metric is GuidanceMetric.REVENUE and vs is not None and ve is not None:
        before = clause[max(0, vs - 360):vs]
        after = clause[ve:min(len(clause), ve + 90)]
        result_headers = list(_QUARTER_RESULTS_HEADER_V34.finditer(before))
        if result_headers:
            latest = result_headers[-1]
            result_tail = before[latest.end():]
            if not re.search(r"\\b(?:guidance|outlook|forecast)\\b", result_tail, re.I) and re.match(
                r"\\s*,?\\s*(?:up|down|\\+|-)?\\s*\\d+(?:\\.\\d+)?%",
                after,
                re.I,
            ):
                return "quarter_results_actual_with_guidance_action_leak"

    # Historical FCF rows immediately preceding a generic Financial Guidance
    # heading are realized results, not the new full-year FCF outlook.
    if fact.metric is GuidanceMetric.FCF and vs is not None and ve is not None:
        after = clause[ve:min(len(clause), ve + 260)]
        before = clause[max(0, vs - 170):vs]
        if _GENERIC_FINANCIAL_GUIDANCE_HEADING_V34.search(after) and not re.search(
            r"\\b(?:guidance|outlook|forecast|expects?|expected|reaffirm|reiterate|raise|lower)\\b",
            before,
            re.I,
        ):
            return "historical_fcf_before_guidance_section"

    # "cost of revenues" / "costs of revenues" is an expense metric. The
    # revenue token inside that phrase cannot own a revenue guidance action.
    if fact.metric is GuidanceMetric.REVENUE and ms is not None:
        metric_local = clause[max(0, ms - 55):min(len(clause), (me or ms) + 55)]
        if re.search(r"\\bcosts?\\s+of\\s+(?:contract\\s+)?revenues?\\b", metric_local, re.I):
            return "revenue_token_inside_cost_of_revenues"

    # If a quarter fact's selected value is explicitly introduced as full-year
    # guidance for the same metric, the quarter period is table/phrase bleed.
    if fact.period_kind is GuidancePeriodKind.QUARTER and vs is not None:
        before = clause[max(0, vs - 220):vs]
        metric_word = {
            GuidanceMetric.REVENUE: r"(?:revenue|net\\s+sales)",
            GuidanceMetric.EPS: r"(?:EPS|earnings\\s+per\\s+(?:common\\s+)?share)",
            GuidanceMetric.EBITDA: r"(?:adjusted\\s+)?EBITDA",
            GuidanceMetric.FCF: r"(?:free\\s+cash\\s+flow|FCF)",
            GuidanceMetric.GROSS_MARGIN: r"gross(?:\\s+profit)?\\s+margin",
            GuidanceMetric.OPERATING_MARGIN: r"operating\\s+margin",
        }.get(fact.metric)
        if metric_word and re.search(
            rf"\\b(?:rais(?:e|es|ed|ing)|lower(?:s|ed|ing)?|provid(?:e|es|ed|ing)|maintain(?:s|ed|ing)?)\\b"
            rf"[^.;•]{{0,80}}\\b{metric_word}\\b[^.;•]{{0,45}}\\b(?:guidance|outlook)\\b"
            rf"[^.;•]{{0,55}}\\b(?:fiscal(?:\\s+year)?|full[- ]year)\\s+20\\d{{2}}\\b"
            r"|"
            rf"\\b{metric_word}\\b[^.;•]{{0,35}}\\b(?:guidance|outlook)\\b"
            rf"[^.;•]{{0,35}}\\b(?:fiscal(?:\\s+year)?|full[- ]year)\\s+20\\d{{2}}\\b",
            before,
            re.I,
        ):
            return "full_year_guidance_misbound_to_quarter"

    # Per-share guidance mechanically restated for a stock split is not an
    # economic cut. Reject the nominal restatement so the classifier fails closed
    # rather than comparing pre-split and post-split EPS as like-for-like levels.
    if fact.metric is GuidanceMetric.EPS and _STOCK_SPLIT_RESTATEMENT_V34.search(clause):
        return "stock_split_eps_restatement_not_economic_cut"

    # A named non-issuer entity's stand-alone annual revenue expectation inside
    # an issuer filing is scope-ambiguous. Without issuer/entity resolution,
    # fail closed instead of treating it as consolidated company guidance.
    if fact.metric is GuidanceMetric.REVENUE and fact.scope_kind is GuidanceScopeKind.COMPANY:
        owner = _NAMED_ENTITY_GENERATE_REVENUE_V34.search(clause)
        if owner and owner.group("owner").lower() not in {"company", "management"}:
            return "named_entity_revenue_forecast_scope_ambiguous"

    return None


def _suppress_fresh_manual_audit_defects_v34(
    facts: Iterable[TypedGuidanceFact],
    rejected: list[dict],
) -> list[TypedGuidanceFact]:
    kept: list[TypedGuidanceFact] = []
    for fact in facts:
        reason = _fresh_manual_audit_reason_v34(fact)
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

TEST_APPEND = r'''

# Fresh post-v33 full-market manual-audit regressions (v34).
def test_remaining_performance_obligation_revenue_is_not_guidance():
    toast = _facts("TOST", "As of June 30, 2026, approximately $1,110 million of revenue is expected to be recognized from remaining performance obligations over the next twelve months.")
    assert not any(f.metric.value == "revenue" and f.low == 1110 for f in toast)
    okta = _facts("OKTA", "Remaining performance obligations were $4,858 million. Of this amount, the Company expects to recognize revenue of approximately $2,585 million over the next 12 months.")
    assert not any(f.metric.value == "revenue" and f.low == 2585 for f in okta)


def test_recognized_revenue_result_is_not_full_year_guidance():
    facts = _facts("PWR", "For the full year ending December 31, 2026, Quanta expects revenues to range between $34.7 billion and $35.2 billion. During the six months ended June 30, 2026 and 2025, Quanta recognized revenue of approximately $2.53 billion and $1.96 billion, respectively.")
    assert not any(f.metric.value == "revenue" and f.low == 2.53 for f in facts)


def test_outlook_historical_column_is_not_current_guidance():
    facts = _facts("EVTC", "2026 Outlook. Outlook 2026 2025 (Dollar amounts in millions, except per share data) Low High Revenues (GAAP) $1,085 $1,095 $1,073.")
    assert not any(f.metric.value == "revenue" and f.fiscal_period == "FY2025" and f.low == 1073 for f in facts)


def test_quarter_results_do_not_inherit_full_year_raise_action():
    facts = _facts("GE", "GE Aerospace announces Second Quarter 2026 Results, raising full-year guidance across the board. Second Quarter 2026 Results: Total revenue (GAAP) of $13.3 billion, +21%; adjusted revenue of $12.6 billion, +24%.")
    assert not any(f.metric.value == "revenue" and f.fiscal_period == "Q2FY2026" for f in facts)


def test_realized_fcf_before_financial_guidance_section_is_not_guidance():
    facts = _facts("PYPL", "Adjusted free cash flow $1,832 $656 179%. Financial Guidance 2026 Guidance: Following another strong quarter, PayPal is raising full year non-GAAP EPS guidance.")
    assert not any(f.metric.value == "fcf" and f.low == 1832 for f in facts)


def test_cost_of_revenues_plural_is_not_revenue_guidance():
    facts = _facts("ENTG", "We expect total depreciation expense in 2026 to be reduced by approximately $73.0 million recognized primarily in cost of revenues and R&D expenses.")
    assert not any(f.metric.value == "revenue" and f.low == 73 for f in facts)


def test_full_year_revenue_guidance_is_not_rebound_to_quarter():
    facts = _facts("CIEN", "Providing revenue guidance for fiscal fourth quarter 2026 of $1.75 billion plus or minus $50 million. Raising revenue guidance for fiscal year 2026 to $6.42 billion plus or minus $50 million.")
    assert any(f.metric.value == "revenue" and f.fiscal_period == "FY2026" and f.low == 6.42 for f in facts)
    assert not any(f.metric.value == "revenue" and f.fiscal_period == "Q4FY2026" and f.low == 6.42 for f in facts)


def test_stock_split_eps_restatement_is_not_economic_guidance_cut():
    facts = _facts("APH", "Following the two-for-one stock split, the Company's Adjusted Diluted EPS guidance for the third quarter of 2026 would be $0.70 to $0.71, versus pre-split guidance of $1.40 to $1.42.")
    assert not any(f.metric.value == "eps" and f.low == 0.70 and f.high == 0.71 for f in facts)


def test_named_entity_standalone_revenue_forecast_fails_closed_on_scope():
    facts = _facts("ECG", "For the full calendar year 2026, Epsilon expects to generate revenue of approximately $250 million with earnings before interest, taxes, depreciation and amortization.")
    assert not any(f.metric.value == "revenue" and f.low == 250 for f in facts)


def test_valid_annual_ebitda_raise_survives_v34_guards():
    facts = _facts("ESI", "The Company now expects full year 2026 adjusted EBITDA to be in the range of $690 million to $710 million.")
    assert any(f.metric.value == "ebitda" and f.fiscal_period == "FY2026" for f in facts)
'''


def main() -> None:
    extractor = EXTRACTOR.read_text()
    if V34_MARKER not in extractor:
        marker = "\ndef _suppress_document_fragments(facts: Iterable[TypedGuidanceFact], rejected: list[dict]) -> list[TypedGuidanceFact]:\n"
        if marker not in extractor:
            raise SystemExit("extractor insertion marker not found")
        extractor = extractor.replace(marker, V34_CODE + marker, 1)

        old_calls = (
            "    facts = _suppress_manual_audit_defects_v33(facts, rejected)\n"
            "    facts = _suppress_document_fragments(facts, rejected)\n"
            "    facts = _suppress_semantic_aliases_v29(facts, rejected)\n"
        )
        new_calls = (
            "    facts = _suppress_manual_audit_defects_v33(facts, rejected)\n"
            "    facts = _suppress_fresh_manual_audit_defects_v34(facts, rejected)\n"
            "    facts = _suppress_document_fragments(facts, rejected)\n"
            "    facts = _suppress_semantic_aliases_v29(facts, rejected)\n"
        )
        if old_calls not in extractor:
            raise SystemExit("extractor call-site marker not found")
        extractor = extractor.replace(old_calls, new_calls, 1)
        EXTRACTOR.write_text(extractor)

    tests = TESTS.read_text()
    if "Fresh post-v33 full-market manual-audit regressions (v34)." not in tests:
        TESTS.write_text(tests.rstrip() + TEST_APPEND + "\n")


if __name__ == "__main__":
    main()
