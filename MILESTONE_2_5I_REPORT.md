# Milestone 2.5I — Free/Public Biotech Cash-Runway, Financing & Catalyst-Eligibility Validation

Date: 2026-08-31  
Model: `SOE-1.0.0`  
Scope: operationalize and validate the existing biotech runway, financing-exception and catalyst-eligibility inputs using free/public data without changing any investment rule, threshold, score weight, scanner condition or classification.

## Result

Milestone 2.5I is validated on the targeted free/public stack.

The engine can now derive a conservative biotech cash runway from SEC reported operating cash flow and current liquidity, recover a material marketable-security balance from the latest periodic filing when SEC `companyfacts` omits a custom-tagged balance, and determine whether post-balance-sheet financing is **deterministically completed/closed** rather than merely available or announced.

Catalyst eligibility remains independent. ClinicalTrials.gov primary/completion milestones do not become readout catalysts, and A/B date evidence with missing materiality/surprise still cannot create catalyst points or qualify the Grade-A exception path.

No change was made to `config/soe_v1_0_rules.yaml`. Branch and `main` use the identical rules blob SHA `3cd94be285e0f3b00b8952e33973762ec67b5f4d`. Investment Execution Engine v1.7.2 was not modified. Milestone 3 was not started.

## Frozen biotech rules preserved

The existing rules remain exactly:

- preferred cash runway: **≥18 months**
- standard minimum runway: **≥12 months**
- automatic rejection: **<9 months**, unless financing is secured
- Grade-A catalyst technical exception: **≤28 days**, subject to the existing technical conditions
- catalyst horizon: **≤56 days**

Milestone 2.5I adds evidence and normalization only. It does not alter these thresholds.

## Cash-runway methodology

### 1. Operating cash burn

SEC operating-cash-flow duration facts are normalized into discrete quarters before burn is calculated. YTD values are not incorrectly treated as individual quarters:

- Q2 = six-month YTD − Q1
- Q3 = nine-month YTD − six-month YTD
- Q4 = FY − Q1 − Q2 − Q3

At least two discrete reported quarters are required. Positive CFO quarters do not offset negative-quarter burn. The conservative monthly burn rate is:

`max(latest-quarter negative monthly burn, trailing negative-quarter monthly burn)`

This prevents an accelerating recent burn from being diluted by older periods.

### 2. Liquidity

The normal path uses reported cash plus one non-overlapping current marketable-security balance. Double-counting overlapping securities concepts is explicitly avoided.

A critical live validation exposed a real SEC/XBRL limitation: `companyfacts` can omit a current investment balance when an issuer uses a custom taxonomy extension. In the first 2.5I run, ARWR therefore appeared to have only about $69.4 million of liquidity and a false ~1.8-month runway.

The implementation was stopped rather than accepting that result. A deterministic fallback was added against the latest 10-Q/10-K primary SEC filing. The fallback:

- only accepts explicit cash/marketable-security balance phrases;
- only accepts amounts explicitly scaled as `million` or `billion`;
- ignores unscaled filing-table values because table units can vary;
- rejects collaboration milestones, milestone receivables, ATM/shelf capacity and other unrelated large amounts;
- aligns the resulting runway to the latest periodic report date.

After the correction, the live ARWR June 30, 2026 filing supplied approximately $1.5472 billion of available-for-sale securities. The deliberately conservative extraction used about $1.5513 billion of total runway liquidity and produced a **26.22-month runway**, moving ARWR from a false automatic reject to the frozen **PREFERRED_18M_PLUS** category.

## Financing methodology

The adapter uses SEC submissions plus relevant primary filing documents after the **same effective balance-sheet date used for the runway calculation**.

`financing_secured=True` requires deterministic evidence such as:

- financing/offering completed or closed; or
- proceeds explicitly received.

The following do **not** qualify as secured financing:

- shelf registration;
- ATM capacity;
- prospectus supplement alone;
- an offering pricing announcement alone;
- wording that an offering is expected to close;
- unused borrowing capacity.

If financing-related documents cannot be reviewed completely, the result remains `null`, not `false`. This prevents an unavailable-data condition from creating a false automatic rejection.

