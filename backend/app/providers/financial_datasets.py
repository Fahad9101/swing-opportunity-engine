from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from app.domain.enums import CatalystGrade
from app.domain.schemas import Catalyst, EstimateSnapshot, FieldProvenance, FundamentalSnapshot, OHLCVBar
from app.providers.errors import ProviderError
from app.providers.http_client import FetchedJson, ResilientJsonClient
from app.services.cache_service import JsonFileCache


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _stale(as_of: datetime, fetched_at: datetime, max_age_hours: int) -> bool:
    return fetched_at - as_of > timedelta(hours=max_age_hours)


def normalize_prices(payload: dict[str, Any], *, requested_ticker: str) -> list[OHLCVBar]:
    returned = str(payload.get("ticker") or requested_ticker).upper().replace(".", "-")
    requested = requested_ticker.upper().replace(".", "-")
    if returned != requested:
        raise ProviderError("financial_datasets", "PROVIDER_SYMBOL_MISMATCH", "Provider returned data for a different symbol.", retryable=False, ticker=requested_ticker, endpoint="/prices")
    bars: dict[date, OHLCVBar] = {}
    for row in payload.get("prices") or []:
        day = _date(row.get("time"))
        values = [_number(row.get(key)) for key in ("open", "high", "low", "close", "volume")]
        if day is None or any(value is None for value in values):
            continue
        open_, high, low, close, volume = values
        if min(open_, high, low, close) <= 0 or volume < 0 or high < max(open_, close, low) or low > min(open_, close, high):
            continue
        bars[day] = OHLCVBar(date=day, open=open_, high=high, low=low, close=close, volume=volume)
    return [bars[day] for day in sorted(bars)]


def normalize_fundamentals(
    ticker: str,
    metric_payload: dict[str, Any] | None,
    income_payload: dict[str, Any] | None,
    balance_payload: dict[str, Any] | None,
    cashflow_payload: dict[str, Any] | None,
    *,
    fetched_at: datetime,
    max_age_hours: int,
) -> FundamentalSnapshot | None:
    metrics = (metric_payload or {}).get("snapshot") or {}
    income = list((income_payload or {}).get("income_statements") or [])
    balance = list((balance_payload or {}).get("balance_sheets") or [])
    cashflow = list((cashflow_payload or {}).get("cash_flow_statements") or [])
    if not metrics and not income and not balance and not cashflow:
        return None
    income.sort(key=lambda row: str(row.get("report_period") or ""), reverse=True)
    balance.sort(key=lambda row: str(row.get("report_period") or ""), reverse=True)
    cashflow.sort(key=lambda row: str(row.get("report_period") or ""), reverse=True)
    latest_i = income[0] if income else {}
    prior_i = income[1] if len(income) > 1 else {}
    latest_b = balance[0] if balance else {}
    latest_c = cashflow[0] if cashflow else {}
    report_dates = [_date(row.get("report_period")) for row in (latest_i, latest_b, latest_c)]
    report_dates = [value for value in report_dates if value]
    as_of_day = max(report_dates) if report_dates else fetched_at.date()
    as_of = datetime.combine(as_of_day, time.min, tzinfo=UTC)

    revenue = _number(latest_i.get("revenue"))
    prior_revenue = _number(prior_i.get("revenue"))
    qoq = None if revenue is None or prior_revenue in (None, 0) else revenue / prior_revenue - 1
    operating_margin = None if revenue in (None, 0) else (_number(latest_i.get("operating_income")) or 0) / revenue
    prior_operating_margin = None if prior_revenue in (None, 0) else (_number(prior_i.get("operating_income")) or 0) / prior_revenue
    gross_margin = None if revenue in (None, 0) else (_number(latest_i.get("gross_profit")) or 0) / revenue
    prior_gross_margin = None if prior_revenue in (None, 0) else (_number(prior_i.get("gross_profit")) or 0) / prior_revenue
    cash = _number(latest_b.get("cash_and_equivalents"))
    debt = _number(latest_b.get("total_debt"))
    ebit = _number(latest_i.get("ebit"))
    da = _number(latest_c.get("depreciation_and_amortization"))
    ebitda = None if ebit is None or da is None else ebit + da

    raw_fields: dict[str, tuple[str, Any]] = {
        "revenue_growth": ("snapshot.revenue_growth", metrics.get("revenue_growth")),
        "eps_growth": ("snapshot.earnings_per_share_growth", metrics.get("earnings_per_share_growth")),
        "fcf_growth": ("snapshot.free_cash_flow_growth", metrics.get("free_cash_flow_growth")),
        "forward_ebitda_growth": ("snapshot.ebitda_growth", metrics.get("ebitda_growth")),
        "eps": ("snapshot.earnings_per_share", metrics.get("earnings_per_share")),
        "interest_coverage": ("snapshot.interest_coverage", metrics.get("interest_coverage")),
        "fcf": ("cash_flow_statements[0].free_cash_flow", latest_c.get("free_cash_flow")),
        "cash": ("balance_sheets[0].cash_and_equivalents", cash),
        "debt": ("balance_sheets[0].total_debt", debt),
        "shares_outstanding": ("balance_sheets[0].outstanding_shares", latest_b.get("outstanding_shares")),
    }
    provenance = {
        field: FieldProvenance(source="Financial Datasets", as_of=as_of, fetched_at=fetched_at, stale=_stale(as_of, fetched_at, max_age_hours), raw_field=raw_field)
        for field, (raw_field, value) in raw_fields.items() if value is not None
    }
    stale = _stale(as_of, fetched_at, max_age_hours)
    return FundamentalSnapshot(
        ticker=ticker, revenue_growth=_number(metrics.get("revenue_growth")), revenue_growth_qoq=qoq,
        eps_growth=_number(metrics.get("earnings_per_share_growth")), eps=_number(metrics.get("earnings_per_share")),
        fcf_growth=_number(metrics.get("free_cash_flow_growth")), forward_ebitda_growth=_number(metrics.get("ebitda_growth")),
        operating_margin=operating_margin if operating_margin is not None else _number(metrics.get("operating_margin")),
        operating_margin_prior=prior_operating_margin, gross_margin=gross_margin if gross_margin is not None else _number(metrics.get("gross_margin")),
        gross_margin_prior=prior_gross_margin,
        operating_margin_expansion_bps=None if operating_margin is None or prior_operating_margin is None else (operating_margin - prior_operating_margin) * 10_000,
        fcf=_number(latest_c.get("free_cash_flow")), ebitda=ebitda, cash=cash, debt=debt,
        net_debt=None if cash is None or debt is None else debt - cash, interest_coverage=_number(metrics.get("interest_coverage")),
        shares_outstanding=_number(latest_b.get("outstanding_shares")),
        source="Financial Datasets", as_of=as_of, fetched_at=fetched_at, stale=stale,
        raw={"financial_metrics": metrics, "latest_income_statement": latest_i, "latest_balance_sheet": latest_b, "latest_cash_flow_statement": latest_c},
        field_provenance=provenance,
    )


