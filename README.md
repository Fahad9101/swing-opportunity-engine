# Swing Opportunity Engine v1.0

`SOE-1.0.0` is a standalone, deterministic U.S. swing-opportunity discovery engine. This package contains Milestones 1–2 and the free/public-data Milestone 2.5 validation. Milestone 3 is intentionally absent.

The investment rules remain frozen in `config/soe_v1_0_rules.yaml` (SHA-256 `59cc7ffe14472434bfbb92b07b89b0b48293d0c5762d5270769bce3b494550ac`). Investment Execution Engine v1.7.2 is neither embedded nor modified.

## Free/public provider stack

| Domain | Source | Normalized use |
| --- | --- | --- |
| Universe | Nasdaq Trader official symbol directories | Ticker, name, exchange, active status, ETF flag, provider symbol, deterministic asset-type exclusions |
| Metadata | Nasdaq public stock screener endpoint | Market cap, country, sector, industry, company-name cross-check |
| Fundamentals | SEC EDGAR nightly `companyfacts.zip` | Historical revenue/growth, EPS/growth, margins, operating income, CFO-capex FCF, operating-income-plus-D&A EBITDA input, cash, debt, net debt, interest coverage, shares, cash runway where derivable |
| Analyst estimates | Nasdaq public analyst forecast endpoint | Prototype-only annual consensus EPS forecasts; derives forward EPS growth and analyst count without inventing revision history |
| Daily OHLCV | Yahoo Finance chart endpoint | Replaceable prototype-only adapter; completed EOD sessions; derives all SOE technicals |
| Earnings | Nasdaq public earnings calendar | Date and timing when supplied; event only, not a scored catalyst |
| Trials | ClinicalTrials.gov API v2 | On-demand primary/completion milestones; event only, never fabricated into an FDA/PDUFA date or scored A/B catalyst |
| Regime | Completed EOD SPY/QQQ/IWM plus Cboe VIX history | Deterministic regime inputs; breadth explicitly unavailable |

Yahoo and Nasdaq web endpoints are suitable for prototype validation but have no contractual SLA or explicit commercial redistribution grant in this project. Replace or separately license them before commercial production. SEC, Cboe, and ClinicalTrials adapters are isolated so provider-native payloads never reach scanner or scoring code.

No paid provider or Financial Datasets credential is required. Production mode never falls back to fixtures. The `fixture` provider remains available only when explicitly selected for tests/local demonstration.

## Missing-data semantics

- Missing values remain `null`; they are never converted to zero.
- Each scanner condition is `true`, `false`, or `null`.
- If missing required data could change the outcome, the scanner reports `DATA_INCOMPLETE` and does not qualify the security.
- Historical SEC results are not relabeled as forward estimates.
- Forward EPS growth and analyst count may be populated from the Nasdaq public analyst forecast endpoint when available.
- Analyst revision history, forward revenue/EBITDA, short float, scored catalysts, breadth, guidance deterioration, and valuation support remain unavailable in the free stack unless a later adapter explicitly supplies them.
- Every normalized production record retains source, `as_of`, `fetched_at`, and `stale`; field-level provenance is retained for derived values.

## Install and configure

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
cp .env.example .env
```

Set a descriptive SEC user agent with a contact URL or email:

```bash
PROVIDER_NAME=free_public
SEC_USER_AGENT="SwingOpportunityEngine/1.0 (+https://your-domain.example)"
DATABASE_URL=postgresql+psycopg://...
```

Download and validate the SEC nightly archive once:

```bash
PYTHONPATH=backend python -m app.cli_sec_bulk
```

The archive and all API caches live under `.cache/soe` and are excluded from the package. `submissions.zip` is not required by the current normalization path; CIK mapping uses SEC's exchange-ticker file and financial facts use `companyfacts.zip`.

## Cache and resilience

Configured lifetimes are: universe 24h, OHLCV 6h, price 15m, fundamentals 24h, estimates 12h, calendar 6h, and regime 15m. The SEC bulk archive is a nightly operator refresh. Calls use bounded concurrency, retry/backoff, rate-limit handling, timeouts, atomic cache writes, and structured errors. One provider or ticker failure cannot terminate the scan.

## Run

```bash
PYTHONPATH=backend PROVIDER_NAME=free_public python -m app.cli
python -m pytest
```

API:

```bash
uvicorn app.main:app --app-dir backend --reload
```

Endpoints: `GET /api/v1/health`, `POST /api/v1/scans`, `GET /api/v1/scans/{id}`, `GET /api/v1/opportunities`, and `GET /api/v1/market-regime`. Errors are JSON-only.

## Validation and audit

Automatic checks cover impossible percentages, EOD staleness, price/share market-cap inconsistencies, invalid negative fields, SMA mismatches, RSI range, null-to-zero conversion, duplicate tickers, provider symbol mismatches, ADR/common-stock confusion, and possible split discontinuities. Provider and validation errors persist against the scan run.

See `MILESTONE_2_5_REPORT.md` for the original real 5,156-security free-data run. Milestone 2.5B adds forward-EPS enrichment without changing the frozen SOE investment model; a new validation run is required before its effect on candidate qualification is accepted.

## Explicitly deferred

Entry Score, support, stops, T1/T2, R:R, maximum acceptable entry, Why Now/Why Not, thesis breaker, polished dashboard, Execution Engine handoff, alerts, and historical outcome tracking are not implemented.
