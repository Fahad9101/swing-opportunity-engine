from __future__ import annotations

from typing import Protocol

from app.domain.schemas import EstimateSnapshot


class EstimatesProvider(Protocol):
    name: str

    async def get_estimates(self, ticker: str) -> EstimateSnapshot | None: ...

