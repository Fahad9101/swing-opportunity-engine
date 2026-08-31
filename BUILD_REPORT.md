# Milestones 1–2.5 build report

## Identity and scope

- Model: Swing Opportunity Engine `SOE-1.0.0`
- Rules/config SHA-256: `59cc7ffe14472434bfbb92b07b89b0b48293d0c5762d5270769bce3b494550ac`
- Scope: Milestones 1–2 plus free/public-data validation
- Paid providers required: none
- Milestone 3: not started

## Added in free-data Milestone 2.5

- Free-public composite provider and provider registry wiring; `production` aliases the same non-fixture stack.
- SEC EDGAR bulk company-facts normalizer and resumable segmented archive downloader.
- Replaceable prototype EOD OHLCV adapter with completed-session normalization.
- Nasdaq public metadata, Nasdaq earnings calendar, Cboe VIX, and ClinicalTrials.gov v2 adapters.
- Explicit `DATA_INCOMPLETE` scanner outcomes and per-domain availability flags.
- Improved preferred, debt, CEF, partnership-unit, SPAC/unit, and ADR normalization.
- Trading-session-aware freshness, structured provider errors, and suspicious-output validation.
- Regression tests for public-provider normalization, SEC null preservation, free production selection, ClinicalTrials event semantics, asset-type edge cases, and incomplete scanner conditions.

## Verification

- Tests: **79 passed, 0 failed**
- Warning: one third-party Starlette `TestClient` deprecation warning
- Real completed-EOD scan: **COMPLETED**
- Initial cleaned universe: **5,156**
- Universal-gate survivors: **2,331**
- Technical-ready survivors: **2,310**
- Qualified candidates: **0**
- Fixture/mock inputs in production run: **none**

See `MILESTONE_2_5_REPORT.md` for the full funnel, completeness, validation counts, and five manual audits.

## Scope confirmation

Investment Execution Engine v1.7.2 files modified: **NONE**.

Milestone 3 was not started.