class FinancialDatasetsProvider:
    """Vendor adapter. Provider-native JSON never crosses this boundary."""

    name = "financial_datasets"

    def __init__(self, *, api_key: str, base_url: str, cache: JsonFileCache, rules: dict[str, Any], transport: httpx.AsyncBaseTransport | None = None):
        if not api_key:
            raise ValueError("FINANCIAL_DATASETS_API_KEY is required for production mode")
        quality = rules["data_quality"]
        provider = quality["provider"]
        self.rules = rules
        self.ttl = quality["cache_ttl_seconds"]
        self.staleness = quality["staleness_hours"]
        self.errors: list[dict[str, Any]] = []
        self.client = ResilientJsonClient(
            provider=self.name, base_url=base_url, headers={"X-API-KEY": api_key}, cache=cache,
            timeout_seconds=provider["timeout_seconds"], max_retries=provider["max_retries"],
            initial_backoff_seconds=provider["initial_backoff_seconds"], max_concurrency=provider["max_concurrency"], transport=transport,
        )

    def drain_errors(self) -> list[dict[str, Any]]:
        errors, self.errors = self.errors, []
        return errors

    async def get_company_facts(self, ticker: str) -> tuple[dict[str, Any] | None, datetime]:
        result = await self.client.request_json_with_metadata("GET", "/company/facts", params={"ticker": ticker}, cache_key=f"facts:{ticker}", ttl_seconds=self.ttl["fundamentals"], ticker=ticker)
        data = result.data if isinstance(result.data, dict) else {}
        facts = data.get("company_facts")
        if facts and str(facts.get("ticker", ticker)).upper().replace(".", "-") != ticker.upper().replace(".", "-"):
            raise ProviderError(self.name, "PROVIDER_SYMBOL_MISMATCH", "Company facts were returned for a different symbol.", retryable=False, ticker=ticker, endpoint="/company/facts")
        return facts, result.fetched_at

    async def get_market_cap(self, ticker: str) -> tuple[float | None, datetime]:
        result = await self.client.request_json_with_metadata("GET", "/financial-metrics/snapshot", params={"ticker": ticker}, cache_key=f"metrics:{ticker}", ttl_seconds=self.ttl["fundamentals"], ticker=ticker)
        data = result.data if isinstance(result.data, dict) else {}
        return _number((data.get("snapshot") or {}).get("market_cap")), result.fetched_at

    async def get_market_caps(self) -> tuple[dict[str, float], datetime]:
        result = await self.client.request_json_with_metadata(
            "POST", "/financials/search/screener",
            payload={"filters": [{"field": "market_cap", "operator": "gte", "value": 0}], "limit": 15000},
            cache_key="market-caps", ttl_seconds=self.ttl["fundamentals"],
        )
        data = result.data if isinstance(result.data, dict) else {}
        values: dict[str, float] = {}
        for row in data.get("search_results") or []:
            ticker = str(row.get("ticker") or "").upper().replace(".", "-")
            value = _number(row.get("market_cap"))
            if ticker and value is not None:
                values[ticker] = value
        return values, result.fetched_at

    async def get_ohlcv(self, ticker: str, sessions: int = 260) -> list[OHLCVBar]:
        end = date.today()
        start = end - timedelta(days=max(400, int(sessions * 1.7)))
        result = await self.client.request_json_with_metadata("GET", "/prices", params={"ticker": ticker, "interval": "day", "start_date": start.isoformat(), "end_date": end.isoformat()}, cache_key=f"ohlcv:{ticker}:{start}:{end}", ttl_seconds=self.ttl["ohlcv"], ticker=ticker)
        payload = result.data if isinstance(result.data, dict) else {}
        rows = list(payload.get("prices") or [])
        next_url = payload.get("next_page_url")
        page = 1
        while next_url and len(rows) < sessions and page < 10:
            parsed = urlparse(next_url)
            cursor = (parse_qs(parsed.query).get("cursor") or [None])[0]
            if not cursor:
                break
            following = await self.client.request_json("GET", "/prices", params={"cursor": cursor}, cache_key=f"ohlcv:{ticker}:page:{cursor}", ttl_seconds=self.ttl["ohlcv"], ticker=ticker)
            if not isinstance(following, dict):
                break
            rows.extend(following.get("prices") or [])
            next_url = following.get("next_page_url")
            page += 1
        bars = normalize_prices({"ticker": payload.get("ticker", ticker), "prices": rows}, requested_ticker=ticker)
        return bars[-sessions:]

    async def get_fundamentals(self, ticker: str) -> FundamentalSnapshot | None:
        specs = (
            ("metric", "/financial-metrics/snapshot", {"ticker": ticker}),
            ("income", "/financials/income-statements", {"ticker": ticker, "period": "quarterly", "limit": 5}),
            ("balance", "/financials/balance-sheets", {"ticker": ticker, "period": "quarterly", "limit": 2}),
            ("cashflow", "/financials/cash-flow-statements", {"ticker": ticker, "period": "ttm", "limit": 1}),
        )
        async def fetch(label: str, path: str, params: dict[str, Any]) -> tuple[str, FetchedJson | ProviderError]:
            try:
                value = await self.client.request_json_with_metadata("GET", path, params=params, cache_key=f"fundamentals:{label}:{ticker}", ttl_seconds=self.ttl["fundamentals"], ticker=ticker)
                return label, value
            except ProviderError as exc:
                return label, exc
        results = dict(await asyncio.gather(*(fetch(*spec) for spec in specs)))
        successful = {key: value for key, value in results.items() if isinstance(value, FetchedJson)}
        if not successful:
            first = next(iter(results.values()))
            if isinstance(first, ProviderError):
                raise first
            return None
        for value in results.values():
            if isinstance(value, ProviderError):
                item = value.as_dict()
                item["occurred_at"] = datetime.now(UTC).isoformat()
                self.errors.append(item)
        fetched_at = min(value.fetched_at for value in successful.values())
        payload = lambda key: successful[key].data if key in successful and isinstance(successful[key].data, dict) else None
        return normalize_fundamentals(ticker, payload("metric"), payload("income"), payload("balance"), payload("cashflow"), fetched_at=fetched_at, max_age_hours=self.staleness["fundamentals"])

    async def get_estimates(self, ticker: str) -> EstimateSnapshot | None:
        # Financial Datasets does not expose forward consensus or revision-history fields.
        return None

    async def get_catalysts(self, ticker: str) -> list[Catalyst]:
        # The provider's earnings endpoint is historical SEC filing data, not a future event calendar.
        return []

    async def get_vix(self) -> float | None:
        bars = await self.get_ohlcv("VIX", 5)
        return bars[-1].close if bars else None

    async def get_breadth_pct(self) -> float | None:
        return None
