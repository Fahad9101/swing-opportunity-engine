from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")


def latest_expected_completed_session(now: datetime | None = None) -> date:
    """Weekday-aware EOD freshness boundary for prototype validation.

    Exchange holidays remain a documented limitation; weekends and a still-open U.S.
    session no longer create false stale-price flags.
    """
    moment = (now or datetime.now(UTC)).astimezone(NEW_YORK)
    candidate = moment.date()
    if moment.weekday() < 5 and moment.time() < time(16, 0):
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def is_eod_stale(as_of: datetime, now: datetime | None = None) -> bool:
    return as_of.date() < latest_expected_completed_session(now)
