from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = PATH.read_text()


def replace_function(source: str, name: str, new_source: str) -> str:
    marker = f"\ndef {name}("
    start = source.find(marker)
    if start < 0:
        raise RuntimeError(f"{name}: function start not found")
    start += 1
    next_start = source.find("\ndef ", start + 1)
    if next_start < 0:
        return source[:start] + new_source.rstrip() + "\n"
    return source[:start] + new_source.rstrip() + "\n\n" + source[next_start + 1:]


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


# 1) BKSY-class role locality: a historical "previously updated" clause does
# not turn a subsequently reaffirmed/current numeric value into QUOTED_PRIOR.
text = replace_function(
    text,
    "_fact_role",
    r'''def _fact_role(clause: str, value) -> GuidanceFactRole:
    if value is None:
        return GuidanceFactRole.CURRENT
    before = clause[max(0, value.start - 180):value.start]
    prior_patterns = [
        re.compile(r"\b(?:from\s+(?:our\s+)?)?prior(?:\s+[A-Za-z0-9*.-]+){0,5}\s+(?:guidance|outlook|forecast)\b", re.I),
        re.compile(r"\bprevious(?:\s+[A-Za-z0-9*.-]+){0,5}\s+(?:guidance|outlook|forecast|estimate)\b", re.I),
        re.compile(r"\bpreviously(?:\s+(?:expected|forecast|guided|provided|stated|updated))?\b", re.I),
    ]
    matches = [match for pattern in prior_patterns for match in pattern.finditer(before)]
    if not matches:
        return GuidanceFactRole.CURRENT
    latest = max(matches, key=lambda item: item.end())
    tail = before[latest.end():]
    # A fresh forward/current cue after the historical marker owns the value.
    # Example: "reaffirming ... previously updated ... The Company expects ... $X".
    if re.search(
        r"\b(?:now|currently|reaffirm(?:s|ed|ing)?|maintain(?:s|ed|ing)?|"
        r"expects?|expected|anticipat(?:e|es|ed|ing)|project(?:s|ed|ing))\b",
        tail,
        re.I,
    ):
        return GuidanceFactRole.CURRENT
    return GuidanceFactRole.QUOTED_PRIOR''',
)

# 2) KNSA-class product scope: a branded all-caps token immediately qualifying
# "net sales" is product guidance, not consolidated/company net sales.
brand_marker = '_PRODUCT_REVENUE_QUALIFIER = re.compile(r"\\bproduct\\s*$", re.I)\n'
brand_constants = r'''_BRANDED_NET_SALES = re.compile(r"(?:^|[\s(])(?P<brand>[A-Z][A-Z0-9-]{2,})(?:®|™)?\s*$")
_BRAND_SCOPE_RESERVED = {
    "TOTAL", "FULL", "GAAP", "NON", "ADJUSTED", "ANNUAL", "FISCAL", "COMPANY",
    "FY", "QTR", "QUARTER", "YEAR",
}
'''
if "_BRANDED_NET_SALES" not in text:
    text = replace_once(text, brand_marker, brand_marker + brand_constants, "branded net-sales constants")

old_scope = '''    if "total product revenue" in lower or "total revenue" in lower or "consolidated revenue" in lower or "net sales" in lower:\n        return GuidanceScopeKind.COMPANY, label\n'''
new_scope = '''    if "net sales" in lower:\n        prefix = clause[max(0, anchor - 70):anchor]\n        prefix = re.split(r"[.;:•|\\n\\r]", prefix)[-1].strip()\n        branded = _BRANDED_NET_SALES.search(prefix)\n        if branded and branded.group("brand").upper() not in _BRAND_SCOPE_RESERVED:\n            return GuidanceScopeKind.PRODUCT, branded.group("brand") + " net sales"\n        return GuidanceScopeKind.COMPANY, label\n    if "total product revenue" in lower or "total revenue" in lower or "consolidated revenue" in lower:\n        return GuidanceScopeKind.COMPANY, label\n'''
text = replace_once(text, old_scope, new_scope, "branded net-sales scope")

