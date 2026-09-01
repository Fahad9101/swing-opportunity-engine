# Swing Opportunity Engine SOE-1.1.0 — Structural Input Specification

Status: DESIGN-LOCK CANDIDATE. This document is design only; it does not activate SOE-1.1.0 in production.

## 1. Purpose

SOE-1.1.0 exists to solve the structural completeness gaps proven by the final Milestone 2.5J full-market validation while preserving the investment philosophy and all unaffected SOE-1.0.0 rules.

SOE-1.1.0 changes only the deterministic definitions required to populate four previously unresolved fields:

1. Catalyst `materiality` (0-10).
2. Catalyst `surprise_potential` / re-rating potential (0-5).
3. `guidance_deterioration` (tri-state true / false / null).
4. `balance_sheet_distressed` (tri-state true / false / null).

The Catalyst Score remains 25 points exactly: materiality 0-10 + timing 0-5 + date confidence 0-5 + surprise/re-rating potential 0-5. All other SOE-1.0.0 universe gates, scanner thresholds, score weights, penalties, market-regime rules, classifications, and the Investment Execution Engine v1.7.2 remain unchanged unless separately approved.

## 2. Governance invariants

- SOE-1.0.0 remains immutable and reproducible under its existing rules hash.
- SOE-1.1.0 receives a new model version and rules hash.
- Missing evidence is never converted to zero or to a favorable state.
- Absence of a negative filing is not evidence of safety.
- A language model may extract structured facts from public source text, but may not assign a score, classification, or threshold result.
- Every scored catalyst and every guidance/distress classification must preserve source, source timestamp, extracted evidence, normalized values, rule path, and decision reason.
- Conflicting primary-source evidence resolves to null unless a newer authoritative source clearly supersedes the older source.
- No event is scored merely because an event date exists.

## 3. Source hierarchy

Primary evidence, in order of authority:

1. SEC 10-K, 10-Q, 8-K, 6-K and filed exhibits such as earnings releases.
2. FDA or other regulator primary notices; ClinicalTrials.gov for registered trial design/status/date facts.
3. Company investor-relations releases and presentations when the same item is not yet filed with the SEC.
4. Exchange/public calendar feeds for dates only.
5. Analyst-consensus and ownership/short-interest prototype feeds for quantitative expectation context only.

Secondary/news text may be used for discovery but cannot by itself make a catalyst scoring-ready, guidance deterioration false, or balance-sheet distress false.

## 4. Catalyst materiality: deterministic 0-10

Materiality measures the magnitude of the business/valuation consequence if the event outcome is meaningfully positive or negative. It does not predict direction.

`materiality = event_class_base + economic_exposure + consequence_severity`, capped at 10.

All three components must be determinable. If any required component is unknown, materiality is null and the catalyst is not scoring-ready.

### 4.1 Event-class base: 0-5

| Base | Event class |
| ---: | --- |
| 5 | FDA/PDUFA/AdCom or equivalent regulatory decision; pivotal/Phase 3 primary-endpoint readout; merger approval/close with material deal certainty impact; final court/regulatory ruling capable of changing company viability or core economics |
| 4 | Quarterly earnings with formal financial results; formal full-year guidance update; Phase 2 proof-of-concept readout; major reimbursement decision; investor day that includes new multi-year financial targets |
| 3 | Phase 1/2 clinical data update with efficacy signal; disclosed major contract/customer award; product launch with disclosed economics; material refinancing/covenant event; strategic review outcome |
| 2 | Non-pivotal study update; conference presentation expected to contain new data; ordinary product/segment update with measurable but non-core economics |
| 1 | Routine investor presentation or conference appearance with no verified new data/targets expected |
| 0 | Administrative, unverifiable, duplicated, or non-economic event |

Administrative/base-0 events are not catalyst candidates.

### 4.2 Economic exposure: 0-3

For conventional companies use the best verified measure of revenue, EBITDA/operating-income, FCF, asset value, or segment contribution attributable to the event.

