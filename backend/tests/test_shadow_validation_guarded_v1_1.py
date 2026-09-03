from app.cli_shadow_validation_guarded import _guard_numeric_range
from app.domain.soe_v1_1 import GuidanceMetric


def test_guard_rejects_inverted_eps_guidance_range() -> None:
    text = "FY2027 adjusted EPS guidance $2.50 to $2.00"

    result = _guard_numeric_range(text, GuidanceMetric.EPS, anchor=text.index("EPS"))

    assert result is None


def test_guard_preserves_valid_eps_guidance_range() -> None:
    text = "FY2027 adjusted EPS guidance $2.00 to $2.50"

    result = _guard_numeric_range(text, GuidanceMetric.EPS, anchor=text.index("EPS"))

    assert result == (2.0, 2.5, "USD/share")
