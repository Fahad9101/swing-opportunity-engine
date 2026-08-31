from app.domain.schemas import FundamentalSnapshot


def has_improving_margin(fundamental: FundamentalSnapshot | None) -> bool | None:
    if fundamental is None or fundamental.operating_margin is None or fundamental.operating_margin_prior is None:
        return None
    return fundamental.operating_margin > fundamental.operating_margin_prior


def has_improving_fcf_or_ebitda(fundamental: FundamentalSnapshot | None) -> bool | None:
    if fundamental is None:
        return None
    values = [fundamental.fcf_growth, fundamental.forward_ebitda_growth]
    known = [value for value in values if value is not None]
    return max(known) > 0 if known else None

