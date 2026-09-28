from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("America/New_York")
NIGHTLY_SCAN_TIME = time(17, 30)
# Matches the nightly-scan workflow timeout (330 minutes) with a little headroom.
SCAN_GRACE = timedelta(hours=6)


def _as_utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes; the pipeline stores UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def scheduled_runs_before(now: datetime, count: int = 2) -> list[datetime]:
    """Most recent weekday 17:30 ET nightly-scan start times at or before `now`, newest first."""
    local = _as_utc(now).astimezone(MARKET_TZ)
    day = local.date()
    runs: list[datetime] = []
    while len(runs) < count:
        start = datetime.combine(day, NIGHTLY_SCAN_TIME, tzinfo=MARKET_TZ)
        if day.weekday() < 5 and start <= local:
            runs.append(start.astimezone(UTC))
        day -= timedelta(days=1)
    return runs


def is_stale(completed_at: datetime | None, now: datetime | None = None) -> bool:
    """Stale when the newest completed scan predates the run that should have finished by now.

    While tonight's scan is inside its grace window, the prior night's result is still fresh.
    Market holidays are not modeled, so the morning after a holiday can read stale.
    """
    if completed_at is None:
        return True
    now = _as_utc(now or datetime.now(UTC))
    latest, previous = scheduled_runs_before(now)
    expected = latest if now - latest >= SCAN_GRACE else previous
    return _as_utc(completed_at) < expected