| Score | Exposure |
| ---: | --- |
| 3 | Company-wide event, or >=20% of relevant revenue/EBITDA/FCF/value; for biotech, lead/single asset representing >=50% of probability-adjusted pipeline value |
| 2 | 10% to <20%, or a major segment/asset with meaningful diversification elsewhere; biotech asset 25% to <50% of pipeline value |
| 1 | 5% to <10%, or a meaningful but non-core segment/asset; biotech asset 10% to <25% of pipeline value |
| 0 | <5% / immaterial exposure |

Special deterministic defaults:

- Company-wide quarterly earnings: exposure = 3.
- Company-wide formal annual guidance update: exposure = 3.
- Single-asset biotech lead program: exposure = 3 if documented as the only or dominant clinical-value asset.

Unknown exposure is null, not zero.

### 4.3 Consequence severity: 0-2

| Score | Consequence |
| ---: | --- |
| 2 | Binary or threshold event that can directly permit/prohibit commercialization, materially alter financing/covenant viability, approve/terminate a transaction, or establish/fail a pivotal primary endpoint |
| 1 | Event can materially change estimates, margins, growth trajectory, or strategic execution but is not a direct binary permission/viability threshold |
| 0 | Primarily informational with limited near-term estimate impact |

Quarterly earnings receive consequence = 1; earnings that simultaneously contain a formal full-year guidance initiation/raise/cut/withdrawal receive consequence = 2.

## 5. Catalyst surprise / re-rating potential: deterministic 0-5

This score measures how much the market's valuation/expectation set could plausibly reset around the event. It is not a forecast that the surprise will be positive.

`surprise_potential = outcome_binaryity + expectation_uncertainty + valuation_concentration`, capped at 5.

### 5.1 Outcome binaryity: 0-2

| Score | Definition |
| ---: | --- |
| 2 | Hard yes/no or primary-threshold outcome: FDA/PDUFA/AdCom decision, pivotal primary endpoint, merger vote/approval, covenant/default/refinancing deadline, final material ruling |
| 1 | Earnings, formal guidance update, Phase 2 proof-of-concept, reimbursement decision, new long-term targets |
| 0 | Mainly incremental/informational event |

### 5.2 Expectation uncertainty: 0-2

The rule path depends on event family.

**Earnings / guidance events**

Use analyst-consensus ranges from the latest available estimate snapshot. Prefer EPS dispersion; if EPS average is near zero or sign-changing, use revenue dispersion.

`dispersion = (high_estimate - low_estimate) / abs(consensus_average)`.

- >=20%: 2
- >=10% and <20%: 1
- <10%: 0

If high/low consensus is unavailable, use 90-day consensus instability on the primary metric:

- absolute change >=10%: 2
- >=5% and <10%: 1
- <5%: 0

If neither dispersion nor consensus-instability evidence is available, this component is null.

**Clinical / regulatory events**

- 2: pivotal/registrational or regulatory decision where the decisive endpoint/approval outcome remains unresolved and there is no identical prior confirmatory result that effectively predetermines the decision.
- 1: Phase 2 proof-of-concept or label-expansion decision supported by meaningful prior human efficacy evidence.
- 0: confirmatory/administrative event where the primary economic conclusion is already known from a definitive prior result.

The facts above must be extracted from ClinicalTrials.gov plus primary company/regulatory evidence. If prior-evidence status is ambiguous, this component is null.

**Transaction / legal / financing events**

- 2: binary approval/close/default outcome with unresolved material contingency.
- 1: event has multiple plausible economic outcomes but no existential contingency.
- 0: routine administrative milestone.

### 5.3 Valuation concentration: 0-1

- 1 if economic exposure score = 3.
- 0 if economic exposure score <=2.
- null if economic exposure is null.

All required subcomponents must be available. A null subcomponent makes surprise potential null.

## 6. Guidance deterioration classifier

`guidance_deterioration` is tri-state.

