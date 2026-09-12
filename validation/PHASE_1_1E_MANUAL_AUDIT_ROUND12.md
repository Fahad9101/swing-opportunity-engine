# Phase 1.1E Manual Audit — Round 12

## Outcome

**FAIL — EARLY STOP (systematic fiscal-period row-binding defect)**

- Full-market workflow run: `34129172850` (run 78)
- Final artifact: `10025030851`
- Audited head SHA: `19fbd729e5f8d29352a4c4ab66ff89667a369348`
- Captured snapshot: `dc6e8624ebb3bf21f5de6f9c47bcb2762f74a02cf5e912cbfe62176a1d87cb2e`
- Baseline scan run: `058c0b69-c2b4-403d-a837-9559cf6b3b16`
- Automated decision before manual review: `PENDING_MANUAL_AUDIT`
- Required manual sample: 100
- Required concordance: >=95%
- Governance rule: any systematic audit error blocks activation regardless of numeric concordance.

All nine automated gates passed. The fresh deterministic audit queue contained 100 classifications: 31 balance-sheet distress, 20 catalyst materiality, 30 catalyst surprise, and 19 guidance.

Audit positions 1–8 were concordant after independently recomputing the persisted rule inputs and inspecting the cited primary SEC evidence where document semantics mattered. That prefix contained two balance-sheet distress classifications, two catalyst-materiality classifications, three catalyst-surprise classifications, and one guidance classification.

Audit adjudication was intentionally stopped at global sample position 9 after the INSM defect below was reproduced through the exact production extraction and Guidance Ledger path. A final 100-item numeric concordance percentage is not reported because the locked contract requires early stop once a systematic error is established.

## Blocking sampled case — INSM

Engine classification:

- Audit position: 9
- Domain: guidance
- Engine result: `NOT_DETERIORATED`
- Engine rule path: `guidance_v1_1.comparable_set_within_tolerance`
- Engine comparable pair: ARIKAYCE revenue guidance, $420–$430 million to $450–$470 million, labeled `FY2025`

The cited primary releases do not provide a same-period pair. The September 2025 release raises **full-year 2025** ARIKAYCE revenue guidance to $420–$430 million. The February 2026 release provides/reiterates **full-year 2026** ARIKAYCE revenue guidance of $450–$470 million and separately reports total-company revenue for full-year 2025.

The extractor created both a correct `FY2026` record and an invalid duplicate `FY2025` record for the $450–$470 million range. The invalid record borrowed `Full-Year 2025` from the following reported-results row: “Total Company Revenues of $606.4 Million for Full-Year 2025.” Without that cross-row period binding, there is no same-period prior/current pair, so the correct result is `UNKNOWN` through `guidance_v1_1.no_comparable_prior`.

Primary sources:

- https://www.sec.gov/Archives/edgar/data/1104506/000114036125039789/ef20057768_ex99-1.htm
- https://www.sec.gov/Archives/edgar/data/1104506/000114036126006116/ef20066055_ex99-1.htm

## Additional observed evidence defects

The guidance evidence documents were cached and replayed as a batch before audit adjudication. Two later queue entries exposed related metric/value locality gaps; they are recorded here without changing the official early-stop position:

- BFLY: the revenue range $117–$121 million was also attached to the following adjusted-EBITDA label even though the actual adjusted-EBITDA guidance was a $21–$25 million loss.
- TEX: reconciliation-table cells $14 and $13 were persisted as free-cash-flow guidance, producing a false material cut even though the cited releases maintained full-year FCF guidance at $300–$350 million.

The repair therefore requires: fiscal-period locality across metric rows; preventing a following metric label with its own value from borrowing the preceding range; and rejecting an unstructured monetary scalar when its value is absent from its retained evidence span. These are evidence-normalization constraints only.

## Governance

- SOE-1.0.0 remains active and frozen.
- SOE-1.1.0 is not promoted.
- PR #16 remains unmerged and draft.
- Milestone 3 remains blocked.
- No threshold, score, weight, scanner, ranking, classification, technical, catalyst, market-regime, SOE-1.0.0, or IEE v1.7.2 logic is changed.

## Required next step

Protect INSM, BFLY, and TEX with regressions, run the full deterministic suite, then execute a fresh full-market validation and a brand-new independent audit under the unchanged contract.
