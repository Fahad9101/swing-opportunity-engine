from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    old = dedent(old).lstrip("\n")
    new = dedent(new).lstrip("\n")
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {text.count(old)}")
    return text.replace(old, new, 1)


def patch_canonical_extractor() -> None:
    path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
    text = path.read_text()

    text = replace_once(
        text,
        r'''
        _ACTUAL_VALUE = re.compile(
            r"\b(?:was|were|totaled|reported|generated|delivered|achieved|realized|"
            r"for\s+the\s+quarter\s+ended|for\s+the\s+year\s+ended|year[- ]to[- ]date)\b",
            re.I,
        )
        ''',
        r'''
        _ACTUAL_VALUE = re.compile(
            r"\b(?:was|were|totaled|reports?|reported|generated|delivered|achieved|realized|"
            r"(?:increased|decreased|grew|declined|rose|fell)(?:\s+\d+(?:\.\d+)?%)?\s+to|"
            r"for\s+the\s+quarter\s+ended|for\s+the\s+year\s+ended|year[- ]to[- ]date)\b",
            re.I,
        )
        ''',
        "historical-result vocabulary",
    )

    text = replace_once(
        text,
        r'''            r"(?:EPS|earnings\s+per\s+(?:common\s+)?share)\b",''',
        r'''            r"(?:EPS|earnings\s+per\s+(?:common\s+)?share|per\s+diluted\s+share)\b",''',
        "EPS owner vocabulary",
    )
    text = replace_once(
        text,
        r'''    ("repurchase", re.compile(r"\b(?:share|stock)\s+repurchase\b", re.I)),''',
        r'''    ("repurchase", re.compile(r"\b(?:(?:share|stock)\s+repurchase|repurchas(?:e|es|ed|ing))\b", re.I)),''',
        "repurchase owner vocabulary",
    )
    text = replace_once(
        text,
        r'''    ("contract_value", re.compile(r"\b(?:contract\s+wins?|contracts?\s+valued|transaction\s+consideration)\b", re.I)),''',
        r'''
        (
            "contract_value",
            re.compile(
                r"\b(?:contract\s+wins?|contracts?\s+valued|transaction\s+consideration|"
                r"contracts?\b[^.;]{0,100}\b(?:valued|combined\s+annual\s+revenues?))\b",
                re.I,
            ),
        ),
        ''',
        "contract-value owner vocabulary",
    )

    text = replace_once(
        text,
        r'''
        def _value_has_local_metric_owner(clause: str, anchor: int, mention, value) -> bool:
            current_start = anchor
            current_end = anchor + len(mention.text)
            current_gap = _span_gap(current_start, current_end, value.start, value.end)
            nearest_other: tuple[int, GuidanceMetric | str] | None = None
            for owner, pattern in _VALUE_OWNER_PATTERNS:
                for match in pattern.finditer(clause):
                    if owner is mention.metric and not (match.end() <= current_start or match.start() >= current_end):
                        continue
                    gap = _span_gap(match.start(), match.end(), value.start, value.end)
                    if nearest_other is None or gap < nearest_other[0]:
                        nearest_other = (gap, owner)
            if nearest_other is None:
                return True
            other_gap, other_owner = nearest_other
            if other_owner is mention.metric:
                return True
            return current_gap < other_gap
        ''',
        r'''
        def _value_has_local_metric_owner(clause: str, anchor: int, mention, value) -> bool:
            current_start = anchor
            current_end = anchor + len(mention.text)
            current_gap = _span_gap(current_start, current_end, value.start, value.end)
            nearest_other: tuple[int, GuidanceMetric | str] | None = None
            current_basis = (
                "ADJUSTED" if re.search(r"\b(?:adjusted|non[- ]GAAP)\b", mention.text, re.I)
                else "GAAP" if re.search(r"(?<!non[- ])\bGAAP\b", mention.text, re.I)
                else None
            )
            for owner, pattern in _VALUE_OWNER_PATTERNS:
                for match in pattern.finditer(clause):
                    overlaps_current = not (match.end() <= current_start or match.start() >= current_end)
                    if owner is mention.metric and overlaps_current:
                        continue
                    owner_is_effectively_other = owner is not mention.metric
                    if owner is mention.metric and value.end <= current_start:
                        owner_text = match.group(0)
                        owner_basis = (
                            "ADJUSTED" if re.search(r"\b(?:adjusted|non[- ]GAAP)\b", owner_text, re.I)
                            else "GAAP" if re.search(r"(?<!non[- ])\bGAAP\b", owner_text, re.I)
                            else None
                        )
                        owner_is_effectively_other = bool(
                            current_basis and owner_basis and current_basis != owner_basis
                        )
                    if not owner_is_effectively_other:
                        continue
                    gap = _span_gap(match.start(), match.end(), value.start, value.end)
                    if value.end <= current_start and match.end() <= value.start:
                        prior_gap = value.start - match.end()
                        if prior_gap <= 120 and prior_gap <= current_gap + 80:
                            return False
                    if nearest_other is None or gap < nearest_other[0]:
                        nearest_other = (gap, owner)
            if nearest_other is None:
                return True
            other_gap, _ = nearest_other
            return current_gap < other_gap
        ''',
        "local metric-owner binding",
    )

    text = replace_once(
        text,
        r'''
        def _value_is_historical_actual(clause: str, anchor: int, value) -> bool:
            if value is None:
                return False
            before = clause[max(0, min(anchor, value.start) - 40):value.start]
            actuals = list(_ACTUAL_VALUE.finditer(before))
            if not actuals:
                return False
            latest_actual = actuals[-1]
            after_actual = before[latest_actual.end():]
            if _FORWARD_SIGNAL.search(after_actual):
                return False
            return len(before) - latest_actual.end() <= 90
        ''',
        r'''
        def _value_is_historical_actual(clause: str, anchor: int, value) -> bool:
            if value is None:
                return False
            before = clause[max(0, min(anchor, value.start) - 120):value.start]
            actuals = list(_ACTUAL_VALUE.finditer(before))
            if not actuals:
                return False
            latest_actual = actuals[-1]
            marker_context = before[max(0, latest_actual.start() - 80):latest_actual.end()]
            if re.search(r"\b(?:guidance|outlook|forecast)\b", marker_context, re.I):
                return False
            after_actual = before[latest_actual.end():]
            if _FORWARD_SIGNAL.search(after_actual):
                return False
            return len(before) - latest_actual.end() <= 120
        ''',
        "historical actual boundary",
    )

    text = replace_once(
        text,
        "    best_by_key: dict[tuple, int] = {}\n",
        r'''
            # Suppress an unscaled shadow fragment when exactly the same raw endpoints
            # also exist in a scaled money observation for the same economic identity.
            scaled_units = {
                GuidanceUnit.USD_THOUSAND,
                GuidanceUnit.USD_MILLION,
                GuidanceUnit.USD_BILLION,
            }
            for i, fact in enumerate(items):
                if i in remove or fact.low is None or fact.high is None or fact.unit is not GuidanceUnit.USD:
                    continue
                for j, other in enumerate(items):
                    if i == j or j in remove or other.unit not in scaled_units:
                        continue
                    if not _same_economic_identity(fact, other):
                        continue
                    if fact.low == other.low and fact.high == other.high:
                        remove.add(i)
                        rejected.append(
                            {
                                "reason": "unscaled_shadow_fragment",
                                "metric": fact.metric.value,
                                "period": fact.fiscal_period,
                                "value": [fact.low, fact.high],
                            }
                        )
                        break

            best_by_key: dict[tuple, int] = {}
        ''',
        "scale-shadow suppression",
    )

    text = replace_once(
        text,
        r'''
                    if period is None:
                        rejected.append({"reason": "ambiguous_or_missing_period", "metric": mention.metric.value, "evidence": clause[:500]}); continue
                    if value is None and local_action not in {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM, GuidanceAction.WITHDRAW}:
        ''',
        r'''
                    if period is None:
                        rejected.append({"reason": "ambiguous_or_missing_period", "metric": mention.metric.value, "evidence": clause[:500]}); continue
                    if value is not None and value.end <= period.start <= anchor:
                        rejected.append(
                            {
                                "reason": "value_crosses_period_boundary",
                                "metric": mention.metric.value,
                                "value_text": value.text,
                                "period": period.period,
                                "evidence": clause[:500],
                            }
                        ); continue
                    if value is None and local_action not in {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM, GuidanceAction.WITHDRAW}:
        ''',
        "period-heading boundary",
    )

    if '"raw_document_extractor": "guidance-canonical-raw-v4"' not in text:
        raise RuntimeError("raw extractor version marker changed upstream")
    text = text.replace(
        '"raw_document_extractor": "guidance-canonical-raw-v4"',
        '"raw_document_extractor": "guidance-canonical-raw-v5"',
    )
    path.write_text(text)


