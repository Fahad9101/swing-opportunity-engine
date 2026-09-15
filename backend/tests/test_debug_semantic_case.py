from test_guidance_explicit_scope_normalizer_v1_1 import doc, HASH, RULES
from test_phase_1_1e_run83_pipeline_regressions import CASES
from app.services.canonical_shadow_guidance_service import assess_canonical_guidance_documents


def test_debug_canonical_quarantine_case2():
    documents = [doc(CASES[2][0]), doc(CASES[2][0], 8)]
    assessment, meta, errors = assess_canonical_guidance_documents("TEST", documents, RULES, rules_hash=HASH)
    summary = []
    for item in meta["canonical_quarantine"]:
        fact = item["fact"]
        evidence = fact["provenance"][0]["evidence"]
        summary.append({
            "metric": fact["metric"],
            "period": fact["fiscal_period"],
            "role": fact["role"],
            "low": fact["low"],
            "high": fact["high"],
            "metric_text": evidence.get("metric_text"),
            "value_text": evidence.get("value_text"),
            "period_text": evidence.get("period_text"),
            "violations": [v["message"] for v in item["violations"]],
        })
    assert not summary, summary
