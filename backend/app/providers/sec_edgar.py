from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.domain.schemas import FieldProvenance, FundamentalSnapshot
from app.providers.errors import ProviderError
from app.services.cache_service import JsonFileCache


TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

CONCEPTS = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
    "eps": ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"),
    "net_income": ("NetIncomeLossAvailableToCommonStockholdersBasic", "NetIncomeLoss", "ProfitLoss"),
    "operating_income": ("OperatingIncomeLoss",),
    "gross_profit": ("GrossProfit",),
    "cfo": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsForPropertyPlantAndEquipment"),
    "depreciation": ("DepreciationDepletionAndAmortization", "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment"),
    "cash": ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    "debt_current": ("LongTermDebtAndFinanceLeaseObligationsCurrent", "LongTermDebtCurrent", "ShortTermBorrowings"),
    "debt_noncurrent": ("LongTermDebtAndFinanceLeaseObligationsNoncurrent", "LongTermDebtNoncurrent"),
    "shares": ("CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"),
    "interest": ("InterestExpenseNonOperating", "InterestAndDebtExpense"),
}


def _unit_rows(payload: dict[str, Any], concepts: tuple[str, ...], units: tuple[str, ...]) -> tuple[list[dict[str, Any]], str | None]:
    facts = payload.get("facts") or {}
    for namespace in ("us-gaap", "dei"):
        namespace_facts = facts.get(namespace) or {}
        for concept in concepts:
            item = namespace_facts.get(concept) or {}
            unit_map = item.get("units") or {}
            for unit in units:
                rows = unit_map.get(unit)
                if rows:
                    return list(rows), f"{namespace}:{concept}:{unit}"
    return [], None


def _duration_days(row: dict[str, Any]) -> int | None:
    if not row.get("start") or not row.get("end"):
        return None
    try:
        return (datetime.fromisoformat(row["end"]) - datetime.fromisoformat(row["start"])).days
    except ValueError:
        return None


