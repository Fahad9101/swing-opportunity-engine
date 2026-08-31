from app.domain.schemas import FundamentalSnapshot, MarketSnapshot, ScoreComponent


def score_liquidity(market: MarketSnapshot, fundamental: FundamentalSnapshot | None) -> ScoreComponent:
    adv = market.avg_dollar_volume_20d
    dollar = 3 if adv > 100_000_000 else 2.5 if adv >= 30_000_000 else 2 if adv >= 10_000_000 else 1 if adv >= 5_000_000 else 0
    ownership = None if fundamental is None else fundamental.institutional_ownership
    institutional = None if ownership is None else 2 if ownership > 0.50 else 1.5 if ownership >= 0.30 else 1 if ownership >= 0.10 else 0
    total = dollar + (institutional or 0)
    return ScoreComponent(score=total, maximum=5, available=True, available_points=5 if institutional is not None else 3, components={"dollar_volume": dollar, "institutional_ownership": institutional, "institutional_ownership_available": institutional is not None})
