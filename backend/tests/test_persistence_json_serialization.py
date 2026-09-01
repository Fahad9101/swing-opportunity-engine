from datetime import UTC, date, datetime
from uuid import uuid4

from app.domain.schemas import FundamentalSnapshot
from app.persistence.repositories import ScanRepository


class _CaptureSession:
    def __init__(self):
        self.added = None

    def add(self, item):
        self.added = item


def test_save_fundamental_encodes_nested_datetime_metadata():
    now = datetime(2026, 9, 1, 5, 30, 34, tzinfo=UTC)
    session = _CaptureSession()
    repo = ScanRepository(session)  # type: ignore[arg-type]
    snapshot = FundamentalSnapshot(
        ticker="NVAX",
        source="SEC EDGAR companyfacts",
        as_of=now,
        fetched_at=now,
        stale=False,
        raw={
            "valuation_reference": {
                "as_of": now,
                "period_end": date(2026, 6, 30),
                "nested": [{"fetched_at": now}],
            }
        },
    )

    repo.save_fundamental(uuid4(), snapshot)

    raw = session.added.raw_source_json
    assert raw["valuation_reference"]["as_of"] == "2026-09-01T05:30:34+00:00"
    assert raw["valuation_reference"]["period_end"] == "2026-06-30"
    assert raw["valuation_reference"]["nested"][0]["fetched_at"] == "2026-09-01T05:30:34+00:00"
