from __future__ import annotations

from typing import Protocol

from app.domain.schemas import Catalyst


class CalendarProvider(Protocol):
    name: str

    async def get_catalysts(self, ticker: str) -> list[Catalyst]: ...

