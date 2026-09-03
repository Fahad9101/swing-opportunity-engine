from __future__ import annotations

from app.domain.catalyst_surprise_v1_1 import AnalystConsensusContext
from app.providers.analyst_consensus_v1_1 import normalize_yahoo_surprise_consensus
from app.providers.yahoo_analyst import YahooAnalystEstimateProvider


class YahooSurpriseConsensusProvider:
    """Additive SOE-1.1D view over the existing Yahoo prototype payload cache.

    The underlying Yahoo adapter remains unchanged so SOE-1.0.0 estimate
    behavior is byte-for-byte unaffected. This wrapper only exposes extra
    range/instability fields needed by the candidate SOE-1.1D model.
    """

    name = "yahoo_surprise_consensus_prototype"

    def __init__(self, analyst_provider: YahooAnalystEstimateProvider) -> None:
        self.analyst_provider = analyst_provider

    async def get_consensus(
        self,
        ticker: str,
        *,
        event_type: str,
    ) -> tuple[AnalystConsensusContext | None, AnalystConsensusContext | None]:
        payload, fetched_at = await self.analyst_provider._payload(ticker)
        return normalize_yahoo_surprise_consensus(
            ticker,
            payload,
            event_type=event_type,
            fetched_at=fetched_at,
            max_age_hours=self.analyst_provider.rules["data_quality"]["staleness_hours"]["estimates"],
        )