def patch_typed_extractor() -> None:
    path = ROOT / "backend/app/services/guidance_raw_typed_extractor.py"
    text = path.read_text()
    text = replace_once(
        text,
        r'''        eps_single = re.compile(r"\$\s*(?P<value>-?\d+(?:\.\d+)?)(?!\s*%)")''',
        r'''        eps_single = re.compile(r"\$\s*(?P<value>-?\d+(?:\.\d+)?)(?![\d,]|\s*%)")''',
        "EPS comma truncation guard",
    )
    path.write_text(text)


def patch_replay_report() -> None:
    path = ROOT / "backend/app/services/guidance_raw_replay_differential_service.py"
    text = path.read_text()
    old = dedent(r'''
            ticker_reports.append(
                {
                    "ticker": ticker,
                    "legacy_classification": old_classification,
                    "raw_canonical_classification": raw_classification,
                    "status": "COMPLETE",
                    "source_document_count": len(by_ticker.get(ticker, [])),
                    "raw_fact_count": ticker_raw_count,
                    "canonical_fact_count": len(canonical.accepted),
                    "quarantined_fact_count": len(canonical.quarantined),
                    "quarantine_codes": dict(sorted(ticker_codes.items())),
                    "rejected_candidate_count": len(rejected),
                }
            )
    ''').lstrip("\n")
    new = dedent(r'''
            ticker_reports.append(
                {
                    "ticker": ticker,
                    "legacy_classification": old_classification,
                    "raw_canonical_classification": raw_classification,
                    "status": "COMPLETE",
                    "source_document_count": len(by_ticker.get(ticker, [])),
                    "raw_fact_count": ticker_raw_count,
                    "canonical_fact_count": len(canonical.accepted),
                    "quarantined_fact_count": len(canonical.quarantined),
                    "quarantine_codes": dict(sorted(ticker_codes.items())),
                    "rejected_candidate_count": len(rejected),
                    "accepted_facts": [_fact_summary(fact) for fact in canonical.accepted],
                    "quarantined_facts": [_quarantine_summary(item) for item in canonical.quarantined],
                    "rejected_candidates": rejected,
                }
            )
    ''').lstrip("\n")
    if text.count(old) != 1:
        raise RuntimeError(f"complete replay report block: expected one match, found {text.count(old)}")
    path.write_text(text.replace(old, new, 1))


