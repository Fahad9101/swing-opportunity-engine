# Milestone 2.5J — Free-Data Reliability & Scoring-Completeness Hardening

Generated: 2026-09-01T09:18:09.218482+00:00
Model: `SOE-1.0.0`
Rules hash: `59cc7ffe14472434bfbb92b07b89b0b48293d0c5762d5270769bce3b494550ac`
Scan run ID: `9b73fe20-87ac-43fc-94f0-62e5ef5ffd71`

## Integrity result

This validation changes no SOE-1.0.0 investment threshold, score weight, scanner condition, classification, or Investment Execution Engine v1.7.2 logic.
The Yahoo change is transport-only: one shared authenticated/cache payload per ticker, serialized requests, deterministic throttling, and explicit 429 backoff.

## Full-market funnel

| Metric | Result |
| --- | ---: |
| Universe | 5156 |
| Universal-gate survivors | 2331 |
| Technical-ready survivors | 2309 |
| Re-Rating qualified | 231 |
| Growth Pullback qualified | 0 |
| Biotech/Catalyst qualified | 0 |
| Deduplicated opportunities | 231 |
| Fully scored opportunities | 0 |

## Provider reliability

Total provider errors: **7**  
Shared Yahoo errors: **0**  
Yahoo authentication/rate-limit errors: **0**

```json
{
  "SEC_BULK_READ_ERROR": 3,
  "TICKER_DATA_UNAVAILABLE": 4
}
```

## Exact DATA_INCOMPLETE fields

### RERATING

Incomplete rows: **780**

```json
{
  "fcf_or_ebitda_improving": 757,
  "forward_eps_growth": 155,
  "margin_improving": 425,
  "positive_revisions": 63,
  "revenue_growth_qoq": 273,
  "valuation_discount": 587
}
```

### GROWTH_PULLBACK

Incomplete rows: **989**

```json
{
  "balance_sheet_not_distressed": 989,
  "growth_driver": 423,
  "no_guidance_deterioration": 989,
  "no_strong_negative_revisions": 83,
  "revenue_growth": 375
}
```

### BIOTECH_CATALYST

Incomplete rows: **245**

```json
{
  "cash_runway_eligible": 89,
  "verified_grade_a_or_b_catalyst": 245
}
```

## Field availability among persisted snapshots

Fundamental snapshots: **1951**

```json
{
  "balance_sheet_distressed": 0,
  "cash_runway_months": 233,
  "expected_swing_upside": 1689,
  "fcf_growth": 206,
  "financing_secured": 234,
  "forward_ebitda_growth": 0,
  "fundamental_undervaluation": 978,
  "guidance_deterioration": 0,
  "institutional_ownership": 1947,
  "operating_margin_expansion_bps": 1490,
  "short_float": 1936,
  "valuation_discount": 978
}
```

Estimate snapshots: **2328**

```json
{
  "ebitda_down_revisions": 0,
  "ebitda_up_revisions": 0,
  "eps_down_revisions": 2296,
  "eps_revision_30d": 2276,
  "eps_revision_90d": 2258,
  "eps_up_revisions": 2296,
  "forward_ebitda": 0,
  "forward_eps_growth": 1986,
  "forward_revenue": 2328,
  "revenue_down_revisions": 0,
  "revenue_up_revisions": 0
}
```

## Scoring completeness

Scanner-qualified opportunities: **231**

Unavailable components across those opportunities:

```json
{
  "balance_sheet": 48,
  "catalyst": 231,
  "fundamental": 7,
  "liquidity": 0,
  "revisions": 0,
  "technical": 0,
  "valuation": 11
}
```

Corporate events persisted: **424**  
Catalyst-candidate events: **367**  
Fully scored catalysts: **0**

Missing fields on catalyst-candidate events:

```json
{
  "materiality": 367,
  "surprise_potential": 367
}
```

## Structural free-stack blockers