A separate regression check verifies that financing is re-evaluated from the effective runway date. This prevents a stale `companyfacts` cash date from treating financing already reflected in the latest balance sheet as a new post-period exception.

## Catalyst-eligibility validation

The 2.5H evidence architecture remains intact:

- only scoring-ready, verified Grade A/B catalyst evidence can satisfy the catalyst-eligibility condition;
- exact A/B public date evidence with missing materiality or surprise remains `score_inputs_incomplete`;
- ClinicalTrials.gov primary/completion milestones remain `TRIAL_MILESTONE_ONLY_NOT_A_READOUT`;
- no primary/completion milestone is converted into an FDA/PDUFA date;
- no missing materiality or surprise value is fabricated.

## Live targeted validation

GitHub Actions validation run `33426263100` / job `99600462083` completed successfully.

Deterministic suite: **117 passed, 0 failed**. One unrelated Starlette/httpx deprecation warning remains.

Live free/public sample results, all aligned to the June 30, 2026 effective runway date:

| Ticker | Derived runway | Frozen runway classification | Financing after period | Catalyst eligibility |
| --- | ---: | --- | --- | --- |
| ARWR | 26.22 months | `PREFERRED_18M_PLUS` | No completed financing evidence found | No scored catalyst |
| BEAM | 38.50 months | `PREFERRED_18M_PLUS` | No completed financing evidence found | No scored catalyst |
| MRNA | 29.30 months | `PREFERRED_18M_PLUS` | No completed financing evidence found | 7 trial milestones retained; none treated as readouts |
| EDIT | 21.19 months | `PREFERRED_18M_PLUS` | No completed financing evidence found | No scored catalyst |
| RXRX | 15.77 months | `ELIGIBLE_12_TO_18M` | No completed financing evidence found | No scored catalyst |

For ARWR, the current-period filing fallback recovered the large available-for-sale securities balance that the initial `companyfacts` path missed. This was the principal high-value validation finding of Milestone 2.5I.

For all five tickers, the financing review date matched the runway date. No ticker was marked `financing_secured=True` without a matched SEC filing. No public catalyst evidence silently created a scored catalyst.

## Deterministic tests added

Coverage now includes:

- YTD CFO decomposition into discrete quarters;
- conservative burn-rate calculation;
- cash + non-overlapping marketable securities;
- minimum reported-burn history;
- completed/closed financing vs announced/shelf financing;
- SEC submissions normalization;
- post-balance-sheet financing document evidence;
- frozen 9/12/18-month runway boundaries;
- catalyst-date evidence vs scanner eligibility;
- trial milestone not equal to readout;
- custom-tagged periodic-filing liquidity recovery;
- false-positive rejection for very large collaboration/milestone amounts;
- refusal to guess unscaled SEC table units;
- preservation of valid `companyfacts` marketable-security values;
- financing/runway effective-date alignment.

## Data-quality semantics

Milestone 2.5I deliberately prefers `DATA_INCOMPLETE` to false precision.

A cash-runway figure is not management guidance and is not a prediction that cash will last exactly that long. It is a deterministic screening input based on reported liquidity and historical operating cash consumption. Business-development receipts, changes in R&D cadence, capex, restructuring, milestone payments, debt transactions and future financings can materially change actual runway.

Likewise, `financing_secured=False` means the reviewed public SEC evidence did not show a completed/closed post-period financing; it does not mean the company cannot or will not raise capital.

## Remaining biotech limitations

The free/public stack still does not automatically provide a complete authoritative set of:

- clinical data-readout dates;
- FDA/PDUFA/action dates;
- catalyst materiality 0–10;
- catalyst surprise/re-rating potential 0–5;
- qualitative clinical-evidence-quality, pipeline-importance and external-validation scores for every company.

Those fields remain unavailable unless supported by a later deterministic adapter. Milestone 2.5I does not weaken the scanner to compensate.

## Conclusion

Milestone 2.5I passes its intended objective: free/public biotech runway and financing inputs are materially more usable and auditable, false low-runway rejection caused by missing custom-tagged SEC investment balances is mitigated, financing evidence is period-aligned, and catalyst eligibility remains conservative.

A fresh full-market validation run is still required before the overall Milestone 2.5 production-data phase is considered complete. Milestone 3 remains deferred.
