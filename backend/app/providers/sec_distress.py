from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.domain.distress_v1_1 import DistressRawFacts, DistressSectorAdapter


_CASH = ("CashAndCashEquivalentsAtCarryingValue",)
_MARKETABLE = ("ShortTermInvestments", "MarketableSecuritiesCurrent")
_LIQUID_TOTAL = ("CashCashEquivalentsAndShortTermInvestments",)

_LT_DEBT_TOTAL = ("LongTermDebtAndFinanceLeaseObligations", "LongTermDebt")
_LT_DEBT_CURRENT = ("LongTermDebtAndFinanceLeaseObligationsCurrent", "LongTermDebtCurrent")
_LT_DEBT_NONCURRENT = ("LongTermDebtAndFinanceLeaseObligationsNoncurrent", "LongTermDebtNoncurrent")
_SHORT_TERM_DEBT = ("ShortTermBorrowings", "ShortTermDebtCurrent")

_OPERATING_INCOME = ("OperatingIncomeLoss",)
_DEPRECIATION = (
    "DepreciationDepletionAndAmortization",
    "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
)
_CASH_INTEREST = ("InterestPaidNet", "InterestPaid")

_MAX_BALANCE_AGE_DAYS = 220
_MAX_ANNUAL_AGE_DAYS = 550


def _concept_rows(payload: dict[str, Any], concepts: tuple[str, ...], unit: str = "USD") -> tuple[list[dict[str, Any]], str | None]:
    """Return rows across all semantically compatible alternative concepts.

    SEC issuers frequently migrate between equivalent US-GAAP tags. Selecting the
    first concept that has *any* historical rows can therefore freeze a metric on
    an obsolete year. We merge alternatives and retain concept priority only as a
    tie-breaker for the same filing/end date.
    """
    namespace = ((payload.get("facts") or {}).get("us-gaap") or {})
    merged: list[dict[str, Any]] = []
    used: list[str] = []
    for priority, concept in enumerate(concepts):
        rows = (((namespace.get(concept) or {}).get("units") or {}).get(unit)) or []
        if not rows:
            continue
        used.append(concept)
        for row in rows:
            tagged = dict(row)
            tagged["_concept"] = concept
            tagged["_concept_priority"] = priority
            merged.append(tagged)
    label = "|".join(f"us-gaap:{concept}:{unit}" for concept in used) if used else None
    return merged, label


