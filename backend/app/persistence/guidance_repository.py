from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.soe_v1_1 import GuidanceAssessment, GuidanceMetricRecord, SourceDocument
from app.persistence.soe_v1_1_orm import GuidanceAssessmentORM, GuidanceMetricRecordORM, SourceDocumentORM


def _json(model) -> dict:
    return model.model_dump(mode="json")


class GuidanceRepository:
    """Append-only persistence for SOE-1.1 evidence and guidance assessments."""

    def __init__(self, session: Session):
        self.session = session

    def save_source_document(self, item: SourceDocument, *, scan_run_id: str | None = None) -> None:
        if self.session.execute(
            select(SourceDocumentORM).where(SourceDocumentORM.document_id == item.document_id)
        ).scalars().first() is not None:
            return
        self.session.add(
            SourceDocumentORM(
                document_id=item.document_id,
                model_version=item.model_version,
                rules_hash=item.rules_hash,
                scan_run_id=scan_run_id,
                ticker=item.ticker,
                cik=item.cik,
                accession=item.accession,
                form=item.form,
                source_url=item.source_url,
                source_timestamp=item.source_timestamp,
                fetched_at=item.fetched_at,
                stale=item.stale,
                content_hash=item.content_hash,
                normalized_data=_json(item),
            )
        )

    def save_guidance_record(self, item: GuidanceMetricRecord) -> None:
        if self.session.get(GuidanceMetricRecordORM, str(item.record_id)) is not None:
            raise ValueError("Guidance metric records are immutable and cannot be overwritten")
        self.session.add(
            GuidanceMetricRecordORM(
                record_id=str(item.record_id),
                model_version=item.model_version,
                rules_hash=item.rules_hash,
                scan_run_id=str(item.scan_run_id) if item.scan_run_id else None,
                ticker=item.ticker,
                fiscal_period=item.fiscal_period,
                metric=item.metric.value,
                accounting_basis=item.accounting_basis,
                low=item.low,
                high=item.high,
                midpoint=item.midpoint,
                unit=item.unit,
                source=item.source,
                source_url=item.source_url,
                source_accession=item.source_accession,
                source_timestamp=item.source_timestamp,
                explicit_action=item.explicit_action.value,
                verified=item.verified,
                supersedes_record_id=str(item.supersedes_record_id) if item.supersedes_record_id else None,
                extraction_method=item.extraction_method.value,
                evidence_span=item.evidence_span,
                source_document_hash=item.source_document_hash,
                as_of=item.as_of,
                fetched_at=item.fetched_at,
                stale=item.stale,
                normalized_data=_json(item),
            )
        )

    def save_assessment(self, item: GuidanceAssessment) -> None:
        if self.session.get(GuidanceAssessmentORM, str(item.assessment_id)) is not None:
            raise ValueError("Guidance assessments are immutable and cannot be overwritten")
        self.session.add(
            GuidanceAssessmentORM(
                assessment_id=str(item.assessment_id),
                model_version=item.model_version,
                rules_hash=item.rules_hash,
                scan_run_id=str(item.scan_run_id) if item.scan_run_id else None,
                ticker=item.ticker,
                as_of=item.as_of,
                classification=item.classification.value,
                guidance_deterioration=item.guidance_deterioration,
                rule_path=item.rule_path,
                reasons=item.reasons,
                sources=item.sources,
                normalized_data=_json(item),
            )
        )

    def guidance_records(self, ticker: str, *, as_of: datetime | None = None) -> list[GuidanceMetricRecord]:
        query = select(GuidanceMetricRecordORM).where(GuidanceMetricRecordORM.ticker == ticker)
        if as_of is not None:
            query = query.where(GuidanceMetricRecordORM.source_timestamp <= as_of)
        rows = self.session.execute(query.order_by(GuidanceMetricRecordORM.source_timestamp)).scalars().all()
        return [GuidanceMetricRecord.model_validate(row.normalized_data) for row in rows]

    def commit(self) -> None:
        self.session.commit()
