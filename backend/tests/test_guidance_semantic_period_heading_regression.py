from app.services.guidance_semantic_ownership_service import _explicit_period_mentions


def test_explicit_quarter_heading_does_not_create_overlapping_full_year_owner():
    mentions = _explicit_period_mentions("Third Quarter 2026 Guidance: Revenue $26 million to $30 million.")
    periods = [period for period, _start, _end in mentions]
    assert "Q3FY2026" in periods
    assert "FY2026" not in periods


def test_standalone_year_guidance_remains_full_year_owner():
    mentions = _explicit_period_mentions("2026 Guidance: Revenue $119 million to $123 million.")
    periods = [period for period, _start, _end in mentions]
    assert periods == ["FY2026"]