def _latest_by_end(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        end = row.get("end")
        if not end or row.get("form") not in {"10-Q", "10-Q/A", "10-K", "10-K/A"}:
            continue
        existing = result.get(end)
        candidate_key = (str(row.get("filed") or ""), -int(row.get("_concept_priority") or 0))
        existing_key = (
            str(existing.get("filed") or ""),
            -int(existing.get("_concept_priority") or 0),
        ) if existing is not None else None
        if existing is None or candidate_key > existing_key:
            result[end] = row
    return result


def _instant_map(payload: dict[str, Any], concepts: tuple[str, ...]) -> tuple[dict[str, float], str | None]:
    rows, concept = _concept_rows(payload, concepts)
    values: dict[str, float] = {}
    for end, row in _latest_by_end(rows).items():
        try:
            values[end] = float(row["val"])
        except (KeyError, TypeError, ValueError):
            continue
    return values, concept


def _duration_days(row: dict[str, Any]) -> int | None:
    try:
        return (datetime.fromisoformat(row["end"]) - datetime.fromisoformat(row["start"])).days
    except (KeyError, TypeError, ValueError):
        return None


def _annual_map(payload: dict[str, Any], concepts: tuple[str, ...]) -> tuple[dict[str, float], str | None]:
    rows, concept = _concept_rows(payload, concepts)
    values: dict[str, tuple[str, int, float]] = {}
    for row in rows:
        days = _duration_days(row)
        end = row.get("end")
        if not end or row.get("form") not in {"10-K", "10-K/A"} or days is None or not 300 <= days <= 400:
            continue
        try:
            value = float(row["val"])
        except (KeyError, TypeError, ValueError):
            continue
        filed = str(row.get("filed") or "")
        priority = int(row.get("_concept_priority") or 0)
        existing = values.get(end)
        candidate_key = (filed, -priority)
        existing_key = (existing[0], -existing[1]) if existing is not None else None
        if existing is None or candidate_key > existing_key:
            values[end] = (filed, priority, value)
    return {end: value for end, (_, _, value) in values.items()}, concept


def _fresh_end(end: str, fetched_at: datetime, *, max_age_days: int) -> bool:
    try:
        period_end = datetime.fromisoformat(end).date()
    except ValueError:
        return False
    age = (fetched_at.date() - period_end).days
    return -7 <= age <= max_age_days


def _debt_by_end(payload: dict[str, Any]) -> tuple[dict[str, float], dict[str, str | None]]:
    total_lt, total_concept = _instant_map(payload, _LT_DEBT_TOTAL)
    current_lt, current_concept = _instant_map(payload, _LT_DEBT_CURRENT)
    noncurrent_lt, noncurrent_concept = _instant_map(payload, _LT_DEBT_NONCURRENT)
    short_term, short_term_concept = _instant_map(payload, _SHORT_TERM_DEBT)

    ends = set(total_lt) | set(current_lt) | set(noncurrent_lt) | set(short_term)
    debt: dict[str, float] = {}
    for end in ends:
        if end in total_lt:
            amount = total_lt[end]
        else:
            components = [item.get(end) for item in (current_lt, noncurrent_lt) if end in item]
            if not components:
                continue
            amount = sum(components)
        if end in short_term:
            amount += short_term[end]
        debt[end] = amount

    return debt, {
        "long_term_total": total_concept,
        "long_term_current": current_concept,
        "long_term_noncurrent": noncurrent_concept,
        "short_term": short_term_concept,
    }


def normalize_distress_companyfacts(
    ticker: str,
    payload: dict[str, Any],
    *,
    sector_adapter: DistressSectorAdapter,
    fetched_at: datetime,
) -> DistressRawFacts:
    """Normalize current primary SEC companyfacts suitable for SOE-1.1B.

    Alternative US-GAAP concepts are merged instead of selecting whichever tag
    happens to appear first historically. Facts outside the explicit freshness
    windows are suppressed to null so an obsolete balance sheet or coverage year
    can never create a safe/distressed classification.
    """

    cash_map, cash_concept = _instant_map(payload, _CASH)
    marketable_map, marketable_concept = _instant_map(payload, _MARKETABLE)
    liquid_total_map, liquid_total_concept = _instant_map(payload, _LIQUID_TOTAL)
    debt_map, debt_concepts = _debt_by_end(payload)

    common_balance_ends = sorted(
        end
        for end in set(debt_map) & (set(cash_map) | set(liquid_total_map))
        if _fresh_end(end, fetched_at, max_age_days=_MAX_BALANCE_AGE_DAYS)
    )
    balance_end = common_balance_ends[-1] if common_balance_ends else None

    debt = debt_map.get(balance_end) if balance_end else None
    cash = cash_map.get(balance_end) if balance_end else None
    marketable = marketable_map.get(balance_end) if balance_end else None
    liquid_total = liquid_total_map.get(balance_end) if balance_end else None
    liquid_complete = liquid_total is not None or (cash is not None and marketable is not None)

    op_income_map, op_income_concept = _annual_map(payload, _OPERATING_INCOME)
    depreciation_map, depreciation_concept = _annual_map(payload, _DEPRECIATION)
    cash_interest_map, cash_interest_concept = _annual_map(payload, _CASH_INTEREST)

    annual_ends = sorted(
        end
        for end in set(op_income_map) & set(depreciation_map)
        if _fresh_end(end, fetched_at, max_age_days=_MAX_ANNUAL_AGE_DAYS)
    )
    annual_end = annual_ends[-1] if annual_ends else None
    ebit = op_income_map.get(annual_end) if annual_end else None
    ebitda = None
    if annual_end and annual_end in op_income_map and annual_end in depreciation_map:
        ebitda = op_income_map[annual_end] + depreciation_map[annual_end]
    cash_interest = cash_interest_map.get(annual_end) if annual_end else None

    as_of_dates = [item for item in (balance_end, annual_end) if item]
    as_of = max(datetime.fromisoformat(item).replace(tzinfo=UTC) for item in as_of_dates) if as_of_dates else fetched_at

    cik_value = payload.get("cik")
    try:
        cik = f"{int(cik_value):010d}"
    except (TypeError, ValueError):
        cik = str(cik_value or "").zfill(10)
    source_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json" if cik.strip("0") else "https://data.sec.gov/api/xbrl/companyfacts/"

    audit = {
        "source": "SEC EDGAR companyfacts",
        "fetched_at": fetched_at.isoformat(),
        "balance_period_end": balance_end,
        "annual_coverage_period_end": annual_end,
        "staleness_policy": {
            "balance_max_age_days": _MAX_BALANCE_AGE_DAYS,
            "annual_max_age_days": _MAX_ANNUAL_AGE_DAYS,
        },
        "concepts": {
            "cash": cash_concept,
            "marketable_securities": marketable_concept,
            "liquid_assets_total": liquid_total_concept,
            "debt": debt_concepts,
            "ebit": op_income_concept,
            "depreciation": depreciation_concept,
            "cash_interest": cash_interest_concept,
        },
        "companyfacts_limits": [
            "committed undrawn revolver not inferred",
            "12-month debt maturities not inferred from absence/presence of current debt tags",
            "REIT EBITDAre/fixed-charge coverage not inferred",
            "bank/insurer regulatory capital not inferred",
            "trailing FCF not inferred from annual companyfacts",
            "stale balance/annual facts are suppressed rather than carried forward",
        ],
    }

    return DistressRawFacts(
        ticker=ticker,
        sector_adapter=sector_adapter,
        as_of=as_of,
        debt=debt,
        cash=cash,
        marketable_securities=marketable,
        liquid_assets_total=liquid_total,
        liquid_assets_complete=liquid_complete,
        ebitda=ebitda,
        ebit=ebit,
        cash_interest_expense=abs(cash_interest) if cash_interest is not None else None,
        sources=[source_url],
        audit=audit,
    )