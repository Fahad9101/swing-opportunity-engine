from app.domain.schemas import ScoreBreakdown, ScoreComponent


def multi_scanner_bonus(scanner_count: int) -> int:
    return 0 if scanner_count <= 1 else 2 if scanner_count == 2 else 3


def calculate_opportunity_score(components: dict[str, ScoreComponent], penalty_points: int, scanner_count: int) -> ScoreBreakdown:
    base = sum(float(item.score or 0) for item in components.values())
    bonus = multi_scanner_bonus(scanner_count)
    adjusted = max(0, min(100, base + penalty_points + bonus))
    return ScoreBreakdown(catalyst=components["catalyst"], fundamental=components["fundamental"], valuation=components["valuation"], technical=components["technical"], revisions=components["revisions"], balance_sheet=components["balance_sheet"], liquidity=components["liquidity"], base_opportunity_score=base, penalty_points=penalty_points, multi_scanner_bonus=bonus, opportunity_score=adjusted)

