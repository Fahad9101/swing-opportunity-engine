from __future__ import annotations

from typing import Protocol

from app.domain.schemas import Instrument, OHLCVBar


class MarketDataProvider(Protocol):
    name: str

    async def list_instruments(self) -> list[Instrument]: ...

    async def get_ohlcv(self, ticker: str, sessions: int = 260) -> list[OHLCVBar]: ...

    async def get_vix(self) -> float | None: ...

    async def get_breadth_pct(self) -> float | None: ...

