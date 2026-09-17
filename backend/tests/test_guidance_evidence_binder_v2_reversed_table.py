from app.services.guidance_evidence_binder_v2 import _mixed_quarter_full_year_guidance_table


def test_shak_reversed_flattened_table_is_detected():
    text = (
        "Revenue Adjusted EBITDA Adjusted Pro Forma Tax Rate "
        "$1.6b - $1.7b $57.0m - $59.0m 22.0% - 23.0% "
        "$124m - $128m Q2 2026 Guidance FY 2026 Guidance Three Year Financial Targets"
    )
    assert _mixed_quarter_full_year_guidance_table(text)


def test_forward_flattened_table_remains_detected():
    text = (
        "Q2 2026 Guidance FY 2026 Guidance Revenue $424m $428m $1.6b $1.7b "
        "Adjusted EBITDA $57m $59m $230m $245m"
    )
    assert _mixed_quarter_full_year_guidance_table(text)


def test_separate_narrative_quarter_and_fy_sections_are_not_blocked():
    text = (
        "Q2 2026 Guidance Revenue is expected to be $424m to $428m. "
        "Management also updated FY 2026 Guidance Revenue to $1.6b to $1.7b."
    )
    assert not _mixed_quarter_full_year_guidance_table(text)


def test_adjacent_headers_without_dense_table_are_not_blocked():
    text = "Q2 2026 Guidance FY 2026 Guidance Revenue expected to be approximately $1.6b."
    assert not _mixed_quarter_full_year_guidance_table(text)
