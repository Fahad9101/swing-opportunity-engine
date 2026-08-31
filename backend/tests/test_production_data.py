import asyncio
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.core.config import load_rules
from app.core.config import get_settings
from app.domain.enums import AssetType
from app.domain.schemas import FundamentalSnapshot, Instrument, OHLCVBar
from app.orchestration.scan_pipeline import run_full_scan, scan_manager
from app.persistence.database import init_database
from app.providers.errors import ProviderError
from app.providers.financial_datasets import normalize_fundamentals, normalize_prices
from app.providers.fixture_provider import FixtureProvider
from app.providers.http_client import ResilientJsonClient
from app.providers.provider_registry import get_provider, register_provider
from app.providers.provider_registry import _providers
from app.providers.public_market_data import normalize_nasdaq_screener, normalize_yahoo_spark
from app.providers.sec_edgar import normalize_companyfacts
from app.providers.clinical_trials import normalize_trial_events
from app.providers.symbol_directory import normalize_symbol_directories
from app.services.cache_service import JsonFileCache
from app.services.data_quality_service import detect_null_to_zero, duplicate_symbol_issues, validate_candidate
from app.services.technical_service import build_market_snapshot
from app.services.trading_calendar_service import is_eod_stale, latest_expected_completed_session


def _client(tmp_path, transport, *, retries=1):
    return ResilientJsonClient(provider="test", base_url="https://example.test", headers={}, timeout_seconds=0.01, max_retries=retries, initial_backoff_seconds=0, max_concurrency=2, cache=JsonFileCache(tmp_path), transport=transport)


def test_financial_datasets_price_normalization_and_symbol_check():
    payload = {"ticker": "BRK-B", "prices": [{"time": "2026-08-28T20:00:00Z", "open": 500, "high": 510, "low": 499, "close": 507, "volume": 10}]}
    bars = normalize_prices(payload, requested_ticker="BRK.B")
    assert bars[0].close == 507
    with pytest.raises(ProviderError) as error:
        normalize_prices({**payload, "ticker": "BRK-A"}, requested_ticker="BRK.B")
    assert error.value.code == "PROVIDER_SYMBOL_MISMATCH"


def test_financial_normalization_preserves_missing_as_null():
    now = datetime.now(UTC)
    result = normalize_fundamentals("NULL", {"snapshot": {"revenue_growth": None, "earnings_per_share": None}}, {"income_statements": []}, {"balance_sheets": []}, {"cash_flow_statements": []}, fetched_at=now, max_age_hours=2880)
    assert result is not None
    assert result.revenue_growth is None
    assert result.eps is None
    assert result.cash is None


def test_rate_limit_retries_then_succeeds(tmp_path):
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "0"}, request=request) if calls == 1 else httpx.Response(200, json={"ok": True}, request=request)
    result = asyncio.run(_client(tmp_path, httpx.MockTransport(handler)).request_json("GET", "/value"))
    assert result == {"ok": True}
    assert calls == 2


def test_timeout_is_structured_and_does_not_expose_request(tmp_path):
    def handler(request):
        raise httpx.ReadTimeout("secret-bearing request timed out", request=request)
    with pytest.raises(ProviderError) as error:
        asyncio.run(_client(tmp_path, httpx.MockTransport(handler), retries=0).request_json("GET", "/value", ticker="TEST"))
    assert error.value.code == "PROVIDER_TIMEOUT"
    assert "secret" not in error.value.message


def test_cache_retains_original_fetch_timestamp(tmp_path):
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"ok": True}, request=request)
    client = _client(tmp_path, httpx.MockTransport(handler))
    first = asyncio.run(client.request_json_with_metadata("GET", "/cached", cache_key="cached", ttl_seconds=60))
    second = asyncio.run(client.request_json_with_metadata("GET", "/cached", cache_key="cached", ttl_seconds=60))
    assert calls == 1
    assert second.from_cache is True
    assert second.fetched_at == first.fetched_at


def test_official_symbol_directory_excludes_etf_and_classifies_adr():
    nasdaq = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nAAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\nETF1|Index ETF|G|N|N|100|Y|N\nADR1|Issuer American Depositary Shares|Q|N|N|100|N|N\nFile Creation Time: 2026082821:31|||||||\n"
    other = "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\nIBM|IBM Common Stock |N|IBM|N|100|N|IBM\n"
    rows = normalize_symbol_directories(nasdaq, other, fetched_at=datetime.now(UTC))
    by_ticker = {item.ticker: item for item in rows}
    assert by_ticker["ETF1"].asset_type == AssetType.ETF
    assert by_ticker["ADR1"].asset_type == AssetType.ADR
    assert by_ticker["IBM"].exchange == "NYSE"


