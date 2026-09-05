# Phase 1.1E Manual Audit — Round 8 Early-Stop

## Governance result

**FAIL — systematic fiscal-period binding defect.**

The fresh independent audit for full-market run `33967487517` was stopped as soon as a systematic defect was confirmed, per `SOE-1.1E-SHADOW-V1`. A numerical 100-name concordance percentage is intentionally not reported because the contract separately blocks activation when a systematic audit error is identified.

## Automated run

- Head SHA: `79ad995889c6a1573a0010f9229af3ad2b7947ee`
- Universe: 5,151
- Universal survivors: 2,315
- Growth structural targets: 434
- Guidance coverage: 96.51%
- Nonfinancial distress coverage: 100%
- Catalyst materiality coverage: 100%
- Catalyst surprise coverage: 100%
- Automated decision: `PENDING_MANUAL_AUDIT`
- All machine integrity gates: PASS

## Blocking manual finding

### IOT — guidance

Engine classification:
- `DETERIORATED`
- rule path: `guidance_v1_1.material_numeric_cut`
- engine reason: material cut in **revenue**
- comparable pairs: 1

Independent primary-source adjudication:

**Q1 FY2027 release (June 4, 2026)**
- Q2 FY2027 revenue outlook: `$482M–$484M`
- FY2027 revenue outlook: `$2.005B–$2.013B`
- FY2027 non-GAAP operating margin: `20%`
- FY2027 non-GAAP EPS: `$0.70–$0.72`

**Q2 FY2027 release (September 3, 2026)**
- Q3 FY2027 revenue outlook: `$514M–$516M`
- FY2027 revenue outlook: `$2.043B–$2.047B`
- FY2027 non-GAAP operating margin: `21%`
- FY2027 non-GAAP EPS: `$0.76–$0.78`

All valid same-period full-year metrics increased. There is no verified material revenue-guidance cut.

Primary sources:
- https://www.sec.gov/Archives/edgar/data/1642896/000162828026040788/samsaraepr-q12027.htm
- https://www.sec.gov/Archives/edgar/data/1642896/000162828026060438/samsaraepr-q22027.htm

## Root cause

Round-7 annual period hardening can interpret an annual token inside a quarter header such as `Q2 FY2027 Outlook` as annual `FY2027` for the nearby revenue metric. This can collapse a quarter-specific guidance record and a full-year guidance record onto the same comparison key. Dedupe can then retain different scopes at different timestamps and manufacture an apparent cut.

This is a generic period/scope binding defect, not an IOT-specific economic judgment.

## Required repair

Evidence binding must preserve the most specific verified fiscal scope:
1. Detect metric-bound quarter headers such as `Q2 FY2027 Outlook` / `Third Quarter FY2027 Guidance`.
2. Preserve or restore `QxFYyyyy` before applying annual fallback binding.
3. Only apply annual `FYyyyy` binding when no metric-bound quarter scope exists.
4. Add regression coverage proving quarterly and full-year ranges from the same release remain distinct comparison keys and only same-period full-year records form the valid prior/current pair.

No scanner threshold, score, weight, technical rule, catalyst rule, distress threshold, guidance threshold, classification rule, SOE-1.0.0 rule, or IEE v1.7.2 logic may change.

## Governance consequence

- SOE-1.0.0 remains the active model.
- SOE-1.1.0 is not promoted.
- PR #16 remains unmerged/draft.
- Milestone 3 remains blocked.