def _latest_by_end(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    usable: dict[str, dict[str, Any]] = {}
    for row in rows:
        end = row.get("end")
        if not end:
            continue
        existing = usable.get(end)
        if existing is None or str(row.get("filed") or "") > str(existing.get("filed") or ""):
            usable[end] = row
    return sorted(usable.values(), key=lambda item: item["end"])


def _quarterly(payload: dict[str, Any], key: str, units: tuple[str, ...] = ("USD",)) -> tuple[list[dict[str, Any]], str | None]:
    rows, concept = _unit_rows(payload, CONCEPTS[key], units)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        days = _duration_days(row)
        if days is None or row.get("form") not in {"10-Q", "10-Q/A", "10-K", "10-K/A"}:
            continue
        frame = str(row.get("frame") or "")
        if not (60 <= days <= 120) or (frame and "Q" not in frame):
            continue
        candidates.append(row)
    return _latest_by_end(candidates), concept


def _annual(payload: dict[str, Any], key: str, units: tuple[str, ...] = ("USD",)) -> tuple[list[dict[str, Any]], str | None]:
    rows, concept = _unit_rows(payload, CONCEPTS[key], units)
    candidates = [
        row
        for row in rows
        if row.get("form") in {"10-K", "10-K/A"}
        and (days := _duration_days(row)) is not None
        and 300 <= days <= 400
    ]
    return _latest_by_end(candidates), concept


def _complete_additive_quarters(payload: dict[str, Any], key: str) -> tuple[list[dict[str, Any]], str | None]:
    """Return direct fiscal quarters plus deterministically derived Q4 values.

    Revenue and net income are additive over a fiscal year. SEC companyfacts
    commonly reports Q1-Q3 as quarterly durations but the 10-K as a full-year
    duration, so Q4 is not always present as a standalone fact. For valuation
    history only, Q4 is derived as FY minus the three direct quarters when the
    periods are non-overlapping and clearly contained in the same fiscal year.
    The main SOE fundamental fields are intentionally left unchanged.
    """
    quarters, concept = _quarterly(payload, key)
    annuals, annual_concept = _annual(payload, key)
    merged = {row["end"]: dict(row) for row in quarters}

    for annual in annuals:
        if annual["end"] in merged:
            continue
        try:
            annual_start = datetime.fromisoformat(annual["start"]).date()
            annual_end = datetime.fromisoformat(annual["end"]).date()
        except (TypeError, ValueError):
            continue
        inside: list[dict[str, Any]] = []
        for row in quarters:
            try:
                start = datetime.fromisoformat(row["start"]).date()
                end = datetime.fromisoformat(row["end"]).date()
            except (TypeError, ValueError):
                continue
            if annual_start <= start <= end < annual_end:
                inside.append(row)
        inside = sorted(inside, key=lambda item: item["end"])
        if len(inside) < 3:
            continue
        first_three = inside[:3]
        try:
            quarter_sum = sum(float(row["val"]) for row in first_three)
            annual_value = float(annual["val"])
        except (TypeError, ValueError):
            continue
        derived = {
            "start": first_three[-1]["end"],
            "end": annual["end"],
            "filed": annual.get("filed"),
            "form": annual.get("form"),
            "frame": f"DERIVED_Q4:{annual.get('fy') or annual['end']}",
            "val": annual_value - quarter_sum,
            "derived": True,
        }
        merged[derived["end"]] = derived

    return sorted(merged.values(), key=lambda item: item["end"]), concept or annual_concept


def _instant(payload: dict[str, Any], key: str, units: tuple[str, ...] = ("USD",)) -> tuple[dict[str, Any] | None, str | None]:
    rows, concept = _unit_rows(payload, CONCEPTS[key], units)
    usable = [row for row in rows if row.get("end") and row.get("form") in {"10-Q", "10-Q/A", "10-K", "10-K/A"}]
    return (max(usable, key=lambda item: (item.get("end", ""), item.get("filed", ""))) if usable else None), concept


def _instant_history(payload: dict[str, Any], key: str, units: tuple[str, ...]) -> tuple[list[dict[str, Any]], str | None]:
    rows, concept = _unit_rows(payload, CONCEPTS[key], units)
    usable = [row for row in rows if row.get("end") and row.get("form") in {"10-Q", "10-Q/A", "10-K", "10-K/A"}]
    return _latest_by_end(usable), concept


def _compact_history(rows: list[dict[str, Any]], limit: int = 16) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for row in rows[-limit:]:
        try:
            value = float(row["val"])
        except (KeyError, TypeError, ValueError):
            continue
        compact.append(
            {
                "start": row.get("start"),
                "end": row.get("end"),
                "filed": row.get("filed"),
                "val": value,
                "derived": bool(row.get("derived", False)),
            }
        )
    return compact


def _growth(latest: dict[str, Any] | None, comparison: dict[str, Any] | None) -> float | None:
    if not latest or not comparison:
        return None
    old = comparison.get("val")
    if old in (None, 0):
        return None
    return float(latest["val"]) / float(old) - 1


def _same_period(rows: list[dict[str, Any]], end: str) -> dict[str, Any] | None:
    return next((row for row in reversed(rows) if row.get("end") == end), None)


def normalize_companyfacts(ticker: str, payload: dict[str, Any], *, fetched_at: datetime, max_age_hours: int) -> FundamentalSnapshot | None:
    revenue, revenue_concept = _quarterly(payload, "revenue")
    eps, eps_concept = _quarterly(payload, "eps", ("USD/shares", "USD / shares"))
    op_income, op_concept = _quarterly(payload, "operating_income")
    gross_profit, gross_concept = _quarterly(payload, "gross_profit")
    cfo, cfo_concept = _quarterly(payload, "cfo")
    capex, capex_concept = _quarterly(payload, "capex")
    depreciation, depreciation_concept = _quarterly(payload, "depreciation")
    interest, interest_concept = _quarterly(payload, "interest")
    valuation_revenue, valuation_revenue_concept = _complete_additive_quarters(payload, "revenue")
    valuation_net_income, valuation_net_income_concept = _complete_additive_quarters(payload, "net_income")
    valuation_shares, valuation_shares_concept = _instant_history(payload, "shares", ("shares",))

    latest = revenue[-1] if revenue else (op_income[-1] if op_income else None)
    if latest is None:
        return None
    latest_end = latest["end"]
    latest_date = datetime.fromisoformat(latest_end).replace(tzinfo=UTC)
    prior_q = revenue[-2] if len(revenue) >= 2 else None
    prior_y = min(revenue[:-1], key=lambda row: abs((datetime.fromisoformat(latest_end) - datetime.fromisoformat(row["end"])).days - 365), default=None)
    if prior_y and abs((datetime.fromisoformat(latest_end) - datetime.fromisoformat(prior_y["end"])).days - 365) > 70:
        prior_y = None

    latest_revenue = float(latest["val"]) if revenue else None
    latest_op = _same_period(op_income, latest_end)
    prior_op = op_income[-2] if len(op_income) >= 2 else None
    latest_gross = _same_period(gross_profit, latest_end)
    prior_gross = gross_profit[-2] if len(gross_profit) >= 2 else None
    latest_cfo, latest_capex = _same_period(cfo, latest_end), _same_period(capex, latest_end)
    fcf = float(latest_cfo["val"]) - abs(float(latest_capex["val"])) if latest_cfo and latest_capex else None
    prior_fcf = None
    if latest_cfo:
        prior_cfo = min(cfo[:-1], key=lambda row: abs((datetime.fromisoformat(latest_end) - datetime.fromisoformat(row["end"])).days - 365), default=None)
        prior_capex = _same_period(capex, prior_cfo["end"]) if prior_cfo else None
        if prior_cfo and prior_capex:
            prior_fcf = float(prior_cfo["val"]) - abs(float(prior_capex["val"]))
    fcf_growth = None if prior_fcf in (None, 0) or fcf is None else fcf / prior_fcf - 1

    latest_dep = _same_period(depreciation, latest_end)
    ebitda = float(latest_op["val"]) + float(latest_dep["val"]) if latest_op and latest_dep else None
    cash_row, cash_concept = _instant(payload, "cash")
    debt_current, debt_current_concept = _instant(payload, "debt_current")
    debt_noncurrent, debt_noncurrent_concept = _instant(payload, "debt_noncurrent")
    shares_row, shares_concept = _instant(payload, "shares", ("shares",))
    cash = float(cash_row["val"]) if cash_row else None
    debt_parts = [float(row["val"]) for row in (debt_current, debt_noncurrent) if row]
    debt = sum(debt_parts) if debt_parts else None
    interest_row = _same_period(interest, latest_end)
    interest_coverage = float(latest_op["val"]) / abs(float(interest_row["val"])) if latest_op and interest_row and float(interest_row["val"]) != 0 else None
    runway = 12 * cash / (-fcf * 4) if cash is not None and fcf is not None and fcf < 0 else None
    latest_eps = eps[-1] if eps else None
    prior_eps_y = min(eps[:-1], key=lambda row: abs((datetime.fromisoformat(latest_eps["end"]) - datetime.fromisoformat(row["end"])).days - 365), default=None) if latest_eps else None
    if latest_eps and prior_eps_y and abs((datetime.fromisoformat(latest_eps["end"]) - datetime.fromisoformat(prior_eps_y["end"])).days - 365) > 70:
        prior_eps_y = None
    stale = datetime.now(UTC) - latest_date > timedelta(hours=max_age_hours)

    values: dict[str, Any] = {
        "revenue": latest_revenue, "revenue_growth": _growth(latest, prior_y), "revenue_growth_qoq": _growth(latest, prior_q),
        "eps": float(latest_eps["val"]) if latest_eps else None, "eps_growth": _growth(latest_eps, prior_eps_y),
        "operating_margin": float(latest_op["val"]) / latest_revenue if latest_op and latest_revenue else None,
        "operating_margin_prior": float(prior_op["val"]) / float(prior_q["val"]) if prior_op and prior_q and float(prior_q["val"]) else None,
        "gross_margin": float(latest_gross["val"]) / latest_revenue if latest_gross and latest_revenue else None,
        "gross_margin_prior": float(prior_gross["val"]) / float(prior_q["val"]) if prior_gross and prior_q and float(prior_q["val"]) else None,
        "fcf": fcf, "fcf_growth": fcf_growth, "ebitda": ebitda, "cash": cash, "debt": debt,
        "net_debt": debt - cash if debt is not None and cash is not None else None, "interest_coverage": interest_coverage,
        "shares_outstanding": float(shares_row["val"]) if shares_row else None, "cash_runway_months": runway,
    }
    if values["operating_margin"] is not None and values["operating_margin_prior"] is not None:
        values["operating_margin_expansion_bps"] = (values["operating_margin"] - values["operating_margin_prior"]) * 10_000
    concepts = {
        "revenue": revenue_concept, "eps": eps_concept, "operating_margin": op_concept, "gross_margin": gross_concept,
        "fcf": f"{cfo_concept} - {capex_concept}", "ebitda": f"{op_concept} + {depreciation_concept}",
        "cash": cash_concept, "debt": f"{debt_current_concept} + {debt_noncurrent_concept}", "shares_outstanding": shares_concept,
        "interest_coverage": f"{op_concept} / {interest_concept}",
    }
    provenance = {field: FieldProvenance(source="SEC EDGAR companyfacts", as_of=latest_date, fetched_at=fetched_at, stale=stale, raw_field=concepts.get(field)) for field, value in values.items() if value is not None}
    valuation_history = {
        "revenue_quarters": _compact_history(valuation_revenue),
        "net_income_quarters": _compact_history(valuation_net_income),
        "shares_instants": _compact_history(valuation_shares),
        "concepts": {
            "revenue": valuation_revenue_concept,
            "net_income": valuation_net_income_concept,
            "shares": valuation_shares_concept,
        },
    }
    return FundamentalSnapshot(
        ticker=ticker, **values, source="SEC EDGAR companyfacts", as_of=latest_date, fetched_at=fetched_at, stale=stale,
        raw={"cik": payload.get("cik"), "entity_name": payload.get("entityName"), "period_end": latest_end, "concepts": concepts, "valuation_history": valuation_history},
        field_provenance=provenance,
    )


class SecEdgarProvider:
    name = "sec_edgar"

    def __init__(self, *, cache: JsonFileCache, zip_path: Path, user_agent: str, rules: dict[str, Any], transport: httpx.AsyncBaseTransport | None = None):
        self.cache, self.zip_path, self.user_agent, self.rules, self.transport = cache, zip_path, user_agent, rules, transport
        self._ticker_to_cik: dict[str, str] | None = None
        self._archive: zipfile.ZipFile | None = None

    async def _get_json(self, url: str) -> tuple[dict[str, Any], datetime]:
        try:
            async with httpx.AsyncClient(timeout=30, transport=self.transport, headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}) as client:
                response = await client.get(url)
            response.raise_for_status()
            return response.json(), datetime.now(UTC)
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(self.name, "SEC_DATA_UNAVAILABLE", "SEC EDGAR request failed.", retryable=True, endpoint=url) from exc

    async def ticker_map(self) -> dict[str, str]:
        if self._ticker_to_cik is not None:
            return self._ticker_to_cik
        cached = self.cache.get_entry("sec-company-ticker-exchange-map")
        if cached:
            payload = cached.data
        else:
            payload, _ = await self._get_json(TICKER_MAP_URL)
            self.cache.set("sec-company-ticker-exchange-map", payload, 86400)
        fields = payload.get("fields") or []
        mapping: dict[str, str] = {}
        for values in payload.get("data") or []:
            row = dict(zip(fields, values, strict=False))
            ticker = str(row.get("ticker") or "").upper().replace(".", "-")
            if ticker and row.get("cik") is not None:
                mapping[ticker] = f"{int(row['cik']):010d}"
        self._ticker_to_cik = mapping
        return mapping

    async def get_fundamentals(self, ticker: str) -> FundamentalSnapshot | None:
        cik = (await self.ticker_map()).get(ticker.upper().replace(".", "-"))
        if not cik:
            return None
        fetched_at = datetime.now(UTC)
        if self.zip_path.exists():
            try:
                if self._archive is None:
                    self._archive = zipfile.ZipFile(self.zip_path)
                payload = json.loads(self._archive.read(f"CIK{cik}.json"))
                fetched_at = datetime.fromtimestamp(self.zip_path.stat().st_mtime, UTC)
            except (KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
                raise ProviderError(self.name, "SEC_BULK_READ_ERROR", "SEC companyfacts bulk archive could not be read for ticker.", retryable=False, ticker=ticker, endpoint=str(self.zip_path)) from exc
        else:
            payload, fetched_at = await self._get_json(COMPANYFACTS_URL.format(cik=cik))
        return normalize_companyfacts(ticker, payload, fetched_at=fetched_at, max_age_hours=self.rules["data_quality"]["staleness_hours"]["fundamentals"])
