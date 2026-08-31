from __future__ import annotations

from typing import Protocol

from app.domain.schemas import FundamentalSnapshot


class FundamentalsProvider(Protocol):
    name: str

    async def get_fundamentals(self, ticker: str) -> FundamentalSnapshot | None: ...