# 3) SPXC-class historical result tail: "$X, up/down Y%" is an actual result
# unless forward/guidance language already owns the metric/value span.
text = replace_function(
    text,
    "_value_is_historical_actual",
    r'''def _value_is_historical_actual(clause: str, anchor: int, value) -> bool:
    if value is None:
        return False
    before = clause[max(0, min(anchor, value.start) - 140):value.start]
    after = clause[value.end:min(len(clause), value.end + 100)]
    forward_before = bool(_FORWARD_SIGNAL.search(before))
    if not forward_before and re.search(
        r"^\s*(?:,|;)?\s*(?:up|down)\s+\d+(?:\.\d+)?%\b"
        r"(?:\s+(?:YoY|Y/Y|year[- ]over[- ]year))?",
        after,
        re.I,
    ):
        return True
    actuals = list(_ACTUAL_VALUE.finditer(before))
    if not actuals:
        return False
    latest_actual = actuals[-1]
    after_actual = before[latest_actual.end():]
    if _FORWARD_SIGNAL.search(after_actual):
        return False
    return len(before) - latest_actual.end() <= 120''',
)

# 4) PLTR-class omitted-scale shadow: raw "$8.15" fragments that duplicate an
# endpoint of a correctly scaled "$8.15-$8.158 billion" observation are noise.
fragment_marker = '    best_by_key: dict[tuple, int] = {}\n'
fragment_insertion = r'''    # Suppress an unscaled point/range shadow when its raw numeric token(s)
    # duplicate endpoint(s) of a scaled observation for the exact same economic
    # identity. Compare raw numbers deliberately: base-currency comparison cannot
    # detect the omitted "million/billion" token that created the shadow.
    for i, fact in enumerate(items):
        if i in remove or fact.low is None or fact.high is None or fact.unit is not GuidanceUnit.USD:
            continue
        if max(abs(fact.low), abs(fact.high)) >= 10_000:
            continue
        for j, other in enumerate(items):
            if i == j or j in remove or other.unit not in scaled_units:
                continue
            if not _same_economic_identity(fact, other):
                continue
            if other.low is None or other.high is None:
                continue
            raw_point_endpoint = (
                fact.low == fact.high
                and (abs(fact.low - other.low) <= 1e-9 or abs(fact.low - other.high) <= 1e-9)
            )
            raw_range_match = (
                abs(fact.low - other.low) <= 1e-9 and abs(fact.high - other.high) <= 1e-9
            )
            if raw_point_endpoint or raw_range_match:
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

'''
text = replace_once(text, fragment_marker, fragment_insertion + fragment_marker, "raw endpoint shadow suppression")

# 5) KRMN/FRPT-class compact suffix-owned money ranges. The value must end
# immediately before its metric and may not cross a semicolon/bullet boundary.
constant_marker = '_PREVIOUS_NOW_PERCENT = re.compile(\n'
constant_pos = text.find(constant_marker)
if constant_pos < 0:
    raise RuntimeError("suffix-range constant insertion point not found")
if "_SUFFIX_MONEY_RANGE" not in text:
    suffix_constant = r'''_SUFFIX_MONEY_RANGE = re.compile(
    r"(?P<d1>\$)?\s*(?P<lo>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?:-|–|—|to|through)\s*(?P<d2>\$)?\s*(?P<hi>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<scale>billion|million|thousand|bn|mm|m|b)?\s*$",
    re.I,
)
_BREAKEVEN_TO_MONEY = re.compile(
    r"\b(?:between\s+)?breakeven\s+(?:and|to|through|-|–|—)\s*"
    r"(?P<d>\$)?\s*(?P<high>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<scale>billion|million|thousand|bn|mm|m|b)?\b",
    re.I,
)

'''
    text = text[:constant_pos] + suffix_constant + text[constant_pos:]

helper_marker = '\ndef _previous_now_value_pair('
helper_pos = text.find(helper_marker)
if helper_pos < 0:
    raise RuntimeError("suffix helper insertion point not found")
