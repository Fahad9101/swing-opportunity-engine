from app.domain.schemas import FundamentalSnapshot, Instrument, ScoreComponent


def score_balance_sheet(instrument: Instrument, fundamental: FundamentalSnapshot | None) -> ScoreComponent:
    if fundamental is None:
        return ScoreComponent(score=None, maximum=5, available=False)
    if instrument.sector in {"Financials", "Real Estate", "Utilities"}:
        return ScoreComponent(score=None, maximum=5, available=False, components={"adapter_required": True, "sector": instrument.sector})
    cash, debt, ebitda = fundamental.cash, fundamental.debt, fundamental.ebitda
    if cash is None or debt is None:
        return ScoreComponent(score=None, maximum=5, available=False)
    if fundamental.balance_sheet_distressed is True:
        score = 0
    elif cash >= debt:
        score = 5
    elif ebitda and ebitda > 0:
        leverage = (debt - cash) / ebitda
        score = 4 if leverage <= 1 else 3 if leverage <= 2.5 else 2 if leverage <= 4 else 1
    else:
        score = 1
    return ScoreComponent(score=score, maximum=5, components={"cash": cash, "debt": debt, "ebitda": ebitda})
