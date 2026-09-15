from test_guidance_explicit_scope_normalizer_v1_1 import doc, HASH, RULES
from test_phase_1_1e_run83_pipeline_regressions import CASES
from app.services.canonical_shadow_guidance_service import assess_canonical_guidance_documents


def test_debug_canonical_quarantine_case2():
    documents = [doc(CASES[2][0]), doc(CASES[2][0], 8)]
    assessment, meta, errors = assess_canonical_guidance_documents("TEST", documents, RULES, rules_hash=HASH)
    assert not meta["canonical_quarantine"], meta["canonical_quarantine"]
