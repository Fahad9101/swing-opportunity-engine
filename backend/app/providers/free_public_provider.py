from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.domain.enums import AssetType
from app.domain.schemas import Catalyst, CorporateEvent, EstimateSnapshot, FundamentalSnapshot, Instrument, OHLCVBar
from app.providers.cboe_vix import CboeVixProvider
from app.providers.clinical_trials import ClinicalTrialsProvider
from app.providers.errors import ProviderError
from app.providers.nasdaq_calendar import NasdaqEarningsCalendar
from app.providers.public_market_data import PublicMarketDataProvider
from app.providers.sec_edgar import SecEdgarProvider
from app.providers.symbol_directory import NasdaqSymbolDirectory


def _is_biotech(sector: str | None, industry: str | None) -> bool:
    text = f"{sector or ''} {industry or ''}".lower()
    return "biotech" in text or "biological product" in text or "biotechnology" in text


class FreePublicProvider:
    """Normalized SOE adapter for the Milestone 2.5 free/public validation stack."""

    name = "free_public"

    def __init__(self, *, symbol_directory: NasdaqSymbolDirectory, market: PublicMarketDataProvider, sec: SecEdgarProvider, calendar: NasdaqEarningsCalendar, clinical_trials: ClinicalTrialsProvider, vix: CboeVixProvider, rules: dict[str, Any]):
        self.symbol_directory, self.market, self.sec = symbol_directory, market, sec
        self.calendar, self.clinical_trials, self.vix, self.rules = calendar, clinical_trials, vix, rules
        self.provider_errors: list[dict[str, Any]] = []
        self._instruments: dict[str, Instrument] = {}

    def _record(self, error: ProviderError) -> None:
        self.provider_errors.append(error.as_dict() | {"occurred_at": datetime.now(UTC).isoformat()})

    async def list_instruments(self) -> list[Instrument]:
        self.provider_errors.clear()
        securities = await self.symbol_directory.list_securities(self.rules["data_quality"]["cache_ttl_seconds"]["universe"])
        allowed_exchanges = set(self.rules["universe"]["allowed_exchanges"])
        allowed_types = {AssetType(value) for value in self.rules["universe"]["allowed_asset_types"]}
        securities = [item for item in securities if item.exchange in allowed_exchanges and item.asset_type in allowed_types and item.active]
        try:
            metadata, metadata_at = await self.market.get_metadata()
        except ProviderError as exc:
            self._record(exc)
            metadata, metadata_at = {}, datetime.now(UTC)
        deduplicated: dict[str, Instrument] = {}
        for security in securities:
            if security.ticker in deduplicated:
                self._record(ProviderError(self.name, "DUPLICATE_UNIVERSE_SYMBOL", "Duplicate ticker removed from official universe.", retryable=False, ticker=security.ticker))
                continue
            meta = metadata.get(security.ticker) or {}
            sector, industry = meta.get("sector"), meta.get("industry")
            display_name = str(meta.get("name") or security.company_name)
            asset_type = security.asset_type
            name_upper = display_name.upper()
            depositary_name = "DEPOSITARY" in name_upper or " ADR" in name_upper or " ADS" in name_upper
            if asset_type == AssetType.COMMON_STOCK and depositary_name:
                asset_type = AssetType.ADR
            deduplicated[security.ticker] = Instrument(
                ticker=security.ticker, company_name=display_name, exchange=security.exchange,
                country=meta.get("country") or "US", sector=sector, industry=industry, asset_type=asset_type,
                market_cap=meta.get("market_cap"), is_biotech=_is_biotech(sector, industry), active=True,
                source="Nasdaq Trader Symbol Directory + Nasdaq public screener metadata",
                as_of=min(security.as_of, metadata_at), fetched_at=max(security.fetched_at, metadata_at), stale=False,
                symbol_source=security.source, provider_symbol=security.provider_symbol,
            )
        self._instruments = deduplicated
        return list(deduplicated.values())

    async def prefetch_market_data(self, instruments: list[Instrument]) -> None:
        await self.market.prefetch(["SPY", "QQQ", "IWM", *[item.ticker for item in instruments]])
        self.provider_errors.extend(self.market.errors)
        self.market.errors.clear()

    async def get_ohlcv(self, ticker: str, sessions: int = 260) -> list[OHLCVBar]:
        return await self.market.get_ohlcv(ticker, sessions)

    async def get_fundamentals(self, ticker: str) -> FundamentalSnapshot | None:
        return await self.sec.get_fundamentals(ticker)

    async def get_estimates(self, ticker: str) -> EstimateSnapshot | None:
        return None

    async def get_catalysts(self, ticker: str) -> list[Catalyst] | None:
        # Free public sources provide event metadata, not SOE's scored A/B catalyst inputs.
        return None

    async def prefetch_calendar(self) -> None:
        await self.calendar.prefetch()
        self.provider_errors.extend(self.calendar.errors)

    async def get_calendar_events(self, ticker: str) -> list[CorporateEvent]:
        return await self.calendar.get_events(ticker)

    async def get_clinical_trial_events(self, ticker: str) -> list[CorporateEvent]:
        """On-demand deterministic trial milestones; intentionally not scored as catalysts."""
        instrument = self._instruments.get(ticker)
        if instrument and instrument.is_biotech:
            sponsor = instrument.company_name.split(" - ", 1)[0].split(", Inc.", 1)[0].split(" Inc.", 1)[0]
            try:
                return await self.clinical_trials.get_events(ticker, sponsor, self.rules["catalyst"]["max_horizon_days"])
            except ProviderError as exc:
                self._record(exc)
        return []

    async def get_vix(self) -> float | None:
        return (await self.get_vix_data()).get("value")

    async def get_vix_data(self) -> dict[str, Any]:
        return await self.vix.get_vix_data(self.rules["data_quality"]["cache_ttl_seconds"]["regime"])

    async def get_breadth_pct(self) -> float | None:
        return None

    def drain_provider_errors(self) -> list[dict[str, Any]]:
        errors, self.provider_errors = self.provider_errors, []
        return errors
