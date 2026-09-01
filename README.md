# Swing Opportunity Engine v1.0

`SOE-1.0.0` is a standalone, deterministic U.S. swing-opportunity discovery engine. This package contains Milestones 1–2 and the free/public-data Milestone 2.5 validation. Milestone 3 is intentionally absent.

The investment rules remain frozen in `config/soe_v1_0_rules.yaml` (SHA-256 `59cc7ffe14472434bfbb92b07b89b0b48293d0c5762d5270769bce3b494550ac`). Investment Execution Engine v1.7.2 is neither embedded nor modified.

## Free/public provider stack

| Domain | Source | Normalized use |
| --- | --- | --- |
| Universe | Nasdaq Trader official symbol directories | Ticker, name, exchange, active status, ETF flag, provider symbol, deterministic asset-type exclusions |
| Metadata | Nasdaq public stock screener endpoint | Market cap, country, sector, industry, company-name cross-check |
| Fundamentals | SEC EDGAR nightly `companyfacts.zip` | Historical revenue/growth, EPS/growth, margins, operating income, CFO-capex FCF, operating-income-plus-D&A EBITDA input, cash, debt, net debt, interest coverage, shares, and quarterly operating-cash-flow inputs |
| Biotech liquidity / financing | SEC EDGAR `companyfacts.zip`, `submissions.zip`, and primary 10-Q/10-K/8-K/6-K documents | Deterministic cash-runway derivation, recovery of custom-tagged marketable-security balances from periodic filings, and post-balance-sheet completed-financing evidence |
| Analyst estimates / valuation reference | Yahoo Finance `quoteSummary` / `earningsTrend,financialData` | Prototype-only forward EPS growth, 30-day EPS up/down revision counts, 30/90-day EPS consensus change, forward revenue, analyst count, and consensus target mean/low/high used only as discovery-stage expected-upside headroom |
| Ownership / short float | Yahoo Finance `quoteSummary` / `majorHoldersBreakdown,defaultKeyStatistics` | Prototype-only institutional ownership and short float; ownership feeds the existing liquidity score and short float above 25% activates the existing fixed −2 penalty |
| Daily OHLCV | Yahoo Finance chart endpoint | Replaceable prototype-only adapter; completed EOD sessions; derives all SOE technicals and historical price points used by self-relative valuation |
| Earnings / catalyst evidence | Nasdaq public earnings calendar | Exact public date and timing when supplied, with date-confidence/provenance metadata; evidence remains unscored when materiality or surprise is unavailable |
| Trials / catalyst evidence | ClinicalTrials.gov API v2 | Sponsor-matched primary/completion milestones with exact date precision/windows; never fabricated into a readout, FDA/PDUFA date, or scored catalyst |
| Regime | Completed EOD SPY/QQQ/IWM plus Cboe VIX history | Deterministic regime inputs; breadth explicitly unavailable |

Yahoo and Nasdaq web endpoints are suitable for prototype validation but have no contractual SLA or explicit commercial redistribution grant in this project. Replace or separately license them before commercial production. SEC, Cboe, and ClinicalTrials adapters are isolated so provider-native payloads never reach scanner or scoring code.

No paid provider or Financial Datasets credential is required. Production mode never falls back to fixtures. The `fixture` provider remains available only when explicitly selected for tests/local demonstration.

## Free/public valuation methodology

Milestone 2.5G supplies the two inputs already expected by the frozen SOE valuation component without changing its score bands or weights:

- `fundamental_undervaluation` / `valuation_discount`: for eligible conventional common shares, the engine compares current price with the security's own historical normalized valuation. Historical median P/E is primary; historical median P/S is an explicit fallback when earnings are not usable and the sector adapter permits it. At least four valid historical observations are required. Missing or unreliable history remains `null`.
- `expected_swing_upside`: prototype discovery-stage headroom from the current Yahoo analyst consensus mean target versus current price. This is **not** Milestone-3 T2, not a 1–8 week price forecast, and not a claim that consensus fair value will be reached during the swing horizon.

The two inputs remain logically independent, matching the frozen SOE design: expected upside has 12 possible points and valuation support has 8 possible points. Analyst consensus cannot manufacture the historical-valuation-support condition, and historical valuation cannot manufacture analyst headroom.

Yahoo historical prices are split-adjusted while SEC share facts can contain pre-split and retrospectively restated values. When a large share-count discontinuity is detected, historical multiple observations use the current share basis and record `CURRENT_SHARES_SPLIT_NORMALIZED`; otherwise they use `PERIOD_END_SHARES`. This is a data-normalization safeguard, not an investment-rule change.

