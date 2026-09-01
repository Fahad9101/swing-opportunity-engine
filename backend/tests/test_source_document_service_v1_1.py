from datetime import date

import httpx
import pytest

from app.domain.soe_v1_1 import SecDocumentReference
from app.services.source_document_service import (
    SourceDocumentService,
    index_submissions_payload,
    normalize_cik,
    sec_archive_url,
)


def test_normalize_cik_and_archive_url():
    assert normalize_cik(320193) == "0000320193"
    assert sec_archive_url("0000320193", "0000320193-26-000001", "aapl.htm") == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/aapl.htm"
    )


def test_index_submissions_payload_filters_forms_and_preserves_dates():
    payload = {
        "filings": {
            "recent": {
                "form": ["8-K", "4", "10-Q"],
                "accessionNumber": ["0001-26-000001", "0001-26-000002", "0001-26-000003"],
                "primaryDocument": ["a.htm", "b.htm", "c.htm"],
                "filingDate": ["2026-08-01", "2026-08-02", "2026-08-03"],
            }
        }
    }
    refs = index_submissions_payload("TEST", 1, payload)
    assert [ref.form for ref in refs] == ["8-K", "10-Q"]
    assert refs[0].filing_date == date(2026, 8, 1)
    assert refs[0].source_url.startswith("https://www.sec.gov/Archives/edgar/data/1/")


def test_sec_document_fetch_is_cached(tmp_path):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            text="<html><body>For FY2027, revenue guidance is $1.0 billion to $1.1 billion.</body></html>",
            headers={"content-type": "text/html"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = SourceDocumentService(
        cache_dir=tmp_path,
        user_agent="SwingOpportunityEngine/1.1 test@example.com",
        client=client,
    )
    ref = SecDocumentReference(
        ticker="TEST",
        cik="0000000001",
        accession="0000000001-26-000001",
        form="8-K",
        filing_date=date(2026, 8, 1),
        primary_document="test.htm",
        source_url=sec_archive_url(1, "0000000001-26-000001", "test.htm"),
    )
    first = service.fetch(ref, rules_hash="a" * 64)
    second = service.fetch(ref, rules_hash="a" * 64)
    assert calls["count"] == 1
    assert first.content_hash == second.content_hash
    assert first.content == second.content
    assert first.cache_path


def test_service_rejects_non_sec_url(tmp_path):
    service = SourceDocumentService(
        cache_dir=tmp_path,
        user_agent="SwingOpportunityEngine/1.1 test@example.com",
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="x"))),
    )
    ref = SecDocumentReference(
        ticker="TEST",
        cik="0000000001",
        accession="0000000001-26-000001",
        form="8-K",
        primary_document="test.htm",
        source_url="https://example.com/test.htm",
    )
    with pytest.raises(ValueError):
        service.fetch(ref, rules_hash="a" * 64)


def test_service_requires_declared_contact(tmp_path):
    with pytest.raises(ValueError):
        SourceDocumentService(cache_dir=tmp_path, user_agent="SwingOpportunityEngine/1.1")
