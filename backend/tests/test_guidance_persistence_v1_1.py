from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import GuidanceMetric, GuidanceMetricRecord, SourceDocument
from app.persistence.database import Base, build_engine
from app.persistence.guidance_repository import GuidanceRepository
from app.persistence import orm_models, soe_v1_1_orm  # noqa: F401
from app.services.guidance_classifier import classify_guidance


RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)
NOW = datetime(2026, 9, 1, tzinfo=UTC)


def make_record(value: float, when: datetime) -> GuidanceMetricRecord:
    return GuidanceMetricRecord(
        rules_hash=RULES_HASH,
        ticker="TEST",
        fiscal_period="FY2027",
        metric=GuidanceMetric.REVENUE,
        accounting_basis="GAAP",
        midpoint=value,
        unit="USD",
        source="SEC EDGAR",
        source_url="https://www.sec.gov/test",
        source_timestamp=when,
        as_of=when,
        fetched_at=when,
        evidence_span="verified evidence",
    )


def test_guidance_evidence_is_append_only_and_json_safe():
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repository = GuidanceRepository(session)
        document = SourceDocument(
            document_id="doc1",
            rules_hash=RULES_HASH,
            ticker="TEST",
            cik="0000000001",
            accession="0000000001-26-000001",
            form="8-K",
            filing_date=date(2026, 9, 1),
            source_url="https://www.sec.gov/Archives/edgar/data/1/1/test.htm",
            source_timestamp=NOW,
            fetched_at=NOW,
            content_hash="a" * 64,
            content="not persisted",
        )
        prior = make_record(100.0, NOW - timedelta(days=90))
        current = make_record(98.0, NOW)
        assessment = classify_guidance([current], [prior], RULES, rules_hash=RULES_HASH, as_of=NOW)

        repository.save_source_document(document)
        repository.save_guidance_record(prior)
        repository.save_guidance_record(current)
        repository.save_assessment(assessment)
        repository.commit()

        loaded = repository.guidance_records("TEST")
        assert len(loaded) == 2
        assert loaded[-1].source_timestamp == NOW
        assert loaded[-1].midpoint == 98.0
        assert session.query(soe_v1_1_orm.SourceDocumentORM).one().normalized_data["source_timestamp"].endswith("Z")
        assert "content" not in session.query(soe_v1_1_orm.SourceDocumentORM).one().normalized_data
        assert session.query(soe_v1_1_orm.GuidanceAssessmentORM).one().guidance_deterioration is True

        with pytest.raises(ValueError):
            repository.save_guidance_record(current)
