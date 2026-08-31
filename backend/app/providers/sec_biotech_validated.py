from __future__ import annotations

from datetime import UTC, date, datetime

from app.domain.schemas import FieldProvenance, FundamentalSnapshot
from app.providers.errors import ProviderError
from app.providers.sec_biotech_fallback import SecBiotechLiquidityFallbackProvider


class SecBiotechValidatedProvider(SecBiotechLiquidityFallbackProvider):
    """Final 2.5I SEC biotech adapter with period-aligned financing evidence.

    The liquidity fallback can move the effective balance-sheet date forward when
    companyfacts omits a custom-tagged current investment balance. Financing must
    therefore be re-evaluated from that same effective date; otherwise an older
    companyfacts cash date could incorrectly treat already-incorporated financing
    as a post-period exception.
    """

    async def enrich_fundamental(self, ticker: str, fundamental: FundamentalSnapshot) -> FundamentalSnapshot:
        enriched = await super().enrich_fundamental(ticker, fundamental)
        raw = dict(enriched.raw)
        runway = raw.get("biotech_runway") or {}
        filing_liquidity = raw.get("biotech_filing_liquidity") or {}
        period_value = runway.get("as_of") or filing_liquidity.get("period_end")
        if not period_value:
            return enriched.model_copy(update={"financing_secured": None})
        try:
            balance_sheet_date = date.fromisoformat(str(period_value))
        except ValueError:
            return enriched.model_copy(update={"financing_secured": None})

        cik = (await self.sec.ticker_map()).get(ticker.upper().replace(".", "-"))
        if not cik:
            return enriched.model_copy(update={"financing_secured": None})

        try:
            financing, financing_raw, financing_at = await self.assess_post_period_financing(
                ticker,
                cik,
                balance_sheet_date,
            )
        except ProviderError as exc:
            financing = None
            financing_at = datetime.now(UTC)
            financing_raw = {
                "status": "SEC_FINANCING_DATA_UNAVAILABLE",
                "balance_sheet_date": balance_sheet_date.isoformat(),
                "error": exc.as_dict(),
            }

        raw["biotech_financing"] = financing_raw
        provenance = dict(enriched.field_provenance)
        provenance["financing_secured"] = FieldProvenance(
            source="SEC EDGAR period-aligned post-balance-sheet financing review",
            as_of=datetime.now(UTC),
            fetched_at=financing_at,
            stale=False,
            raw_field="filings.recent + financing-related primaryDocument after effective balance-sheet date",
        )
        return enriched.model_copy(update={
            "financing_secured": financing,
            "raw": raw,
            "field_provenance": provenance,
            "fetched_at": max(enriched.fetched_at, financing_at),
        })