def test_symbol_directory_excludes_preference_depositary_and_partnership_units():
    nasdaq = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nAHL-D|Issuer 5.625% Perpetual Non-Cumulative Preference Shares|Q|N|N|100|N|N\nLP|Issuer L.P. Common Units representing Limited Partners Interests|Q|N|N|100|N|N\nADR|Issuer American Depositary Shares|Q|N|N|100|N|N\nFile Creation Time: 2026082821:31|||||||\n"
    other = "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\nIBM|IBM Common Stock|N|IBM|N|100|N|IBM\n"
    rows = normalize_symbol_directories(nasdaq, other, fetched_at=datetime.now(UTC))
    by_ticker = {item.ticker: item for item in rows}
    assert by_ticker["AHL-D"].asset_type == AssetType.PREFERRED
    assert by_ticker["LP"].asset_type == AssetType.UNIT
    assert by_ticker["ADR"].asset_type == AssetType.ADR


def test_symbol_directory_excludes_abbreviated_preferred_debt_and_cef():
    nasdaq = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nPFD|Issuer Dep Shs repstg 1/1000 Pfd Ser A|Q|N|N|100|N|N\nDEBT|Issuer 6.25% Senior Notes due 2033|Q|N|N|100|N|N\nCEF|Issuer Income Fund Inc. Common Stock|Q|N|N|100|N|N\nFile Creation Time: 2026082821:31|||||||\n"
    other = "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\nIBM|IBM Common Stock|N|IBM|N|100|N|IBM\n"
    by_ticker = {item.ticker: item for item in normalize_symbol_directories(nasdaq, other, fetched_at=datetime.now(UTC))}
    assert by_ticker["PFD"].asset_type == AssetType.PREFERRED
    assert by_ticker["DEBT"].asset_type == AssetType.DEBT_SECURITY
    assert by_ticker["CEF"].asset_type == AssetType.CEF


def test_duplicate_universe_entries_are_flagged(instrument):
    issues = duplicate_symbol_issues([instrument, instrument.model_copy()])
    assert [item.code for item in issues] == ["DUPLICATE_TICKER"]


def test_stale_and_split_adjustment_validation(instrument, rules):
    start = date.today() - timedelta(days=260)
    bars = [OHLCVBar(date=start + timedelta(days=index), open=20, high=21, low=19, close=20, volume=1_000_000) for index in range(260)]
    market = build_market_snapshot(instrument.ticker, bars, "production", rules)
    market.as_of = datetime.now(UTC) - timedelta(days=7)
    unadjusted = list(bars)
    unadjusted[-1] = OHLCVBar(date=unadjusted[-1].date, open=8, high=9, low=7, close=8, volume=2_500_000)
    codes = {item.code for item in validate_candidate(instrument, market, unadjusted, None, rules)}
    assert "STALE_PRICE" in codes
    assert "POSSIBLE_SPLIT_ADJUSTMENT_PROBLEM" in codes
    adjusted_codes = {item.code for item in validate_candidate(instrument, market, bars, None, rules)}
    assert "POSSIBLE_SPLIT_ADJUSTMENT_PROBLEM" not in adjusted_codes


def test_eod_freshness_treats_friday_as_current_before_monday_close():
    monday_before_close = datetime(2026, 8, 31, 15, 0, tzinfo=UTC)
    friday = datetime(2026, 8, 28, 20, 0, tzinfo=UTC)
    assert latest_expected_completed_session(monday_before_close) == date(2026, 8, 28)
    assert is_eod_stale(friday, monday_before_close) is False


def test_null_to_zero_detection_is_explicit():
    normalized = FundamentalSnapshot(ticker="TEST", institutional_ownership=0, source="test", as_of=datetime.now(UTC), fetched_at=datetime.now(UTC))
    issues = detect_null_to_zero(ticker="TEST", raw={"institutional": None}, normalized=normalized, field_map={"institutional_ownership": "institutional"}, source="test")
    assert issues[0].code == "NULL_CONVERTED_TO_ZERO"


def test_one_ticker_provider_failure_does_not_kill_scan():
    class PartialProvider(FixtureProvider):
        name = "partial-production-test"
        async def list_instruments(self):
            items = await super().list_instruments()
            return items + [Instrument(ticker="BROKEN", company_name="Broken", exchange="NASDAQ", sector="Technology", industry="Software", market_cap=1_000_000_000)]
        async def get_ohlcv(self, ticker, sessions=260):
            if ticker == "BROKEN":
                raise ProviderError(self.name, "PROVIDER_TIMEOUT", "Timed out.", retryable=True, ticker=ticker, endpoint="/prices")
            return await super().get_ohlcv(ticker, sessions)
    register_provider("partial-production-test", PartialProvider())
    init_database()
    state = scan_manager.create()
    result = asyncio.run(run_full_scan(state.scan_run_id, "partial-production-test"))
    assert result.status.value == "COMPLETED"
    assert result.error_count == 1
    assert result.provider_errors[0]["ticker"] == "BROKEN"
    assert len(result.opportunities) >= 3


