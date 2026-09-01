from app.core.config import DEFAULT_RULES_PATH, SOE_1_1_RULES_PATH, load_rules, load_rules_for_version
from app.core.constants import MODEL_VERSION


def test_default_runtime_remains_frozen_v1_0():
    assert MODEL_VERSION == "SOE-1.0.0"
    assert DEFAULT_RULES_PATH.name == "soe_v1_0_rules.yaml"
    assert load_rules()["model_version"] == "SOE-1.0.0"


def test_candidate_v1_1_rules_require_explicit_versioned_loader():
    rules = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
    assert rules["model_version"] == "SOE-1.1.0"
    assert rules["guidance_v1_1"]["material_cut_thresholds"]["revenue_pct"] == 0.02


def test_all_unaffected_core_thresholds_match_v1_0():
    v1_0 = load_rules()
    v1_1 = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
    unchanged_sections = [
        "universe",
        "technical",
        "growth",
        "rerating",
        "biotech",
        "catalyst",
        "opportunity",
        "scores",
        "market_regime",
        "penalties",
        "data_quality",
    ]
    for section in unchanged_sections:
        assert v1_1[section] == v1_0[section]