Generic historical-multiple valuation is intentionally not forced onto biotech, ADRs, or Real Estate names where the current free stack lacks the correct specialized valuation adapter. Financial companies may use the earnings-based path when valid, but generic P/S fallback is disabled. Biotech remains outside conventional Buffett-style multiple valuation and retains its separate catalyst/runway framework.

## Free/public catalyst-intelligence methodology

Milestone 2.5H separates **public catalyst evidence** from **scored catalysts** so incomplete public data cannot manufacture catalyst points.

Every normalized public event can retain exact date/window, date precision (`DAY`, `MONTH`, `YEAR`), frozen A/B/C date-confidence evidence, source/provenance, catalyst-candidate state, scoring-readiness state, and explicit missing score fields.

The frozen catalyst score remains unchanged: materiality 0–10, timing 0–5, date confidence A/B/C = 5/3/0, and surprise/re-rating potential 0–5. An event is promoted into the existing scored `Catalyst` model only when the required numerical inputs are explicitly available and the evidence is valid. Missing materiality or surprise remains `null`, not zero.

Nasdaq earnings-calendar records can therefore provide verified exact-day catalyst evidence without automatically receiving catalyst points. ClinicalTrials.gov primary/completion dates are retained as study milestones with their true precision/window; they are **not** assumed to be data-readout dates and are never converted into FDA/PDUFA dates. Sponsor matching is applied before trial events are associated with a biotech ticker.

## Free/public biotech runway and financing methodology

Milestone 2.5I operationalizes the existing biotech runway fields without changing the frozen thresholds: preferred runway ≥18 months, standard eligibility ≥12 months, and automatic rejection below 9 months only when financing is deterministically not secured.

Cash runway is derived from public SEC evidence as follows:

- operating cash flow is converted from SEC YTD duration facts into discrete quarters before burn is calculated;
- positive operating-cash-flow quarters do not offset negative-quarter burn;
- the monthly burn rate is the greater of the latest-quarter monthly burn and trailing negative-quarter monthly burn, preventing older low-burn periods from masking acceleration;
- liquidity uses cash plus one non-overlapping current marketable-security balance when available;
- when `companyfacts` misses a current investment balance because the issuer used a custom XBRL tag, the engine may recover an explicit **scaled** balance from the latest 10-Q/10-K primary filing;
- unscaled filing-table values are not guessed because the table may be reported in thousands or millions;
- collaboration milestones, receivables, ATM capacity, shelf capacity and announced-but-not-closed offerings are never counted as liquidity.

Financing is assessed from SEC submissions and primary filing documents **after the same effective balance-sheet date used for runway**. `financing_secured=True` requires deterministic evidence that financing completed/closed or proceeds were received. Shelf registrations, ATM programs, prospectus supplements, pricing announcements and an expectation to close do not qualify. If the filing review is incomplete, financing remains `null` rather than being forced to false.

Catalyst eligibility remains separate from runway eligibility. A biotech can have an excellent balance sheet but still fail the Biotech/Catalyst scanner if there is no verified A/B catalyst. ClinicalTrials.gov primary/completion milestones remain non-readout events. Exact A/B event-date evidence with missing materiality or surprise remains insufficient to create a scored catalyst or Grade-A technical-exception path.

## Missing-data semantics

- Missing values remain `null`; they are never converted to zero.
- Each scanner condition is `true`, `false`, or `null`.
- If missing required data could change the outcome, the scanner reports `DATA_INCOMPLETE` and does not qualify the security.
- Historical SEC results are not relabeled as forward estimates.
- Forward EPS growth, EPS revision breadth inputs, 30/90-day EPS consensus changes, forward revenue, and analyst count may be populated from Yahoo's `earningsTrend` module when available.
- Analyst target mean/low/high may be populated from Yahoo `financialData`; only a current non-stale mean target can populate the discovery headroom proxy.
- Institutional ownership and short float may be populated from Yahoo's ownership/statistics modules when available. Missing ownership or short float remains `null`; no score or penalty is fabricated.
- The frozen `short_float_over_25` penalty is applied only when normalized short float is strictly greater than 25%; exactly 25% does not trigger it.
- Public event evidence may be available while the scored catalyst remains unavailable. Missing catalyst materiality/surprise cannot be backfilled with arbitrary defaults.
- Biotech runway can be derived from SEC evidence, but unresolved current-period liquidity or financing evidence remains unavailable rather than forcing a false scanner decision.
- Revenue/EBITDA revision counts, market breadth, guidance deterioration, authoritative clinical readout dates and authoritative FDA/PDUFA dates remain unavailable unless a later adapter explicitly supplies them.
- Every normalized production record retains source, `as_of`, `fetched_at`, and `stale`; field-level provenance is retained for derived values.