- `true` means verified material deterioration.
- `false` means verified no material deterioration under a comparable guidance set.
- `null` means evidence is missing, non-comparable, conflicting, or insufficient.

### 6.1 Guidance normalization

For each company, build a versioned guidance ledger by fiscal period and metric. Supported primary metrics:

- revenue
- adjusted or GAAP EPS
- EBITDA / adjusted EBITDA
- FCF
- operating margin / gross margin

Each record stores low, high, midpoint, unit, accounting basis, fiscal period, source date, source URL/accession, and whether management explicitly labeled the change raise/reaffirm/cut/withdrawal.

Comparisons are only allowed for the same fiscal period, same metric, and materially comparable accounting basis.

### 6.2 Deterioration = true

Set true if any of the following is verified:

1. Management explicitly withdraws/suspends previously issued company-level guidance.
2. Management explicitly states that it lowered/reduced/cut company-level guidance.
3. Comparable midpoint cut reaches a material threshold:
   - revenue: >=2% lower
   - EPS: >=5% lower
   - EBITDA / adjusted EBITDA: >=5% lower
   - FCF: >=5% lower
   - gross or operating margin: >=100 bps lower
4. Two or more supported primary metrics are each reduced, even if each individual reduction is below its single-metric threshold, provided each reduction is >=1% for revenue/earnings/cash-flow metrics or >=50 bps for margins.

### 6.3 Deterioration = false

Set false only when a comparable prior guidance set exists and all supported primary metrics are within the non-deterioration tolerances or raised, and there is no verified cut/withdrawal language.

A company with an explicit standing policy of not issuing quantitative guidance may be assigned false only if that policy is verified in a primary source and there is no withdrawal of previously issued guidance for the current period.

A one-off absence of guidance is not false; it remains null unless the company explicitly states a no-guidance policy.

### 6.4 Null cases

Return null when:

- there is no comparable prior guidance,
- fiscal periods or accounting bases differ materially,
- only secondary summaries are available,
- guidance language conflicts with the numeric table and the conflict cannot be resolved,
- the company stopped giving guidance without clearly stating whether prior guidance was withdrawn.

## 7. Balance-sheet distress classifier

`balance_sheet_distressed` is tri-state and sector-aware. False is a positive evidence state, not the absence of a warning.

### 7.1 Universal hard-distress overrides

Set true for any sector if a primary source verifies:

- going-concern/substantial-doubt language,
- bankruptcy/restructuring filing,
- payment default or unresolved covenant breach,
- auditor statement that financial statements cannot be relied upon because of unresolved solvency/liquidity issues,
- explicit inability to meet obligations over the next 12 months without uncommitted financing.

### 7.2 Non-financial corporate adapter

Required derived metrics where applicable:

- net debt / EBITDA
- interest coverage = EBIT or operating income / interest expense
- liquidity coverage = (cash + marketable securities + committed undrawn revolver + max(0, trailing FCF)) / debt maturities due within 12 months
- cash runway for negative-FCF companies

Set `true` if any of these deterministic paths is satisfied:

1. net debt / EBITDA >5.0 AND interest coverage <2.0.
2. interest coverage <1.0 with positive debt outstanding.
3. liquidity coverage <1.0 and refinancing/financing is not verified secured.
4. negative-FCF company has cash runway <12 months and financing is not verified secured.

Set `false` only if no hard-distress override exists and at least one safety path is satisfied:

1. net cash position; or
2. net debt / EBITDA <=3.0 AND interest coverage >=3.0; or
3. liquidity coverage >=1.5 AND trailing FCF is positive; or
4. negative-FCF company has cash runway >=18 months.

Otherwise return null.

### 7.3 Utilities adapter

Because regulated utilities structurally carry higher leverage:

- true if net debt / EBITDA >7.0 AND interest coverage <1.5, or liquidity coverage <1.0 without secured refinancing.
- false if net debt / EBITDA <=5.5 AND interest coverage >=2.0 and no hard-distress override.
- otherwise null.

