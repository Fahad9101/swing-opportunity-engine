# Phase 1.1E Manual Audit — Round 13

## Outcome

**FAIL — PRE-AUDIT EARLY STOP (systematic guidance table coverage defects)**

- Superseded full-market workflow run: `34140322868` (run 79)
- Audited head SHA: `16b21693d9b5714765ebb09d859395ff9b1a5f47`
- Preflight evidence source: run 78 final artifact `10025030851`
- Preflight snapshot: `dc6e8624ebb3bf21f5de6f9c47bcb2762f74a02cf5e912cbfe62176a1d87cb2e`
- Run 79 final artifact: `10028441098`; all nine automated gates passed, decision `PENDING_MANUAL_AUDIT`
- Governance rule: any systematic audit error blocks activation regardless of numeric concordance.

Run 79 was started to validate the Round 12 INSM/BFLY/TEX repair. While its final two growth shards were processing, all 38 primary SEC guidance documents cited by the preceding deterministic audit queue were downloaded and replayed through the current extractor. This diagnostic replay used synthetic sequential timestamps; it does not reproduce production availability dates or substitute for a fresh 100-item independent audit. It exposed two extraction coverage defects. Run 79 subsequently completed successfully; its automated pass does not resolve these defects or establish manual concordance.

## Blocking preflight case — DGX

The cited Quest Diagnostics releases contain legitimate full-year 2026 comparative guidance tables whose columns are flattened as:

`Updated Guidance | Prior Guidance | Low | High | Low | High`

The table normalizer recognized only prior-first headers and only ranges containing an explicit separator. It therefore missed the valid four-cell current-first rows for net revenues, reported diluted EPS, and adjusted diluted EPS. The residual prose path retained only reported quarterly revenue values mislabeled as EPS; the Round 12 range-locality repair correctly rejected those contaminated records, leaving zero valid DGX guidance records.

The correct extraction deterministically binds:

- first-quarter release: revenue $11.78–$11.90 billion, reported EPS $9.58–$9.78, adjusted EPS $10.63–$10.83;
- second-quarter release: revenue $11.95–$12.05 billion, reported EPS $9.97–$10.17, adjusted EPS $11.05–$11.25.

The unchanged Guidance Ledger classifies the successive same-period increases as `NOT_DETERIORATED` through `guidance_v1_1.comparable_set_within_tolerance`.

Primary sources:

- https://www.sec.gov/Archives/edgar/data/1022079/000102207926000040/dgx033120268-kex991.htm
- https://www.sec.gov/Archives/edgar/data/1022079/000102207926000067/dgx063020268-kex991.htm

## Blocking preflight case — HRMY

The July release reports Q2 actual revenue and then separately reaffirms **2026 net revenue guidance** of $1.0–$1.04 billion. A nearest-period rule rebound that annual range to the preceding Q2 actual period. The August investor presentation expresses the same annual guidance in a flattened value-first row: `$1.00B-$1.04B 2026 NET REVENUE GUIDANCE`, which the metric-first prose extractor did not recognize.

The repair treats an action-qualified bare year such as “reaffirms 2026 ... guidance” as annual scope, and normalizes only the exact structured `range + year + metric + guidance/outlook` layout. The unchanged Guidance Ledger then compares the two identical FY2026 ranges and returns `NOT_DETERIORATED`.

Primary sources:

- https://www.sec.gov/Archives/edgar/data/1802665/000110465926084095/hrmy-20260716xex99d1.htm
- https://www.sec.gov/Archives/edgar/data/1802665/000110465926090086/hrmy-20260804xex99d2.htm

## Repair boundary and verification

The evidence layer now:

- supports both prior-first and current-first comparative headers;
- pairs four explicit low/high monetary cells only inside a verified comparative guidance section;
- keeps one table layout across adjacent metric rows so adjusted EPS cannot borrow the reported-EPS row;
- recognizes plural company-level revenue labels;
- recognizes action-qualified annual guidance scope; and
- normalizes exact value-before-year-before-metric guidance rows.

All 38 cited guidance documents from run 78 were replayed after the repair. The diagnostic replay produced the expected DGX and HRMY comparisons; INSM remained `UNKNOWN`, TEX remained `NOT_DETERIORATED`, and the BFLY cross-metric duplicate remained absent as required by Round 12. BX's standing-policy evidence was not supplied to this numeric-only replay, and the synthetic timestamps do not validate ALSN's dated same-document prior links. Those cases remain unadjudicated, as does the fresh run-79 audit queue.

The full deterministic suite passes: **526 passed, 0 failed**, with two known dependency deprecation warnings. Regressions also require explicit low/high columns and reject unscaled monetary rows.

## Governance

- SOE-1.0.0 remains active and frozen.
- SOE-1.1.0 is not promoted.
- PR #16 remains unmerged and draft.
- Milestone 3 remains blocked.
- No threshold, score, weight, scanner, ranking, classification, technical, catalyst, market-regime, SOE-1.0.0, or IEE v1.7.2 logic is changed.

## Required next step

Run a fresh full-market validation at the repaired head, verify all automated gates and the DGX/HRMY/INSM/BFLY/TEX live outcomes, then execute a brand-new 100-item independent audit under the unchanged contract.
