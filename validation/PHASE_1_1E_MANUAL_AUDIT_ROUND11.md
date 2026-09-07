# Phase 1.1E Manual Audit — Round 11

## Outcome

**FAIL — EARLY STOP (systematic conditional-default evidence defect)**

- Full-market workflow run: `34010590821` (run 77)
- Final artifact: `9983597584`
- Audited head SHA: `9bcc652b1c91b2ceba2fc28e1f37199d0e51966e`
- Captured snapshot: `a3b045b6941212e84a88092c280c52e53748070b1c04ba85d0622d433280c7eb`
- Baseline scan run: `09992241-c310-4fcc-b9b1-df640a697b60`
- Automated decision before manual review: `PENDING_MANUAL_AUDIT`
- Required manual sample: 100
- Required concordance: >=95%
- Governance rule: any systematic audit error blocks activation regardless of numeric concordance.

All nine automated gates passed. The fresh deterministic audit queue contained 100 classifications: 25 balance-sheet distress, 26 catalyst materiality, 28 catalyst surprise, and 21 guidance.

Audit positions 1–17 were concordant after independently recomputing the persisted rule inputs and inspecting the cited primary SEC evidence where document semantics mattered. That prefix contained five balance-sheet distress classifications, three catalyst-materiality classifications, seven catalyst-surprise classifications, and two guidance classifications. The cited catalyst documents were quarterly reports, earnings-results filings, or current reports that disclosed completed results. The guidance sources supported a same-period reaffirmation for EOLS and increases for Planet Labs.

Audit adjudication was intentionally stopped at global sample position 18 after the SM defect below was reproduced through the exact production hard-distress extraction path. A final 100-item numeric concordance percentage is not reported because the locked contract requires early stop once a systematic error is established.

## Blocking sampled case — SM

Engine classification:

- Audit position: 18
- Domain: balance-sheet distress
- Engine result: `DISTRESSED`
- Engine rule path: `balance_sheet_distress_v1_1.universal_hard_override`
- Engine hard flag: `payment_default`

The cited filing does not state that SM Energy is currently in payment default. It describes a hypothetical covenant sequence: exceeding a permitted leverage ratio means the company **would be in default**, followed by remedies available **if we are in default** and cannot obtain a waiver. The extractor matched the conditional `if we are in default` clause as an unconditional present payment default.

Without that false hard flag, the persisted record has insufficient supported numeric inputs for either a frozen distress path or a frozen safety path. The correct outcome is therefore `UNKNOWN` through `balance_sheet_distress_v1_1.corporate.unknown`, not `DISTRESSED`.

Primary source:

- https://www.sec.gov/Archives/edgar/data/893538/000089353826000121/sm-20260630.htm

## Root cause and repair boundary

The base hard-distress extractor requires present-tense registrant language, but a conditional clause has the same local verb shape. The Phase 1.1E evidence filter previously applied hypothetical-language rejection only to `unresolved_covenant_breach`, not to `payment_default`.

The repair requires an unconditional current-default match before retaining a payment-default hard flag. It must continue to preserve a genuine current payment default.

During the already-batched guidance evidence replay, an additional row-boundary issue was observed in MOD: ranges for interest expense were being attached to the preceding adjusted-EBITDA label. Those ranges are not EBITDA guidance. The repair therefore also treats interest expense, income taxes, depreciation, and amortization as financial row boundaries. This is extraction-layer hygiene only; the official Round 11 adjudication remains stopped at position 18.

## Governance

- SOE-1.0.0 remains active and frozen.
- SOE-1.1.0 is not promoted.
- PR #16 remains unmerged and draft.
- Milestone 3 remains blocked.
- No threshold, score, weight, scanner, ranking, classification, technical, catalyst, market-regime, SOE-1.0.0, or IEE v1.7.2 logic is changed.

## Required next step

Protect both the conditional-default rejection and genuine-current-default path with regressions, protect the MOD row boundary, then run a fresh full-market validation and a brand-new independent audit under the unchanged contract.
