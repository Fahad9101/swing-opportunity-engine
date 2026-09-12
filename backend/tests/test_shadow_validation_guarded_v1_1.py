from app.cli_shadow_validation_guarded import (
    _guard_numeric_range,
    _malformed_sec_rows,
    _safe_index_submissions_payload,
)
from app.domain.soe_v1_1 import GuidanceMetric


def test_guard_rejects_inverted_eps_guidance_range() -> None:
    text = "FY2027 adjusted EPS guidance $2.50 to $2.00"

    result = _guard_numeric_range(text, GuidanceMetric.EPS, anchor=text.index("EPS"))

    assert result is None


def test_guard_preserves_valid_eps_guidance_range() -> None:
    text = "FY2027 adjusted EPS guidance $2.00 to $2.50"

    result = _guard_numeric_range(text, GuidanceMetric.EPS, anchor=text.index("EPS"))

    assert result == (2.0, 2.5, "USD/share")


def test_safe_sec_index_skips_invalid_allowed_row_without_substitution() -> None:
    _malformed_sec_rows.clear()
    payload = {
        "filings": {
            "recent": {
                "form": ["10-Q", "10-Q"],
                "accessionNumber": ["invalid-accession", "0000123456-26-000001"],
                "primaryDocument": ["bad.htm", "valid.htm"],
                "filingDate": ["2026-08-01", "2026-08-02"],
            }
        }
    }

    refs = _safe_index_submissions_payload(
        "TEST",
        "0000123456",
        payload,
        allowed_forms={"10-Q"},
        limit=24,
    )

    assert len(refs) == 1
    assert refs[0].accession == "0000123456-26-000001"
    assert refs[0].primary_document == "valid.htm"
    assert _malformed_sec_rows["TEST"] == ["SEC_SUBMISSION_ROW_INVALID:10-Q:invalid-accession:bad.htm"]


def test_safe_sec_index_preserves_valid_rows() -> None:
    _malformed_sec_rows.clear()
    payload = {
        "filings": {
            "recent": {
                "form": ["8-K"],
                "accessionNumber": ["0000123456-26-000002"],
                "primaryDocument": ["report.htm"],
                "filingDate": ["2026-08-03"],
            }
        }
    }

    refs = _safe_index_submissions_payload("TEST", "0000123456", payload, allowed_forms={"8-K"}, limit=24)

    assert len(refs) == 1
    assert refs[0].source_url.endswith("/000012345626000002/report.htm")
    assert "TEST" not in _malformed_sec_rows
