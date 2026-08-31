# Milestone 2.5 — free/public-data validation report

Date: 2026-08-31  
Model: `SOE-1.0.0`  
Rules/config SHA-256: `59cc7ffe14472434bfbb92b07b89b0b48293d0c5762d5270769bce3b494550ac`  
Run ID: `88905048-4ad1-48a2-892c-eacb98ef43b6`

## Outcome

The free/public scan completed across **5,156** real NASDAQ, NYSE, and NYSE American common stocks/ADRs using completed EOD sessions. It produced **2,331 universal-gate survivors**, **2,310 technical-ready survivors**, and **zero qualified candidates**.

Zero is the correct frozen-rule result. Required forward estimates, revisions, guidance state, valuation support, and scored A/B catalysts have no reliable free source in this stack. The engine marked potentially rescuable evaluations `DATA_INCOMPLETE`; it did not interpret missing as favorable, lower a threshold, fabricate a value, or mix fixture data into the run.

## Providers and exact fields

| Provider | Fields supplied | Status / constraint |
| --- | --- | --- |
| Nasdaq Trader official symbol directories | ticker, official security name, NASDAQ/NYSE/NYSE American mapping, ETF flag, active/financial status, provider symbol | Operational; preferreds, exchange-traded debt, CEFs, warrants, rights, units/partnership interests, SPAC/shell issues and ETFs/ETNs excluded before scanning |
| Nasdaq public stock screener | market cap, country, sector, industry, display name | Operational for prototype; 5,526/5,639 pre-clean metadata records in initial probe; no contractual SLA |
| Yahoo Finance chart endpoint | completed-session daily open, high, low, close, volume | Prototype-only, replaceable adapter; derives price, SMA20/50/200, slopes, RSI14, ATR14, 20/50/252-day highs/lows, returns, relative volume and average dollar volume |
| SEC EDGAR nightly `companyfacts.zip` | reported revenue, QoQ/YoY revenue growth, EPS/growth, gross/operating margin and change, CFO-capex FCF/growth, operating income plus D&A EBITDA input, cash, debt, net debt, interest coverage, shares, biotech cash runway where deterministically derivable | Operational but variable XBRL coverage; archive integrity: 20,290 issuer files, no corrupt entry |
| Nasdaq earnings calendar | earnings date, timing where supplied, event/company name | Operational; 368 survivor tickers had an event inside the configured window; events are not scored catalysts |
| ClinicalTrials.gov API v2 | NCT ID/title, primary completion date, completion date, ACTUAL/ESTIMATED date type | Operational on demand; live check returned one MRNA and four ARWR upcoming milestones; not converted to FDA/PDUFA dates or A/B catalyst scores |
| Cboe VIX history | VIX close, source, as-of, fetched-at, staleness | Operational; 14.43 as of 2026-08-28 |
| SPY/QQQ/IWM completed EOD | price, SMA50, SMA200 and provenance | Operational through the prototype OHLCV adapter |

SEC `submissions.zip` is not required by the current calculation path: CIK mapping comes from SEC's ticker/exchange mapping and facts come from `companyfacts.zip`. The downloader and adapter remain replaceable.

## Real versus unavailable

Production run inputs were entirely real. Synthetic/mock financial inputs used: **none**.

| Field/domain | Availability |
| --- | --- |
| Historical market/technicals | Fully operational for survivors, except 21 names lacked SMA200 and 28 lacked a 20-session SMA200 slope because history was shorter |
| Historical SEC fundamentals | Partially operational; concept and issuer coverage varies |
| Forward EPS/revenue/EBITDA | Unavailable (`null`) |
| 30/90-day revisions, up/down counts, analyst count | Unavailable (`null`) |
| Institutional ownership percentage | Unavailable (`null`); public 13F is CUSIP-based and lacks a reliable free full-market CUSIP-to-ticker/denominator normalization path |
| Short float | Unavailable (`null`) |
| Guidance deterioration | Unavailable (`null`) |
| Valuation discount / expected swing upside | Unavailable (`null`) |
| Scored catalyst materiality/surprise/A-B grade | Unavailable (`null`) |
| Earnings/trial calendar | Partially operational as unscored events |
| FDA/PDUFA dates | Unavailable; not invented |
| Market breadth | Unavailable; `breadth_available=false` |
| Insider-selling penalty input | Unavailable; Forms 3/4/5 were not transformed because the frozen rules provide no deterministic abnormal-selling classifier |

Public 13F and Forms 3/4/5 were therefore not silently interpreted as negative or positive evidence.

## Scan funnel

| Metric | Result |
| --- | ---: |
| Initial cleaned U.S. universe | 5,156 |
| Universal-gate survivors | 2,331 |
| Technical-ready survivors | 2,310 |
| Re-Rating qualified | 0 |
| Growth Pullback qualified | 0 |
| Biotech/Catalyst qualified | 0 |
| Deduplicated candidates | 0 |
| Fully scored candidates | 0 |
| Re-Rating `DATA_INCOMPLETE` | 1,207 |
| Growth Pullback `DATA_INCOMPLETE` | 1,261 |
| Biotech/Catalyst `DATA_INCOMPLETE` | 260 |
| Provider-error records | 7 |
| Ticker-processing errors | 5 |

