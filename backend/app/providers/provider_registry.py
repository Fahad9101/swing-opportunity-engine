from __future__ import annotations

from app.core.config import get_settings
from app.core.config import load_rules
from app.providers.fixture_provider import FixtureProvider
from app.providers.free_public_provider import FreePublicProvider
from app.providers.symbol_directory import NasdaqSymbolDirectory
from app.providers.nasdaq_calendar import NasdaqEarningsCalendar
from app.providers.cboe_vix import CboeVixProvider
from app.providers.clinical_trials import ClinicalTrialsProvider
from app.providers.public_market_data import PublicMarketDataProvider
from app.providers.sec_edgar import SecEdgarProvider
from app.providers.yahoo_analyst import YahooAnalystEstimateProvider
from app.services.cache_service import JsonFileCache


_providers: dict[str, object] = {"fixture": FixtureProvider()}


def register_provider(name: str, provider: object) -> None:
    _providers[name] = provider


def get_provider(name: str | None = None) -> object:
    selected = name or get_settings().provider_name
    if selected in {"production", "free_public"} and selected not in _providers:
        settings = get_settings()
        rules = load_rules()
        cache = JsonFileCache(settings.cache_dir)
        market = PublicMarketDataProvider(cache=cache, rules=rules)
        analyst = YahooAnalystEstimateProvider(cache=cache, rules=rules)
        provider = FreePublicProvider(
            symbol_directory=NasdaqSymbolDirectory(cache=cache), market=market,
            sec=SecEdgarProvider(cache=cache, zip_path=settings.sec_companyfacts_zip_path, user_agent=settings.sec_user_agent, rules=rules),
            analyst=analyst,
            calendar=NasdaqEarningsCalendar(cache=cache, rules=rules),
            clinical_trials=ClinicalTrialsProvider(timeout_seconds=rules["data_quality"]["provider"]["timeout_seconds"]),
            vix=CboeVixProvider(cache=cache), rules=rules,
        )
        _providers["production"] = provider
        _providers["free_public"] = provider
    if selected not in _providers:
        raise KeyError(f"Unknown provider: {selected}")
    return _providers[selected]