def patch_tests() -> None:
    path = ROOT / "backend/tests/test_guidance_raw_canonical_extractor.py"
    text = path.read_text()
    if "def test_semantic_acceptance_cross_metric_owner_regressions():" in text:
        return
    text += r'''


def test_semantic_acceptance_cross_metric_owner_regressions():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "OWNER2",
            "Fiscal year 2027 guidance: Revenue of between $630 million and $650 million; "
            "Non-GAAP adjusted EBITDA of between $135 million and $145 million. "
            "Full year 2026 guidance: net cash provided by operating activities to range between "
            "$2.90 billion and $3.40 billion and free cash flow to range between $2.00 billion and $2.50 billion.",
        )
    )
    ebitda = [fact for fact in extraction.facts if fact.metric.value == "ebitda"]
    fcf = [fact for fact in extraction.facts if fact.metric.value == "fcf"]
    assert all((fact.low, fact.high) != (630.0, 650.0) for fact in ebitda)
    assert all((fact.low, fact.high) != (2.90, 3.40) for fact in fcf)
    assert any((fact.low, fact.high) == (135.0, 145.0) for fact in ebitda)
    assert any((fact.low, fact.high) == (2.00, 2.50) for fact in fcf)


def test_semantic_acceptance_period_heading_blocks_prior_value_binding():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "HEADING",
            "Adjusted restaurant-level profit is expected to be approximately $208 million to $212 million in FY25. "
            "Initial Fiscal 2026 Financial Guidance: Total revenue of $1.6 billion to $1.7 billion.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert any(fact.fiscal_period == "FY2026" and (fact.low, fact.high) == (1.6, 1.7) for fact in revenue)
    assert all((fact.low, fact.high) != (208.0, 212.0) for fact in revenue)


def test_semantic_acceptance_scale_shadow_is_suppressed():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "SCALE",
            "For full year 2026, we are raising our revenue guidance to between $8.150 - $8.158 billion.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    observed = {(fact.low, fact.high, fact.unit.value) for fact in revenue}
    assert (8.15, 8.158, "USD_BILLION") in observed
    assert (8.15, 8.158, "USD") not in observed


def test_semantic_acceptance_result_headline_is_not_forward_guidance():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "ACTUAL2",
            "Humana Reports Second Quarter 2026 Financial Results; Affirms Full Year 2026 Adjusted Financial Guidance. "
            "Reports 2Q26 earnings per share (EPS) of $5.73 on a GAAP basis, Adjusted EPS of $7.61. "
            "FY 2026 Adjusted EPS guidance is at least $9.00.",
        )
    )
    eps = [fact for fact in extraction.facts if fact.metric.value == "eps"]
    assert all(fact.low not in {5.73, 7.61} for fact in eps)
    assert any(fact.low == 9.0 for fact in eps)


def test_semantic_acceptance_eps_does_not_truncate_comma_dollar_amount():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "COMMA",
            "FY 2026 Adjusted EPS guidance is at least $9.00. Adjusted net income $2,263 million.",
        )
    )
    eps = [fact for fact in extraction.facts if fact.metric.value == "eps"]
    assert all(fact.low != 2.0 for fact in eps)
'''
    path.write_text(text)


if __name__ == "__main__":
    patch_canonical_extractor()
    patch_typed_extractor()
    patch_replay_report()
    patch_tests()
