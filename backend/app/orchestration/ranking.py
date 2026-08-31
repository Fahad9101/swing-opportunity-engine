from app.domain.schemas import OpportunityResult


def rank_opportunities(items: list[OpportunityResult]) -> list[OpportunityResult]:
    return sorted(items, key=lambda item: (item.scores.opportunity_score, 1 + len(item.secondary_scanners), item.scores.technical.score or -1, item.scores.catalyst.score or -1), reverse=True)

