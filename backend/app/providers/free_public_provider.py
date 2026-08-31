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
from app.providers.sec_biotech import SecBiotechIntelligenceProvider
from app.providers.sec_edgar import SecEdgarProvider
from app.providers.symbol_directory import NasdaqSymbolDirectory
from app.providers.yahoo_analyst import YahooAnalystEstimateProvider
from app.providers.yahoo_ownership import OwnershipSnapshot, YahooOwnershipProvider
from app.services.biotech_validation_service import build_biotech_validation
from app.services.catalyst_evidence_service import promote_scoring_ready_event
from app.services.valuation_service import enrich_fundamental_valuation


def _is_biotech(sector: str | None, industry: str | None) -> bool:
    text = f"{sector or ''} {industry or ''}".lower()
    return "biotech" in text or "biological product" in text or "biotechnology" in text


def _sponsor_name(company_name: str) -> str:
    name = company_name.split(" - ", 1)[0]
    for suffix in (
        ", Inc.", " Inc.", ", Inc", " Inc", " Corporation", " Corp.", " Corp", " plc", " PLC", " Limited", " Ltd.", " Ltd",
        " Common Stock", " Class A Common Stock", " Class B Common Stock", " Class C Common Stock",
    ):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.strip()


def merge_ownership_into_fundamentals(
    fundamental: FundamentalSnapshot,
    ownership: OwnershipSnapshot | None,
) -> FundamentalSnapshot:
    """Enrich SEC fundamentals without changing frozen SOE rules.

    The existing SOE-1.0.0 penalty named ``short_float_over_25`` is activated
    only when the normalized short-float fraction is strictly greater than
    0.25. Missing ownership data stay null and no penalty is synthesized.
    """
    if ownership is None:
        return fundamental

    raw = dict(fundamental.raw)
    penalty_flags = list(raw.get("penalty_flags") or [])
    if ownership.short_float is not None and ownership.short_float > 0.25:
        if not any(flag.get("code") == "short_float_over_25" for flag in penalty_flags if isinstance(flag, dict)):
            penalty_flags.append(
                {
                    "code": "short_float_over_25",
                    "reason": f"Short float {ownership.short_float:.1%} exceeds the frozen 25% threshold.",
                    "points": -2,
                    "source": ownership.source,
                    "timestamp": ownership.as_of,
                }
            )
    if penalty_flags:
        raw["penalty_flags"] = penalty_flags

    return fundamental.model_copy(
        update={
            "institutional_ownership": ownership.institutional_ownership,
            "short_float": ownership.short_float,
            "raw": raw,
            "field_provenance": {**fundamental.field_provenance, **ownership.field_provenance},
            "fetched_at": max(fundamental.fetched_at, ownership.fetched_at),
            "stale": fundamental.stale or ownership.stale,
        }
    )


