from datetime import UTC, datetime

from app.core.freshness import is_stale, scheduled_runs_before


def utc(*args):
    return datetime(*args, tzinfo=UTC)


def test_scheduled_runs_skip_weekends_and_follow_daylight_saving():
    # Monday 2026-09-28 12:00 ET (EDT, UTC-4): last runs are Fri 09-25 and Thu 09-24 at 21:30 UTC.
    assert scheduled_runs_before(utc(2026, 9, 28, 16, 0)) == [utc(2026, 9, 25, 21, 30), utc(2026, 9, 24, 21, 30)]
    # Tuesday 2026-12-01 18:00 ET (EST, UTC-5): today's run started at 22:30 UTC.
    assert scheduled_runs_before(utc(2026, 12, 1, 23, 0)) == [utc(2026, 12, 1, 22, 30), utc(2026, 11, 30, 22, 30)]


def test_previous_nights_scan_is_fresh_while_tonights_runs():
    now = utc(2026, 9, 29, 23, 0)  # Tue 19:00 ET, tonight's scan in progress
    assert not is_stale(utc(2026, 9, 28, 23, 45), now)


def test_missed_nightly_run_is_stale():
    now = utc(2026, 9, 30, 14, 0)  # Wed 10:00 ET; Tue night's scan never completed
    assert is_stale(utc(2026, 9, 28, 23, 45), now)


def test_friday_scan_is_fresh_over_the_weekend():
    assert not is_stale(utc(2026, 9, 26, 0, 30), utc(2026, 9, 27, 18, 0))


def test_naive_timestamps_are_treated_as_utc_and_missing_is_stale():
    assert not is_stale(datetime(2026, 9, 28, 23, 45), utc(2026, 9, 29, 23, 0))
    assert is_stale(None)