- All scanner-qualified opportunities lack the frozen Catalyst Score because structured free/public events do not supply materiality and surprise/re-rating potential.
- Guidance deterioration remains unavailable because SOE-1.0.0 contains no frozen deterministic text-to-guidance classifier; no new heuristic was invented.
- Growth-Pullback balance-sheet distress state remains unavailable because SOE-1.0.0 contains no frozen cross-sector distress classifier; no new threshold was invented.

## Top 20 discovery opportunities

| Rank | Ticker | Scanner | Opportunity Score | Catalyst | Fundamental | Valuation | Technical | Revisions | Balance Sheet | Liquidity |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | AMZN | RERATING | 50.00 | NA | 11.00 | 16.00 | 10.00 | 5.00 | 3.00 | 5.00 |
| 2 | MU | RERATING | 48.00 | NA | 15.00 | 12.00 | 7.00 | 4.00 | 5.00 | 5.00 |
| 3 | DAR | RERATING | 47.00 | NA | 14.00 | 11.00 | 11.00 | 5.00 | 1.00 | 5.00 |
| 4 | JLL | RERATING | 47.00 | NA | 10.00 | 11.00 | 11.00 | 5.00 | 5.00 | 5.00 |
| 5 | RBRK | RERATING | 47.00 | NA | 15.00 | 6.00 | 11.00 | 5.00 | 5.00 | 5.00 |
| 6 | FRPT | RERATING | 46.00 | NA | 13.00 | 10.00 | 13.00 | 0.00 | 5.00 | 5.00 |
| 7 | ANET | RERATING | 46.00 | NA | 13.00 | 6.00 | 12.00 | 5.00 | 5.00 | 5.00 |
| 8 | APH | RERATING | 46.00 | NA | 15.00 | 6.00 | 10.00 | 5.00 | 5.00 | 5.00 |
| 9 | RDW | RERATING | 46.00 | NA | 10.00 | 16.00 | 6.00 | 4.00 | 5.00 | 5.00 |
| 10 | GOOGL | RERATING | 45.00 | NA | 8.00 | 16.00 | 10.00 | 5.00 | 1.00 | 5.00 |
| 11 | DNOW | RERATING | 44.50 | NA | 9.00 | 11.00 | 11.00 | 4.00 | 5.00 | 4.50 |
| 12 | TPC | RERATING | 44.50 | NA | 12.00 | 10.00 | 8.00 | 5.00 | 5.00 | 4.50 |
| 13 | KEYS | RERATING | 44.00 | NA | 15.00 | 8.00 | 10.00 | 5.00 | 1.00 | 5.00 |
| 14 | CTRN | RERATING | 44.00 | NA | 12.00 | 10.00 | 8.00 | 5.00 | 5.00 | 4.00 |
| 15 | GFF | RERATING | 43.50 | NA | 6.00 | 16.00 | 11.00 | 5.00 | 1.00 | 4.50 |
| 16 | QTWO | RERATING | 43.50 | NA | 10.00 | 11.00 | 8.00 | 5.00 | 5.00 | 4.50 |
| 17 | LTH | RERATING | 43.00 | NA | 10.00 | 10.00 | 12.00 | 5.00 | 1.00 | 5.00 |
| 18 | BAX | RERATING | 43.00 | NA | 11.00 | 6.00 | 11.00 | 5.00 | 5.00 | 5.00 |
| 19 | CVLT | RERATING | 42.50 | NA | 11.00 | 11.00 | 11.00 | 5.00 | NA | 4.50 |
| 20 | HRTG | RERATING | 42.00 | NA | 12.00 | 7.00 | 14.00 | 5.00 | NA | 4.00 |

## Milestone 2.5 decision gate

Milestone 2.5J is a data-layer validation milestone only. If the shared Yahoo adapter is operationally stable but the Catalyst Score remains structurally unavailable, the report must say so explicitly rather than manufacturing materiality/surprise values. Any future change to those frozen scoring inputs belongs in a separately approved model version, not a silent SOE-1.0.0 modification.