### 7.4 REIT adapter

Prefer debt / EBITDAre and fixed-charge coverage when publicly available.

- true if debt / EBITDAre >8.0 AND fixed-charge coverage <1.5, or liquidity coverage <1.0 without secured refinancing.
- false if debt / EBITDAre <=6.5 AND fixed-charge coverage >=2.0 and no hard-distress override.
- otherwise null.

### 7.5 Banks and insurers

Do not use corporate leverage ratios.

**Banks**

- true if a primary regulatory filing shows a regulatory-capital breach, unresolved prompt-corrective-action condition, or CET1 ratio below the institution-specific required minimum plus regulatory buffer.
- false only if CET1 exceeds the applicable requirement plus buffer by >=250 bps and there is no hard-distress override.
- otherwise null.

**Insurers**

Use regulator-reported solvency/RBC capital only when a standardized required threshold and company ratio are available from a primary filing.

- true if below the applicable regulatory action threshold.
- false if >=1.5x the applicable regulatory action threshold and no hard-distress override.
- otherwise null.

If sector-specific regulatory data cannot be normalized deterministically, return null rather than substituting corporate debt/EBITDA.

## 8. Evidence extraction and AI boundary

A text model may convert a primary document into candidate structured facts such as:

- `metric=Revenue`, `period=FY2027`, `low=...`, `high=...`
- `language=lowered guidance`
- `trial_phase=Phase 3`, `primary_endpoint=...`, `readout_window=...`
- `going_concern=true`, `covenant_breach=true`, `maturity_amount=...`

The deterministic engine must then:

1. verify the source is allowed,
2. validate numeric units/periods,
3. compare against prior structured records,
4. apply only rules contained in the versioned config,
5. produce the final score/classification.

The text model cannot output `materiality=8`, `surprise=4`, `guidance_deterioration=false`, or `balance_sheet_distressed=false` as an authoritative value.

## 9. Interaction with existing SOE-1.0.0 logic

- Re-Rating scanner thresholds remain unchanged.
- Growth Pullback continues to require revenue growth, at least one growth driver, no material guidance deterioration, no strong negative revisions, and balance sheet not distressed.
- Biotech/Catalyst scanner continues to require its existing runway/technical/catalyst rules.
- Catalyst timing and date-confidence mappings remain unchanged.
- Opportunity Score weights remain 25/20/20/15/10/5/5.
- Penalties remain unchanged.
- `missing != zero` remains mandatory.

## 10. Validation gates before activation

SOE-1.1.0 may not replace SOE-1.0.0 until all gates pass:

1. Unit tests prove every boundary in this specification, including null behavior.
2. Golden-case tests cover at least 25 catalysts across earnings, biotech/regulatory, transactions and legal/financing events.
3. Guidance ledger tests cover raises, reaffirms, small changes, material cuts, withdrawals, changed fiscal periods, and non-guiders.
4. Distress tests cover healthy, distressed and indeterminate cases in corporates, utilities, REITs, banks and negative-FCF growth companies.
5. A full-market shadow run compares SOE-1.1.0 against the frozen SOE-1.0.0 run with no v1.0 data overwritten.
6. At least 90% of catalyst candidates with sufficient primary evidence receive deterministic materiality; at least 80% receive a full surprise score.
7. At least 80% of Growth-Pullback candidates with comparable management guidance receive a non-null guidance classification.
8. At least 90% of non-financial Growth-Pullback candidates with sufficient balance-sheet inputs receive a non-null distress classification.
9. Manual audit of at least 100 randomly sampled classifications shows >=95% rule-concordance; any systematic error blocks activation.
10. No Investment Execution Engine v1.7.2 code is modified.

## 11. Version decision

These definitions are a real model change because they create previously unavailable scored/classified inputs. They must therefore activate only under `SOE-1.1.0`, never as a silent patch to `SOE-1.0.0`.
