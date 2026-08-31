from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.schemas import Catalyst, EstimateSnapshot, FundamentalSnapshot, Instrument, MarketSnapshot, ScannerMatch


class BaseScreener(ABC):
    @abstractmethod
    def evaluate(self, instrument: Instrument, market: MarketSnapshot, fundamental: FundamentalSnapshot | None, estimates: EstimateSnapshot | None, catalysts: list[Catalyst], rules: dict) -> ScannerMatch:
        raise NotImplementedError


def count_conditions(conditions: dict[str, bool | None]) -> tuple[int, int]:
    return sum(value is True for value in conditions.values()), len(conditions)

