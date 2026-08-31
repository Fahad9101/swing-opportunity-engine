from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import MODEL_VERSION


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RULES_PATH = PROJECT_ROOT / "config" / "soe_v1_0_rules.yaml"


class Settings(BaseSettings):
    database_url: str = "sqlite:///./soe_dev.db"
    rules_path: Path = DEFAULT_RULES_PATH
    provider_name: str = "fixture"
    log_level: str = "INFO"
    financial_datasets_api_key: str | None = None
    financial_datasets_base_url: str = "https://api.financialdatasets.ai"
    apca_api_key_id: str | None = None
    apca_api_secret_key: str | None = None
    alpaca_data_base_url: str = "https://data.alpaca.markets"
    alpaca_trading_base_url: str = "https://paper-api.alpaca.markets"
    sec_user_agent: str = "SwingOpportunityEngine/1.0 (+https://fahadalmalkimd.com)"
    sec_companyfacts_zip_path: Path = PROJECT_ROOT / ".cache" / "soe" / "sec" / "companyfacts.zip"
    cache_dir: Path = PROJECT_ROOT / ".cache" / "soe"
    production_allow_partial: bool = True
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def load_rules(path: str | Path | None = None) -> dict[str, Any]:
    rules_path = Path(path or get_settings().rules_path)
    with rules_path.open("r", encoding="utf-8") as handle:
        rules = yaml.safe_load(handle)
    if rules.get("model_version") != MODEL_VERSION:
        raise ValueError("Rules model_version does not match application model version")
    return rules


def rules_hash(rules: dict[str, Any] | None = None) -> str:
    canonical = json.dumps(rules or load_rules(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
