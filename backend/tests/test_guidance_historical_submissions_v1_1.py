from datetime import date

from app.cli_guidance_validation import (
    _archive_file_overlaps_cutoff,
    _index_archived_submissions_payload,
)


def test_archive_file_overlap_uses_sec_metadata_dates():
    cutoff = date(2024, 11, 20)
    assert _archive_file_overlaps_cutoff(
        {"name": "CIK0000000001-submissions-001.json", "filingFrom": "2024-01-01", "filingTo": "2025-01-15"},
        cutoff,
    )
    assert not _archive_file_overlaps_cutoff(
        {"name": "CIK0000000001-submissions-002.json", "filingFrom": "2023-01-01", "filingTo": "2024-10-31"},
        cutoff,
    )


def test_archive_file_overlap_is_conservative_when_dates_missing():
    assert _archive_file_overlaps_cutoff({"name": "CIK0000000001-submissions-001.json"}, date(2025, 1, 1))


def test_index_archived_submissions_payload_reads_top_level_arrays():
    payload = {
        "form": ["8-K", "4", "10-Q", "6-K"],
        "accessionNumber": [
            "0000000001-24-000001",
            "0000000001-24-000002",
            "0000000001-24-000003",
            "0000000001-24-000004",
        ],
        "primaryDocument": ["a.htm", "b.htm", "c.htm", "d.htm"],
        "filingDate": ["2024-12-01", "2024-12-02", "2024-12-03", "2024-12-04"],
    }
    refs = _index_archived_submissions_payload("TEST", "0000000001", payload)
    assert [ref.form for ref in refs] == ["8-K", "10-Q", "6-K"]
    assert refs[0].filing_date == date(2024, 12, 1)
    assert refs[0].source_url.endswith("/000000000124000001/a.htm")


def test_index_archived_submissions_payload_skips_missing_accession_or_document():
    payload = {
        "form": ["8-K", "8-K"],
        "accessionNumber": ["", "0000000001-24-000002"],
        "primaryDocument": ["a.htm", ""],
        "filingDate": ["2024-12-01", "2024-12-02"],
    }
    assert _index_archived_submissions_payload("TEST", "0000000001", payload) == []
