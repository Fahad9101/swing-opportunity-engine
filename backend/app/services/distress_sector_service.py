from __future__ import annotations

import re

from app.domain.distress_v1_1 import DistressSectorAdapter
from app.domain.schemas import Instrument


_BANK = re.compile(r"\b(bank|banking|banks|savings|thrift|credit union)\b", re.I)
_INSURER = re.compile(r"\b(insurance|insurer|reinsurance|reinsurer)\b", re.I)
_REIT = re.compile(r"\b(REIT|real estate investment trust)\b", re.I)
_UTILITY = re.compile(r"\b(utilities|utility|electric|gas utility|water utility|regulated power)\b", re.I)
_FINANCIAL_SECTOR = re.compile(r"\b(finance|financial|financials)\b", re.I)
_REAL_ESTATE_SECTOR = re.compile(r"\breal estate\b", re.I)


def route_distress_sector(instrument: Instrument) -> DistressSectorAdapter | None:
    """Route an issuer to the frozen SOE-1.1 distress adapter.

    Financial/real-estate issuers are never silently routed to the generic
    corporate adapter. If their available metadata cannot establish bank,
    insurer, or REIT status, the adapter is null and the distress state must
    remain UNKNOWN until better primary metadata is available.
    """

    sector = (instrument.sector or "").strip()
    industry = (instrument.industry or "").strip()
    combined = f"{sector} {industry}".strip()

    if _REIT.search(combined):
        return DistressSectorAdapter.REIT
    if _BANK.search(industry) or (_FINANCIAL_SECTOR.search(sector) and _BANK.search(combined)):
        return DistressSectorAdapter.BANK
    if _INSURER.search(industry) or (_FINANCIAL_SECTOR.search(sector) and _INSURER.search(combined)):
        return DistressSectorAdapter.INSURER
    if _UTILITY.search(sector) or _UTILITY.search(industry):
        return DistressSectorAdapter.UTILITY

    if _FINANCIAL_SECTOR.search(sector) or _REAL_ESTATE_SECTOR.search(sector):
        return None

    return DistressSectorAdapter.CORPORATE