Market regime was **GREEN**, score 100: SPY 769.35 > SMA50 753.96 > SMA200 709.85; QQQ 716.43 > SMA50 712.06 > SMA200 655.17; IWM 295.75 < SMA50 297.31 but > SMA200 271.31; VIX 14.43. Breadth was `null` and `breadth_available=false`.

## Completeness by field among 2,331 universal survivors

| Field | Available | Rate |
| --- | ---: | ---: |
| Price, SMA20, SMA50, RSI14, ATR14, highs/lows, returns, relative volume, dollar volume | 2,331 | 100.00% |
| SMA200 | 2,310 | 99.10% |
| SMA200 20-session slope | 2,303 | 98.80% |
| Any normalized SEC fundamental snapshot | 1,950 | 83.66% |
| Revenue | 1,867 | 80.09% |
| YoY revenue growth | 1,804 | 77.39% |
| QoQ revenue growth | 1,821 | 78.12% |
| EPS | 1,921 | 82.41% |
| EPS growth | 1,898 | 81.42% |
| Gross margin | 842 | 36.12% |
| Operating margin | 1,503 | 64.48% |
| Operating-margin change | 1,489 | 63.88% |
| FCF / FCF growth | 206 | 8.84% |
| Deterministically derived EBITDA input | 523 | 22.44% |
| Cash | 1,948 | 83.57% |
| Debt / net debt | 1,424 / 1,423 | 61.09% / 61.05% |
| Interest coverage | 44 | 1.89% |
| Shares outstanding | 1,817 | 77.95% |
| Cash runway | 69 | 2.96% |
| Forward fields, revisions, institutional ownership, short float | 0 | 0.00% |
| Earnings calendar event | 368 | 15.79% |

Domain missing rates persisted by the scan were: market 0.00%, fundamentals 16.34%, estimates 100.00%, calendar 84.21%.

## Top 20

No Top 20 is shown because **no security genuinely qualified**. Producing 20 names would require weakening a scanner or treating unavailable data as favorable, both prohibited. Opportunity Scores, penalties and multi-scanner bonuses were not computed for rejected/incomplete securities.

## Five manual audits

The component values below are diagnostic calls to the existing score functions for traceability; they are **not Opportunity Scores and were not ranked**, because each security failed or was incomplete before the scoring stage.

### 1. Highest Re-Rating incomplete case — DELL

- Price 456.24; SMA50 433.17; SMA200 244.73 → technical requirement TRUE.
- Forward EPS growth `null` → unavailable.
- QoQ revenue growth 62.35% > 0% → TRUE.
- Operating margin 8.34% vs prior 7.85% → improving TRUE.
- FCF growth 39.95% > 0% → improving TRUE.
- Positive revisions `null`; valuation discount `null`.
- Result: 3/6 known conditions, threshold 4; `DATA_INCOMPLETE`, not qualified.
- Diagnostic scores: Catalyst `null/25`; Fundamental 12/20 (15 points available); Valuation `null/20`; Technical 11/15; Revisions `null/10`; Balance Sheet 2/5; Liquidity 3/5 (institutional-ownership portion unavailable). Multi-scanner bonus 0; no Opportunity Score.

### 2. Highest Growth Pullback incomplete case — AVGO

- Market cap $1.7545T → large-cap revenue threshold 10%.
- YoY revenue growth 47.87% ≥ 10% → TRUE.
- Operating-margin expansion 428 bps ≥ 100 bps → growth-driver TRUE.
- Forward EPS growth `null`; FCF growth `null`; forward EBITDA growth `null`.
- Guidance deterioration `null`; strong-negative revisions `null`; balance-sheet distress classification `null`.
- Price 368.79; 50-day high 432.73 → pullback 14.78%, within the 5–20% preferred and 7–15% sweet-spot bands.
- Result: 2/5 known required conditions; `DATA_INCOMPLETE`, not qualified.
- Diagnostic scores: Catalyst `null/25`; Fundamental 14/20 (15 available); Valuation `null/20`; Technical 5/15; Revisions `null/10`; Balance Sheet 1/5; Liquidity 3/5. Bonus 0; no Opportunity Score.

### 3. Highest Biotech incomplete case — SRRK

- Cash $437.09M; quarterly FCF -$82.17M → deterministic runway 15.96 months ≥ 12 months → TRUE.
- Price 57.80 > SMA200 47.15 → technical path 1 TRUE.
- Price 57.80 > SMA50 52.91 and ≥ 80% of SMA200 → technical path 2 TRUE.
- Verified scored A/B catalyst `null`; no FDA/PDUFA date fabricated.
- Result: biotech + runway + both technical paths known TRUE, but required scored catalyst unavailable → `DATA_INCOMPLETE`, not qualified.
- Diagnostic scores: Catalyst `null/25`; Biotech Fundamental 3/20 (cash-runway 3, only 5 points available); Valuation `null/20`; Technical 10/15; Revisions `null/10`; Balance Sheet 5/5; Liquidity 2.5/5. Bonus 0; no Opportunity Score.