def test_production_mode_uses_free_public_stack_without_paid_key(monkeypatch):
    monkeypatch.delenv("FINANCIAL_DATASETS_API_KEY", raising=False)
    get_settings.cache_clear()
    _providers.pop("production", None)
    _providers.pop("free_public", None)
    provider = get_provider("production")
    assert provider.name == "free_public"
    assert not isinstance(provider, FixtureProvider)
    get_settings.cache_clear()


def test_public_market_normalization_preserves_missing_and_symbol_identity():
    stamp = int(datetime(2026, 8, 28, tzinfo=UTC).timestamp())
    payload = {"spark": {"result": [{"symbol": "BRK-B", "response": [{"timestamp": [stamp], "indicators": {"quote": [{"open": [500], "high": [510], "low": [499], "close": [507], "volume": [10]}]}}]}]}}
    result = normalize_yahoo_spark(payload, {"BRK-B"}, datetime.now(UTC))
    assert result["BRK-B"][0].close == 507
    assert normalize_yahoo_spark(payload, {"BRK-A"}, datetime.now(UTC)) == {}
    metadata = normalize_nasdaq_screener({"data": {"rows": [{"symbol": "AAPL", "marketCap": "3,000,000", "sector": "Technology", "industry": None}]}})
    assert metadata["AAPL"]["market_cap"] == 3_000_000
    assert metadata["AAPL"]["industry"] is None


def test_sec_xbrl_normalization_uses_reported_values_and_keeps_forward_null():
    def facts(values, unit="USD"):
        return {"units": {unit: values}}
    quarters = [
        {"start": "2025-04-01", "end": "2025-06-30", "filed": "2025-08-01", "form": "10-Q", "frame": "CY2025Q2", "val": 100},
        {"start": "2026-01-01", "end": "2026-03-31", "filed": "2026-05-01", "form": "10-Q", "frame": "CY2026Q1", "val": 110},
        {"start": "2026-04-01", "end": "2026-06-30", "filed": "2026-08-01", "form": "10-Q", "frame": "CY2026Q2", "val": 120},
    ]
    payload = {"cik": 1, "entityName": "Real Co", "facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": facts(quarters),
        "OperatingIncomeLoss": facts([{**row, "val": row["val"] / 10} for row in quarters]),
        "NetCashProvidedByUsedInOperatingActivities": facts([{**row, "val": 20} for row in quarters]),
        "PaymentsToAcquirePropertyPlantAndEquipment": facts([{**row, "val": 5} for row in quarters]),
        "CashAndCashEquivalentsAtCarryingValue": facts([{"end": "2026-06-30", "filed": "2026-08-01", "form": "10-Q", "val": 50}]),
        "CommonStockSharesOutstanding": facts([{"end": "2026-06-30", "filed": "2026-08-01", "form": "10-Q", "val": 10}], "shares"),
    }}}
    result = normalize_companyfacts("REAL", payload, fetched_at=datetime.now(UTC), max_age_hours=10_000)
    assert result is not None
    assert result.revenue == 120
    assert result.revenue_growth == pytest.approx(0.2)
    assert result.revenue_growth_qoq == pytest.approx(120 / 110 - 1)
    assert result.fcf == 15
    assert result.forward_revenue_growth is None
    assert result.forward_eps is None
    assert result.institutional_ownership is None


def test_clinical_trials_dates_are_calendar_events_not_scored_catalysts(monkeypatch):
    monkeypatch.setattr("app.providers.clinical_trials.date", type("FixedDate", (date,), {"today": classmethod(lambda cls: date(2026, 8, 31))}))
    payload = {"studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT1", "briefTitle": "Phase 2"}, "statusModule": {"primaryCompletionDateStruct": {"date": "2026-09", "type": "ESTIMATED"}}}}]}
    events = normalize_trial_events("BIO", payload, fetched_at=datetime.now(UTC), horizon_days=56)
    assert events[0].type == "CLINICAL_TRIAL_PRIMARY_COMPLETION"
    assert events[0].timing == "ESTIMATED"


def test_scanner_marks_unknown_required_data_incomplete(instrument, market, rules):
    from app.screeners.growth_pullback import GrowthPullbackScreener
    fundamental = FundamentalSnapshot(ticker="TEST", revenue_growth=0.20, fcf_growth=0.20, balance_sheet_distressed=False, source="sec", as_of=datetime.now(UTC), fetched_at=datetime.now(UTC))
    match = GrowthPullbackScreener().evaluate(instrument, market, fundamental, None, None, rules)
    assert match.qualified is False
    assert match.evaluation_status.value == "DATA_INCOMPLETE"
    assert "no_strong_negative_revisions" in match.incomplete_fields