if "def _suffix_owned_money_range(" not in text:
    helpers = r'''
def _suffix_owned_money_range(clause: str, anchor: int, mention) -> _ValueBinding | None:
    prefix = clause[max(0, anchor - 90):anchor]
    boundary = max(prefix.rfind(";"), prefix.rfind("•"), prefix.rfind("."))
    local = prefix[boundary + 1:]
    match = _SUFFIX_MONEY_RANGE.search(local)
    if not match:
        return None
    absolute_start = max(0, anchor - 90) + boundary + 1 + match.start()
    absolute_end = max(0, anchor - 90) + boundary + 1 + match.end()
    bridge = clause[absolute_end:anchor]
    if len(bridge) > 24 or not re.fullmatch(r"[\s,:()]*", bridge):
        return None
    unit = _unit_from_scale(
        match.group("scale"),
        mention.metric,
        dollar=bool(match.group("d1") or match.group("d2")),
    )
    if unit is GuidanceUnit.UNKNOWN:
        return None
    low = float(match.group("lo").replace(",", ""))
    high = float(match.group("hi").replace(",", ""))
    if low > high:
        return None
    return _ValueBinding(
        low, high, unit, GuidanceValueKind.ABSOLUTE_LEVEL,
        match.group(0).strip(), absolute_start, absolute_end,
    )


def _breakeven_value(clause: str, anchor: int, mention) -> _ValueBinding | None:
    if mention.metric not in {GuidanceMetric.EBITDA, GuidanceMetric.FCF}:
        return None
    match = _BREAKEVEN_TO_MONEY.search(clause)
    if not match:
        return None
    if _span_gap(anchor, anchor + len(mention.text), match.start(), match.end()) > 150:
        return None
    unit = _unit_from_scale(match.group("scale"), mention.metric, dollar=bool(match.group("d")))
    if unit is GuidanceUnit.UNKNOWN:
        return None
    high = float(match.group("high").replace(",", ""))
    return _ValueBinding(
        0.0, high, unit, GuidanceValueKind.ABSOLUTE_LEVEL,
        match.group(0), match.start(), match.end(),
    )


def _ambiguous_eps_basis_window(clause: str, anchor: int, mention) -> bool:
    if mention.metric is not GuidanceMetric.EPS:
        return False
    window = clause[max(0, anchor - 45):anchor + len(mention.text)]
    adjusted = bool(re.search(r"\b(?:adjusted|non[- ]GAAP)\b", window, re.I))
    gaap = bool(re.search(r"(?<!non[- ])\bGAAP\b", window, re.I))
    return adjusted and gaap

'''
    text = text[:helper_pos] + helpers + text[helper_pos:]

# Modify only the local value-selection and locality lines inside the existing
# published-v5 extractor. Period binding and section fallback remain untouched.
old_values = '''            previous_now_value, previous_now_prior = _previous_now_value_pair(clause, mention)\n            directional_value, directional_prior = _directional_value_pair(clause, anchor, mention, local_action)\n            value = previous_now_value or directional_value or _bind_value(clause, mention, anchor)\n            explicit_prior = previous_now_prior or directional_prior\n'''
new_values = '''            if _ambiguous_eps_basis_window(clause, anchor, mention):\n                rejected.append({"reason": "ambiguous_accounting_basis", "metric": mention.metric.value, "evidence": clause[:500]}); continue\n            previous_now_value, previous_now_prior = _previous_now_value_pair(clause, mention)\n            directional_value, directional_prior = _directional_value_pair(clause, anchor, mention, local_action)\n            suffix_value = _suffix_owned_money_range(clause, anchor, mention)\n            breakeven_value = _breakeven_value(clause, anchor, mention)\n            owned_value = previous_now_value or directional_value or suffix_value or breakeven_value\n            value = owned_value or _bind_value(clause, mention, anchor)\n            explicit_prior = previous_now_prior or directional_prior\n'''
text = replace_once(text, old_values, new_values, "surgical owned-value selection")

