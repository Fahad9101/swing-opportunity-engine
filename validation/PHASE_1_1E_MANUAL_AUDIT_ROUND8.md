# Phase 1.1E Manual Audit — Round 8

## Outcome

**FAIL — EARLY STOP (systematic evidence-binding defect)**

- Full-market run: `33973245276`
- Head SHA: `7adf602f025aedc740b9d1a4a8fd94d46ad6f6e7`
- Automated decision before manual review: `PENDING_MANUAL_AUDIT`
- Required manual sample: 100
- Required concordance: >=95%
- Governance rule: any systematic audit error blocks activation regardless of numeric concordance.

The audit was intentionally stopped during guidance-domain adjudication after a new systematic table-binding defect was confirmed. A final concordance percentage was **not** computed because the locked contract requires early stop once a systematic defect is established.

## Blocking case — ALSN

Engine classification:

- Ticker: `ALSN`
- Domain: guidance
- Engine result: `DETERIORATED`
- Engine reason: material numeric cut in `revenue`

Primary SEC evidence contradicts the engine classification.

Initial FY2026 guidance (February 23, 2026):

- Consolidated net sales: **$5,575M–$5,925M**

Updated FY2026 guidance (August 3, 2026 presentation):

- Prior guide: **$5,575M–$5,925M**
- Updated guide: **$5,800M–$6,000M**
- Prior midpoint: **$5,750M**
- Updated midpoint: **$5,900M**

Revenue guidance therefore increased, not decreased.

Primary sources:

- https://www.sec.gov/Archives/edgar/data/1411207/000119312526063975/d105532dex991.htm
- https://www.sec.gov/Archives/edgar/data/1411207/000119312526330544/d95413dex992.htm

## Root cause

The August presentation contains a flattened comparative guidance table:

`Full Year 2026 Guidance Update ($ in millions) Prior Guide Updated Guide ... Net Sales ... Net Income ... Adjusted EBITDA ...`

Two structural hazards are present:

1. **Table-level unit propagation** — row values such as `$5,800 to $6,000` inherit `millions` from the table header. Treating the row as literal dollars creates an artificial multi-order-of-magnitude cut versus a prior release that spells out `million` on the row.
2. **Flattened row binding** — after HTML/presentation flattening, a metric label can be followed by midpoint values and then the next metric row's numeric range. A generic "range after metric" routine can therefore bind the next row's numbers to the current metric.

This is a systematic comparative-guidance-table normalization defect, not an SOE decision-rule defect.

## Governance

- SOE-1.0.0 remains active.
- SOE-1.1.0 is not promoted.
- PR #16 remains unmerged/draft.
- Milestone 3 remains blocked.
- No threshold, weight, score, scanner, ranking, technical, catalyst, market-regime, SOE-1.0.0, or IEE v1.7.2 logic is changed.

## Required repair

Do not add another ticker-specific regex patch. Replace comparative-guidance-table handling with a normalized evidence layer that binds, before ledger comparison:

`Ticker | Metric | Fiscal Scope | Accounting Basis | Table Unit | Prior Range | Updated Range | Direction | Primary Source`

The normalized table record must override conflicting generic extraction records from the same source/metric/period. A new full-market run and a brand-new independent >=100-name audit are required after the evidence architecture changes.
