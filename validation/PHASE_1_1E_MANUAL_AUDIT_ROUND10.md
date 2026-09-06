# Phase 1.1E Manual Audit — Round 10

## Outcome

**FAIL — EARLY STOP (systematic EPS accounting-basis evidence-binding defect)**

- Full-market workflow run: `33988186112` (run 76)
- Final artifact: `9977263615`
- Audited head SHA: `4308d7423d180f7dd708ba1c26efce6f3473bfd2`
- Captured snapshot: `b96be4abf3cf2275be22de6f27a516d3ce5446b68fecbc7c5e34122139e952b5`
- Baseline scan run: `04dd1c5d-80a8-42a4-ae58-3b9d9fe2f37d`
- Automated decision before manual review: `PENDING_MANUAL_AUDIT`
- Required manual sample: 100
- Required concordance: >=95%
- Governance rule: any systematic audit error blocks activation regardless of numeric concordance.

All nine automated gates passed. The fresh deterministic audit queue contained 100 classifications across guidance, balance-sheet distress, catalyst materiality, and catalyst surprise.

Audit positions 1–34 were concordant after recomputing the persisted rule inputs and inspecting the cited primary SEC evidence where document semantics mattered. That prefix contained 13 balance-sheet distress classifications, 7 catalyst-materiality classifications, 7 catalyst-surprise classifications, and 7 guidance classifications. The catalyst evidence check confirmed that the cited documents were earnings/results filings rather than unrelated exhibits. The guidance checks confirmed same-period raises or reaffirmations for BG, LFST, ATMU, GRMN, PTCT, Q, and EOLS.

Audit adjudication was intentionally stopped at global sample position 35 after the ETN defect below was reproduced through the exact extraction and Guidance Ledger path. A final 100-item numeric concordance percentage is not reported because the locked contract requires early stop once a systematic error is established.

## Blocking sampled case — ETN

Engine classification:

- Audit position: 35
- Domain: guidance
- Engine result: `NOT_DETERIORATED`
- Engine rule path: `guidance_v1_1.comparable_set_within_tolerance`
- Engine comparable pair: adjusted EPS, $11.57–$12.07 to $13.40–$13.60

The engine pair is invalid because the prior $11.57–$12.07 range is unadjusted/GAAP EPS, not adjusted EPS.

Primary SEC evidence:

- Initial full-year 2026 EPS: **$11.57–$12.07**
- Initial full-year 2026 adjusted EPS: **$13.00–$13.50**
- Updated full-year 2026 EPS: **$10.36–$10.56**
- Updated full-year 2026 adjusted EPS: **$13.40–$13.60**

The same-period GAAP EPS midpoint fell from $11.82 to $10.46, a **−11.51%** change. This exceeds the unchanged frozen 5% material-cut threshold and must classify as `DETERIORATED` through `guidance_v1_1.material_numeric_cut`.

Primary sources:

- https://www.sec.gov/Archives/edgar/data/1551182/000155118226000002/etn12312025exhibit99.htm
- https://www.sec.gov/Archives/edgar/data/1551182/000155118226000027/etn06302026exhibit99.htm

## Reproduction and root cause

The production extractor was replayed against the exact cited SEC documents. Before repair it persisted the prior GAAP range as `ADJUSTED`, retained the current adjusted range, rejected or omitted the current GAAP range, and therefore reported an adjusted EPS increase.

Two deterministic normalization gaps caused this:

1. the metric-local row validator did not include the plain phrase `earnings per share`; and
2. an adjacent `adjusted earnings per share` row could lend its accounting basis to the preceding unqualified EPS range.

This is a systematic evidence-normalization defect for releases that present GAAP and adjusted EPS guidance together. It is not an SOE investment-rule defect.

## Governance

- SOE-1.0.0 remains active and frozen.
- SOE-1.1.0 is not promoted.
- PR #16 remains unmerged and draft.
- Milestone 3 remains blocked.
- No threshold, score, weight, scanner, ranking, classification, technical, catalyst, market-regime, SOE-1.0.0, or IEE v1.7.2 logic is changed.

## Required repair

Bind a persisted EPS range to its own local adjusted or unqualified metric label before admitting it to the ledger. Prefer a preceding prose label over an adjacent following label that belongs to the next flattened row. Protect both the GAAP material-cut path and a valid adjusted-EPS row with regression tests, then run a fresh full-market validation and a brand-new independent audit under the unchanged contract.