old_locality = '''            if value is not None and not _value_has_local_metric_owner(clause, anchor, mention, value):\n                rejected.append({"reason": "metric_value_locality", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
new_locality = '''            if value is not None and owned_value is None and not _value_has_local_metric_owner(clause, anchor, mention, value):\n                rejected.append({"reason": "metric_value_locality", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
text = replace_once(text, old_locality, new_locality, "surgical locality bypass")

PATH.write_text(text)

# Golden regression cases for only the six surgical evidence mechanics.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
test_path.write_text(r'''from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.domain.guidance_canonical_v1 import GuidanceFactRole, GuidanceScopeKind
from app.domain.soe_v1_1 import SourceDocument
from app.services.guidance_raw_canonical_extractor import extract_canonical_typed_guidance_facts

TS = datetime(2026, 8, 15, tzinfo=UTC)


def _doc(ticker: str, text: str) -> SourceDocument:
    digest = hashlib.sha256(text.encode()).hexdigest()
    return SourceDocument(
        document_id=f"surgical-{ticker}-{digest[:10]}", rules_hash="surgical", ticker=ticker,
        cik="0000000001", accession="0000000001-26-000001", form="8-K",
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}.htm",
        source_timestamp=TS, fetched_at=TS, stale=False, content_hash=digest,
        content_type="text/plain", content=text,
    )


def test_reaffirmed_current_value_not_demoted_by_previous_update_date():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ROLE",
        "2026 Outlook. The company is reaffirming its full year 2026 outlook, which was previously updated on May 7, 2026. "
        "The Company expects full year revenue between $130 million and $150 million.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 130.0]
    assert revenue and all(f.role is GuidanceFactRole.CURRENT for f in revenue)


def test_branded_net_sales_is_product_scope():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "BRAND",
        "We have raised our 2026 ARCALYST net sales guidance to between $980 million and $995 million.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert revenue and all(f.scope_kind is GuidanceScopeKind.PRODUCT for f in revenue)


def test_unscaled_range_endpoint_shadow_is_suppressed():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "SCALE2",
        "For full year 2026, we are raising our revenue guidance to between $8.150 – $8.158 billion. "
        "Full year 2026 revenue guidance is $8.150 billion to $8.158 billion.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert all(not (f.unit.value == "USD" and f.low == f.high == 8.15) for f in revenue)


def test_yoy_result_tail_is_historical_not_forward_guidance():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ACTUALTAIL",
        "Adjusted EBITDA was $102.6 million, up 11.5% year-over-year. Raising 2025 Guidance. "
        "Full-year 2025 Adjusted EBITDA guidance is $470 million to $495 million.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert all(not (f.low == f.high == 102.6) for f in ebitda)
    assert any((f.low, f.high) == (470.0, 495.0) for f in ebitda)


def test_compact_suffix_ranges_bind_to_their_own_metric():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "COMPACT",
        "Raised full-year 2025 guidance to: $452 - $458 million revenue; $138.5 - $141.5 million Adjusted EBITDA.",
    ))
    rev = [f for f in ex.facts if f.metric.value == "revenue"]
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert any((f.low, f.high) == (452.0, 458.0) for f in rev)
    assert any((f.low, f.high) == (138.5, 141.5) for f in ebitda)
    assert all((f.low, f.high) != (138.5, 141.5) for f in rev)


def test_breakeven_range_preserves_zero_lower_bound():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "BREAKEVEN",
        "Full year 2025 guidance: Adjusted EBITDA is expected to be between breakeven and $10 million.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert any((f.low, f.high) == (0.0, 10.0) for f in ebitda)


def test_adjusted_gaap_eps_contradiction_is_rejected():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "BASIS",
        "FY 2026 Guidance. Affirms Adjusted FY 2026 GAAP EPS guidance of at least $9.00; "
        "while revising GAAP EPS guidance to at least $8.36.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps"]
    assert all(not (f.accounting_basis == "GAAP" and f.low == 9.0) for f in eps)
    assert any(item["reason"] == "ambiguous_accounting_basis" for item in ex.rejected_candidates)
''')