### 4. Closest multi-scanner incomplete case — KNSA

- Re-Rating: QoQ revenue +18.47%, margin 13.66% vs 13.28%, FCF growth +125.14%, technical requirement TRUE → 3 known TRUE; forward EPS, revisions and valuation unavailable → `DATA_INCOMPLETE`.
- Growth Pullback: YoY revenue +55.51% ≥ 15%; FCF driver +125.14%; pullback 5.86% → two required TRUE; guidance, negative-revision state and distress classification unavailable → `DATA_INCOMPLETE`.
- Biotech: price 78.08 > SMA50 69.70 and SMA200 51.92 → paths 1 and 2 TRUE; runway and scored catalyst unavailable → `DATA_INCOMPLETE`.
- No scanner qualified, so multi-scanner bonus = 0.
- Diagnostic scores: Catalyst `null/25`; Biotech Fundamental `null/20`; Valuation `null/20`; Technical 12/15; Revisions `null/10`; Balance Sheet `null/5`; Liquidity 2.5/5. No Opportunity Score.

### 5. Rejected borderline case — MMED

- Market cap $5.66B → normal revenue-growth threshold 15%.
- YoY revenue growth 14.9927% < 15.0000% → Growth Pullback required condition FALSE; threshold was not rounded down.
- Operating margin -12.66% vs prior +3.06% → margin expansion condition FALSE (-1,571 bps).
- Price 20.10; 50-day high 20.88 → pullback 3.74%, below preferred 5%.
- SMA200 unavailable because history was shorter than 200 sessions → Re-Rating technical requirement FALSE.
- Result: definitive Growth Pullback reject and Re-Rating reject, not `DATA_INCOMPLETE` despite other unavailable fields because known FALSE inputs already prevent qualification.
- Diagnostic scores: Catalyst `null/25`; Fundamental 8/20 (15 available); Valuation `null/20`; Technical 5/15; Revisions `null/10`; Balance Sheet `null/5`; Liquidity 2/5. Bonus 0; no Opportunity Score.

## Validation report

| Automatic check | Count |
| --- | ---: |
| Possible split-adjustment/one-session ≥60% discontinuity | 510 |
| Impossible percentage under the frozen validation bounds | 214 |
| Market-cap vs price × SEC shares inconsistency | 157 |
| Stale price | 1 (WLYB, last completed bar 2026-08-27) |
| SMA inconsistency | 0 |
| RSI outside 0–100 | 0 |
| Null converted to zero | 0 |
| Duplicate ticker | 0 |
| Provider symbol mismatch | 0 |
| ADR/common-stock confusion after normalization | 0 |
| Invalid negative nonnegative field | 0 |

The 510 discontinuities are warnings, not automatically assumed split errors: small-cap/biotech event gaps can also exceed 60%. The 214 percentage errors are primarily very large negative margins or growth ratios with small denominators; they remain flagged and are not silently clipped. Market-cap inconsistencies commonly reflect stale/different share-class SEC denominators and are preserved for review.

Provider errors: SEC bulk issuer records unavailable for AYA, IBN and OZK; public OHLCV unavailable for SVA and TRBG (recorded at prefetch and ticker processing, producing four provider-error rows). Ticker errors: PAAI, SNSC and XLAB had fewer than two completed sessions; SVA and TRBG had no usable history. The scan still completed.

## Score-component operational status

| Component | Status | Reason |
| --- | --- | --- |
| Technical Score | Fully operational | Completed EOD OHLCV supplies all inputs when history is sufficient |
| Liquidity Score | Partially operational | Dollar-volume portion works; institutional-ownership portion unavailable |
| Fundamental Score | Partially operational | Historical SEC trajectories work where concepts exist; business-quality input unavailable |
| Biotech Fundamental Score | Partially operational | Cash-runway portion works for 69 survivors; clinical quality, pipeline importance and external validation unavailable |
| Balance Sheet Score | Partially operational | Cash/debt/derived EBITDA variable; sector adapters and distress classification remain incomplete |
| Catalyst Score | Unavailable | Free events lack frozen materiality, surprise and A/B grade inputs |
| Valuation Score | Unavailable | No reliable free expected-swing-upside/undervaluation input |
| Revision Score | Unavailable | No reliable free consensus revision history |
| Penalties | Mostly unavailable | SEC facts do not deterministically establish guidance cuts, customer loss, accounting concern, dilution, abnormal insider selling, litigation, short float or event volatility under frozen definitions |
| Opportunity Score | Not produced | No scanner-qualified candidate reached scoring |

## Tests and scope

- Tests passed: **79**
- Tests failed: **0**
- Existing frozen investment rules weakened or changed: **none**
- Production scans mixing mock/synthetic financial data: **none**
- Investment Execution Engine v1.7.2 files modified: **NONE**
- Milestone 3 work started: **NO**

Stop point reached. Approval is required before any Milestone 3 work.