The previously tested Nasdaq `/api/analyst/{symbol}/forecast` path was retired after a live smoke run returned `PROVIDER_SYMBOL_NOT_FOUND` across DELL, AVGO, FAST, LUV, and ARWR. It is not used by the active free provider.

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

Download and validate the SEC nightly archives:

```bash
PYTHONPATH=backend python -m app.cli_sec_bulk
```

This downloads both `companyfacts.zip` and `submissions.zip` into `.cache/soe/sec`. Archives and API caches are excluded from the package. CIK mapping still uses SEC's exchange-ticker data. The live adapter can fall back to SEC's public per-company endpoints when local bulk archives are unavailable, but full-market operation should use the nightly archives.

## Cache and resilience

Configured lifetimes are: universe 24h, OHLCV 6h, price 15m, fundamentals 24h, estimates/ownership 12h, calendar 6h, and regime 15m. SEC bulk archives are operator-refreshed from the nightly public files. Calls use caching, retry/backoff, rate-limit handling, timeouts, atomic cache writes, and structured errors. One provider or ticker failure cannot terminate the scan. Optional ownership, estimate, valuation-reference and catalyst-evidence failures are recorded without discarding otherwise valid SEC fundamentals or market data.

## Run

```bash
PYTHONPATH=backend PROVIDER_NAME=free_public python -m app.cli
python -m pytest
```

Targeted validation:

```bash
PYTHONPATH=backend PROVIDER_NAME=free_public python -m app.cli_live_catalyst_smoke
PYTHONPATH=backend PROVIDER_NAME=free_public python -m app.cli_live_biotech_smoke
```

API:

```bash
uvicorn app.main:app --app-dir backend --reload
```

Endpoints: `GET /api/v1/health`, `POST /api/v1/scans`, `GET /api/v1/scans/{id}`, `GET /api/v1/opportunities`, and `GET /api/v1/market-regime`. Errors are JSON-only.

## Validation and audit

Automatic checks cover impossible percentages, EOD staleness, price/share market-cap inconsistencies, invalid negative fields, SMA mismatches, RSI range, null-to-zero conversion, duplicate tickers, provider symbol mismatches, ADR/common-stock confusion, possible split discontinuities, historical-valuation observation sufficiency, stale analyst targets, public date precision, catalyst score-input completeness, ClinicalTrials.gov sponsor association, YTD-to-quarter cash-flow decomposition, biotech liquidity fallback false positives, financing completion evidence, runway threshold boundaries, and runway/financing period alignment. Provider and validation errors persist against the scan run.

See `MILESTONE_2_5_REPORT.md` for the original real 5,156-security free-data run, `MILESTONE_2_5E_REPORT.md` for targeted estimate/revision validation, `MILESTONE_2_5F_REPORT.md` for ownership/short-float validation, `MILESTONE_2_5G_REPORT.md` for free/public valuation and expected-upside validation, `MILESTONE_2_5H_REPORT.md` for free/public catalyst-intelligence validation, and `MILESTONE_2_5I_REPORT.md` for biotech cash-runway, financing and catalyst-eligibility validation. A fresh full-market validation run remains required before Milestone 2.5 can be considered fully production-validated.

## SOE-1.1 Phase 1.1A shadow validation

Phase 1.1A adds a primary-source SEC guidance ledger and deterministic tri-state guidance-deterioration classifier while keeping SOE-1.0.0 as the default runtime. The validation harness now performs true historical SEC submissions backfill by following official `filings.files` archive references whose SEC-reported date ranges overlap the lookback window, merging those records with `filings.recent`, and de-duplicating accessions before targeted filing/exhibit retrieval. This expands evidence coverage only; the frozen 2% revenue, 5% EPS/EBITDA/FCF, 100-bps margin, and multi-metric deterioration thresholds are unchanged. Phase 1.1A remains non-active until the live sample contains at least 10 genuinely comparable names, at least 80% classification coverage among them, and 100% provenance on non-null classifications.

## Explicitly deferred

Entry Score, support, stops, T1/T2, R:R, maximum acceptable entry, Why Now/Why Not, thesis breaker, polished dashboard, Execution Engine handoff, alerts, and historical outcome tracking are not implemented. Fully automated qualitative materiality/surprise scoring and authoritative biotech readout/regulatory-date extraction also remain deferred until they can be implemented without changing or fabricating frozen SOE-1.0.0 rules.
