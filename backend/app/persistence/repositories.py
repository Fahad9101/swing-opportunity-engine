from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.schemas import Catalyst, CorporateEvent, EstimateSnapshot, FundamentalSnapshot, Instrument, MarketRegimeResult, MarketSnapshot, OpportunityResult, ScanRunState, ScannerMatch, ValidationIssue
from app.persistence.orm_models import CatalystORM, CorporateEventORM, EstimateSnapshotORM, FundamentalSnapshotORM, InstrumentORM, MarketRegimeORM, MarketSnapshotORM, OpportunityORM, ProviderErrorORM, ScanRunORM, ScannerMatchORM, ValidationIssueORM


def _json(model) -> dict:
    return model.model_dump(mode="json")


class ScanRepository:
    def __init__(self, session: Session): self.session = session

    def create_run(self, state: ScanRunState) -> None:
        self.session.add(ScanRunORM(id=str(state.scan_run_id), model_version=state.model_version, rules_hash=state.rules_hash, started_at=state.started_at, completed_at=None, status=state.status, universe_count=0, stage2_count=0, stage3_count=0, fully_scored_count=0, error_count=0))
        self.session.commit()

    def update_run_progress(self, state: ScanRunState, stage2_count: int = 0, stage3_count: int = 0) -> None:
        row = self.session.get(ScanRunORM, str(state.scan_run_id))
        if row is None: raise KeyError(state.scan_run_id)
        if row.status == "COMPLETED": raise ValueError("Completed scan runs are immutable")
        row.status, row.completed_at, row.universe_count, row.stage2_count, row.stage3_count, row.fully_scored_count, row.error_count = state.status, state.completed_at, state.universe_count, stage2_count, stage3_count, state.fully_scored_count, state.error_count
        self.session.commit()

    def upsert_instrument(self, item: Instrument) -> None:
        now = datetime.now(UTC)
        row = self.session.get(InstrumentORM, item.ticker)
        values = {key: value for key, value in item.model_dump(mode="json").items() if key in {"ticker", "company_name", "exchange", "country", "sector", "industry", "asset_type", "market_cap", "is_biotech", "active"}}
        values["asset_type"] = item.asset_type.value
        if row is None:
            self.session.add(InstrumentORM(**values, created_at=now, updated_at=now))
        else:
            for key, value in values.items(): setattr(row, key, value)
            row.updated_at = now

    def save_market(self, run_id: UUID, item: MarketSnapshot) -> None:
        self.session.add(MarketSnapshotORM(scan_run_id=str(run_id), ticker=item.ticker, normalized_data=_json(item), source=item.source, as_of=item.as_of, fetched_at=item.fetched_at, stale=item.stale))

    def save_fundamental(self, run_id: UUID, item: FundamentalSnapshot) -> None:
        self.session.add(FundamentalSnapshotORM(scan_run_id=str(run_id), ticker=item.ticker, normalized_data=_json(item), raw_source_json=item.raw, source=item.source, as_of=item.as_of, fetched_at=item.fetched_at, stale=item.stale))

    def save_estimates(self, run_id: UUID, item: EstimateSnapshot) -> None:
        self.session.add(EstimateSnapshotORM(scan_run_id=str(run_id), ticker=item.ticker, normalized_data=_json(item), source=item.source, as_of=item.as_of, fetched_at=item.fetched_at, stale=item.stale))

    def save_catalyst(self, run_id: UUID, item: Catalyst) -> None:
        self.session.add(CatalystORM(scan_run_id=str(run_id), ticker=item.ticker, type=item.type, title=item.title, event_date=item.event_date.isoformat() if item.event_date else None, grade=item.grade.value, materiality=item.materiality, surprise_potential=item.surprise_potential, verified=item.verified, source=item.source, source_timestamp=item.source_timestamp, summary=item.summary, normalized_data=_json(item)))

    def save_corporate_event(self, run_id: UUID, item: CorporateEvent) -> None:
        self.session.add(CorporateEventORM(scan_run_id=str(run_id), ticker=item.ticker, type=item.type, title=item.title, event_date=item.event_date.isoformat(), timing=item.timing, verified=item.verified, source=item.source, as_of=item.as_of, fetched_at=item.fetched_at, stale=item.stale, normalized_data=_json(item)))

    def save_scanner_match(self, run_id: UUID, ticker: str, item: ScannerMatch) -> None:
        evidence = {"conditions": item.conditions, "evaluation_status": item.evaluation_status.value, "incomplete_fields": item.incomplete_fields, **item.evidence}
        self.session.add(ScannerMatchORM(scan_run_id=str(run_id), ticker=ticker, scanner=item.scanner.value, qualified=item.qualified, conditions_met=item.conditions_met, conditions_total=item.conditions_total, evidence=evidence))

    def save_regime(self, run_id: UUID, item: MarketRegimeResult) -> None:
        self.session.add(MarketRegimeORM(scan_run_id=str(run_id), regime=item.regime.value, regime_score=item.regime_score, spy_data=item.spy_data, qqq_data=item.qqq_data, iwm_data=item.iwm_data, vix_data=item.vix_data, breadth_data=item.breadth_data, timestamp=item.timestamp))

    def save_opportunity(self, run_id: UUID, item: OpportunityResult) -> None:
        s = item.scores
        self.session.add(OpportunityORM(scan_run_id=str(run_id), ticker=item.ticker, primary_scanner=item.primary_scanner.value, secondary_scanners=[value.value for value in item.secondary_scanners], base_opportunity_score=s.base_opportunity_score, penalty_points=s.penalty_points, multi_scanner_bonus=s.multi_scanner_bonus, opportunity_score=s.opportunity_score, catalyst_score=s.catalyst.score, fundamental_score=s.fundamental.score, valuation_score=s.valuation.score, technical_score=s.technical.score, revision_score=s.revisions.score, balance_sheet_score=s.balance_sheet.score, liquidity_score=s.liquidity.score, automatic_rejections=item.automatic_rejections, audit_json=_json(item), created_at=item.created_at))

    def save_provider_error(self, run_id: UUID, item: dict) -> None:
        occurred_at = item.get("occurred_at") or datetime.now(UTC)
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at)
        self.session.add(ProviderErrorORM(scan_run_id=str(run_id), provider=item.get("provider", "unknown"), code=item.get("code", "PROVIDER_ERROR"), message=item.get("message", "Provider error"), retryable=bool(item.get("retryable")), ticker=item.get("ticker"), endpoint=item.get("endpoint"), status_code=item.get("status_code"), occurred_at=occurred_at))

    def save_validation_issue(self, run_id: UUID, item: ValidationIssue) -> None:
        self.session.add(ValidationIssueORM(scan_run_id=str(run_id), ticker=item.ticker, code=item.code, severity=item.severity.value, field=item.field, message=item.message, observed_value=item.observed_value, expected=item.expected, source=item.source, created_at=item.created_at))

    def commit(self) -> None: self.session.commit()

    def latest_opportunities(self) -> list[dict]:
        latest = self.session.execute(select(ScanRunORM).where(ScanRunORM.status == "COMPLETED").order_by(ScanRunORM.completed_at.desc())).scalars().first()
        if not latest: return []
        rows = self.session.execute(select(OpportunityORM).where(OpportunityORM.scan_run_id == latest.id).order_by(OpportunityORM.opportunity_score.desc())).scalars().all()
        return [row.audit_json for row in rows]

    def latest_market_regime(self) -> dict | None:
        row = self.session.execute(select(MarketRegimeORM).join(ScanRunORM, MarketRegimeORM.scan_run_id == ScanRunORM.id).where(ScanRunORM.status == "COMPLETED").order_by(ScanRunORM.completed_at.desc())).scalars().first()
        if row is None: return None
        return {"regime": row.regime, "regime_score": row.regime_score, "spy_data": row.spy_data, "qqq_data": row.qqq_data, "iwm_data": row.iwm_data, "vix_data": row.vix_data, "breadth_data": row.breadth_data, "timestamp": row.timestamp.isoformat(), "reasons": []}
