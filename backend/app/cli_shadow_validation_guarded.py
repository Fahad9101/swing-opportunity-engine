from __future__ import annotations

from app import cli_shadow_validation
from app.domain.soe_v1_1 import GuidanceMetric
from app.services import fact_extraction_service


_original_numeric_range = fact_extraction_service._numeric_range


def _guard_numeric_range(
    text: str,
    metric: GuidanceMetric,
    *,
    anchor: int,
) -> tuple[float, float, str] | None:
    """Reject structurally invalid guidance ranges instead of aborting 1.1E.

    Phase 1.1E is a shadow-validation/orchestration run. If deterministic text
    extraction produces low > high, the source fact is ambiguous and must remain
    unknown. Reordering the values would manufacture a fact, while allowing the
    Pydantic validation error to escape would terminate the full-market run.
    """
    result = _original_numeric_range(text, metric, anchor=anchor)
    if result is None:
        return None
    low, high, unit = result
    if low > high:
        return None
    return low, high, unit


def main() -> int:
    fact_extraction_service._numeric_range = _guard_numeric_range
    return cli_shadow_validation.main()


if __name__ == "__main__":
    raise SystemExit(main())