class FreePublicProvider:
    """Normalized SOE adapter for the free/public validation stack.

    All provider-native payloads are normalized before reaching scanner or
    scoring code. Missing public data remain unavailable rather than being
    converted to zero or synthetic values.
    """

    name = "free_public"

    def __init__(
        self,
        *,
        symbol_directory: NasdaqSymbolDirectory,
        market: PublicMarketDataProvider,
        sec: SecEdgarProvider,
        analyst: YahooAnalystEstimateProvider,
        ownership: YahooOwnershipProvider,
        calendar: NasdaqEarningsCalendar,
        clinical_trials: ClinicalTrialsProvider,
        vix: CboeVixProvider,
        rules: dict[str, Any],
        biotech_intelligence: SecBiotechIntelligenceProvider | None = None,
    ):
        self.symbol_directory, self.market, self.sec = symbol_directory, market, sec
        self.analyst, self.ownership = analyst, ownership
        self.calendar, self.clinical_trials, self.vix, self.rules = calendar, clinical_trials, vix, rules
        self.biotech_intelligence = biotech_intelligence
        self.provider_errors: list[dict[str, Any]] = []
        self._instruments: dict[str, Instrument] = {}
        self._catalyst_evidence: dict[str, list[CorporateEvent]] = {}

    def _record(self, error: ProviderError) -> None:
        self.provider_errors.append(error.as_dict() | {"occurred_at": datetime.now(UTC).isoformat()})

    async def list_instruments(self) -> list[Instrument]:
        self.provider_errors.clear()
        self._catalyst_evidence.clear()
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
        # Yahoo chart uses the same 2-year response range for technical history.
        # Keep 520 sessions in cache so Milestone 2.5G can reuse the same request
        # for historical self-relative valuation rather than making a second
        # per-ticker market-data call.
        await self.market.prefetch(["SPY", "QQQ", "IWM", *[item.ticker for item in instruments]], sessions=520)
        self.provider_errors.extend(self.market.errors)
        self.market.errors.clear()

    async def get_ohlcv(self, ticker: str, sessions: int = 260) -> list[OHLCVBar]:
        return await self.market.get_ohlcv(ticker, sessions)

    async def get_fundamentals(self, ticker: str) -> FundamentalSnapshot | None:
        fundamental = await self.sec.get_fundamentals(ticker)
        if fundamental is None:
            return None

        try:
            ownership = await self.ownership.get_ownership(ticker)
        except ProviderError as exc:
            self._record(exc)
            ownership = None
        fundamental = merge_ownership_into_fundamentals(fundamental, ownership)

        # Valuation and biotech specialization require instrument classification.
        # Direct unit tests that bypass list_instruments() retain the valid SEC /
        # ownership record without classification-specific enrichment.
        instrument = self._instruments.get(ticker)
        if instrument is None:
            return fundamental

        is_biotech = instrument.is_biotech
        if is_biotech and self.biotech_intelligence is not None:
            try:
                fundamental = await self.biotech_intelligence.enrich_fundamental(ticker, fundamental)
            except ProviderError as exc:
                self._record(exc)

        is_adr = instrument.asset_type == AssetType.ADR
        sector = (instrument.sector or "").strip().lower()
        is_real_estate = sector == "real estate"
        is_financial = sector in {"finance", "financials", "financial services"}

        # Biotech remains outside conventional Buffett-style historical multiple
        # valuation; ADR share-ratio ambiguity and REIT/real-estate FFO gaps are
        # also left unavailable rather than forcing a misleading generic metric.
        allow_historical = not is_biotech and not is_adr and not is_real_estate
        allow_sales_fallback = allow_historical and not is_financial

        reference = None
        if not is_biotech:
            try:
                reference = await self.analyst.get_valuation_reference(ticker)
            except ProviderError as exc:
                self._record(exc)

        valuation_bars: list[OHLCVBar] = []
        if allow_historical or reference is not None:
            try:
                valuation_bars = await self.market.get_ohlcv(ticker, 520)
            except ProviderError as exc:
                self._record(exc)

        if valuation_bars:
            fundamental = enrich_fundamental_valuation(
                fundamental,
                valuation_bars,
                reference,
                allow_historical=allow_historical,
                allow_sales_fallback=allow_sales_fallback,
            )
        return fundamental

    async def get_estimates(self, ticker: str) -> EstimateSnapshot | None:
        return await self.analyst.get_estimates(ticker)

    async def get_catalyst_evidence(self, ticker: str) -> list[CorporateEvent]:
        key = ticker.upper().replace(".", "-")
        if key in self._catalyst_evidence:
            return list(self._catalyst_evidence[key])

        events = list(await self.calendar.get_events(key))
        instrument = self._instruments.get(key)
        if instrument and instrument.is_biotech:
            sponsor = _sponsor_name(instrument.company_name)
            try:
                events.extend(await self.clinical_trials.get_events(key, sponsor, self.rules["catalyst"]["max_horizon_days"]))
            except ProviderError as exc:
                self._record(exc)
        events.sort(key=lambda item: (item.window_start or item.event_date, item.type, item.title))
        self._catalyst_evidence[key] = events
        return list(events)

    async def get_catalysts(self, ticker: str) -> list[Catalyst] | None:
        # Evidence is allowed to carry the frozen A/B/C date-confidence field,
        # but it is promoted into a scored Catalyst only when materiality and
        # surprise are explicitly available. The current free/public sources do
        # not supply those numeric inputs, so missing values remain unavailable.
        evidence = await self.get_catalyst_evidence(ticker)
        promoted = [item for event in evidence if (item := promote_scoring_ready_event(event)) is not None]
        return promoted or None

    async def get_biotech_validation(self, ticker: str) -> dict[str, Any]:
        instrument = self._instruments.get(ticker.upper().replace(".", "-"))
        if instrument is None or not instrument.is_biotech:
            return {"ticker": ticker, "status": "NOT_CLASSIFIED_AS_BIOTECH"}
        fundamental = await self.get_fundamentals(instrument.ticker)
        events = await self.get_catalyst_evidence(instrument.ticker)
        return {"ticker": instrument.ticker, **build_biotech_validation(fundamental, events, self.rules)}

    async def prefetch_calendar(self) -> None:
        self._catalyst_evidence.clear()
        await self.calendar.prefetch()
        self.provider_errors.extend(self.calendar.errors)

    async def get_calendar_events(self, ticker: str) -> list[CorporateEvent]:
        # Preserve the existing pipeline interface while returning the richer
        # Milestone 2.5H evidence stream (earnings + biotech trial milestones).
        return await self.get_catalyst_evidence(ticker)

    async def get_clinical_trial_events(self, ticker: str) -> list[CorporateEvent]:
        """On-demand deterministic trial milestones; never auto-labeled as readouts."""
        instrument = self._instruments.get(ticker)
        if instrument and instrument.is_biotech:
            sponsor = _sponsor_name(instrument.company_name)
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
