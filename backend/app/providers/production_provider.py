from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.domain.enums import AssetType
from app.domain.schemas import Catalyst, CorporateEvent, EstimateSnapshot, FundamentalSnapshot, Instrument, OHLCVBar
from app.providers.errors import ProviderError
from app.providers.financial_datasets import FinancialDatasetsProvider
from app.providers.symbol_directory import ListedSecurity, NasdaqSymbolDirectory
from app.providers.nasdaq_calendar import NasdaqEarningsCalendar
from app.providers.cboe_vix import CboeVixProvider


def _is_biotech(sector: str | None, industry: str | None) -> bool:
    text = f"{sector or ''} {industry or ''}".lower()
    return "biotech" in text or "biological product" in text


class ProductionProvider:
    """SOE-facing composite that keeps vendor payloads out of scanners and scoring."""

    name = "production"

    def __init__(self, *, market_and_fundamentals: FinancialDatasetsProvider, symbol_directory: NasdaqSymbolDirectory, calendar: NasdaqEarningsCalendar, vix: CboeVixProvider, rules: dict[str, Any]):
        self.data = market_and_fundamentals
        self.symbol_directory = symbol_directory
        self.calendar = calendar
        self.vix = vix
        self.rules = rules
        self.provider_errors: list[dict[str, Any]] = []

    def _record(self, error: ProviderError) -> None:
        item = error.as_dict()
        item["occurred_at"] = datetime.now(UTC).isoformat()
        self.provider_errors.append(item)

    async def _instrument(self, security: ListedSecurity, market_caps: dict[str, float]) -> Instrument:
        facts: dict[str, Any] | None = None
        facts_fetched_at = security.fetched_at
        try:
            facts, facts_fetched_at = await self.data.get_company_facts(security.ticker)
        except ProviderError as exc:
            self._record(exc)
        facts = facts or {}
        provider_ticker = str(facts.get("ticker") or security.ticker).upper().replace(".", "-")
        if provider_ticker != security.ticker:
            error = ProviderError(self.data.name, "PROVIDER_SYMBOL_MISMATCH", "Company facts symbol did not match the official listing symbol.", retryable=False, ticker=security.ticker, endpoint="/company/facts")
            self._record(error)
            facts = {}
        sector = facts.get("sector") or facts.get("sic_sector")
        industry = facts.get("industry") or facts.get("sic_industry")
        return Instrument(
            ticker=security.ticker, company_name=str(facts.get("name") or security.company_name),
            exchange=security.exchange, country="US" if security.asset_type == AssetType.COMMON_STOCK else None,
            sector=sector, industry=industry, asset_type=security.asset_type,
            market_cap=market_caps.get(security.ticker), is_biotech=_is_biotech(sector, industry),
            active=security.active and bool(facts.get("is_active", True)), source=f"{security.source} + Financial Datasets",
            as_of=min(security.as_of, facts_fetched_at), fetched_at=max(security.fetched_at, facts_fetched_at),
            stale=False, symbol_source=security.source, provider_symbol=security.provider_symbol,
        )

    async def list_instruments(self) -> list[Instrument]:
        self.provider_errors.clear()
        securities = await self.symbol_directory.list_securities(self.rules["data_quality"]["cache_ttl_seconds"]["universe"])
        allowed_exchanges = set(self.rules["universe"]["allowed_exchanges"])
        allowed_types = {AssetType(value) for value in self.rules["universe"]["allowed_asset_types"]}
        securities = [item for item in securities if item.exchange in allowed_exchanges and item.asset_type in allowed_types]
        try:
            market_caps, _ = await self.data.get_market_caps()
        except ProviderError as exc:
            self._record(exc)
            market_caps = {}
        batch_size = self.rules["data_quality"]["provider"]["batch_size"]
        instruments: list[Instrument] = []
        for offset in range(0, len(securities), batch_size):
            batch = securities[offset:offset + batch_size]
            results = await asyncio.gather(*(self._instrument(item, market_caps) for item in batch), return_exceptions=True)
            for security, result in zip(batch, results, strict=True):
                if isinstance(result, Exception):
                    error = result if isinstance(result, ProviderError) else ProviderError(self.name, "UNIVERSE_NORMALIZATION_ERROR", "Unable to normalize one listed security.", retryable=False, ticker=security.ticker)
                    self._record(error)
                    continue
                instruments.append(result)
        # Exact duplicate symbols are resolved deterministically and recorded.
        deduplicated: dict[str, Instrument] = {}
        for instrument in instruments:
            if instrument.ticker in deduplicated:
                self._record(ProviderError(self.name, "DUPLICATE_UNIVERSE_SYMBOL", "Duplicate ticker removed from production universe.", retryable=False, ticker=instrument.ticker))
                continue
            deduplicated[instrument.ticker] = instrument
        return list(deduplicated.values())

    async def get_ohlcv(self, ticker: str, sessions: int = 260) -> list[OHLCVBar]:
        return await self.data.get_ohlcv(ticker, sessions)

    async def get_fundamentals(self, ticker: str) -> FundamentalSnapshot | None:
        result = await self.data.get_fundamentals(ticker)
        self.provider_errors.extend(self.data.drain_errors())
        return result

    async def get_estimates(self, ticker: str) -> EstimateSnapshot | None:
        return await self.data.get_estimates(ticker)

    async def get_catalysts(self, ticker: str) -> list[Catalyst]:
        return await self.data.get_catalysts(ticker)

    async def prefetch_calendar(self) -> None:
        await self.calendar.prefetch()
        self.provider_errors.extend(self.calendar.errors)

    async def get_calendar_events(self, ticker: str) -> list[CorporateEvent]:
        return await self.calendar.get_events(ticker)

    async def get_vix(self) -> float | None:
        return (await self.vix.get_vix_data(self.rules["data_quality"]["cache_ttl_seconds"]["regime"]))["value"]

    async def get_vix_data(self) -> dict:
        return await self.vix.get_vix_data(self.rules["data_quality"]["cache_ttl_seconds"]["regime"])

    async def get_breadth_pct(self) -> float | None:
        return None

    def drain_provider_errors(self) -> list[dict[str, Any]]:
        errors, self.provider_errors = self.provider_errors, []
        return errors
