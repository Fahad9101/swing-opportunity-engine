# Phase 1.1E Manual Audit — Round 6 Early-Stop

## Governance result

**FAIL — systematic evidence-binding defect.**

The fresh independent audit for full-market run `33947399771` was stopped as soon as a systematic defect was confirmed, per `SOE-1.1E-SHADOW-V1`. A numerical 100-name concordance percentage is intentionally not reported because the contract separately blocks activation when a systematic audit error is identified.

## Automated run

- Head SHA: `c6e45edd00e5badffe398a3d0cec18437a9d2c76`
- Universe: 5,151
- Universal survivors: 2,315
- Guidance coverage: 94.96%
- Nonfinancial distress coverage: 100%
- Catalyst materiality coverage: 100%
- Catalyst surprise coverage: 100%
- Automated decision: `PENDING_MANUAL_AUDIT`
- All machine integrity gates: PASS

## Blocking manual finding

### VG — guidance

Engine classification:
- `DETERIORATED`
- rule path: `guidance_v1_1.material_numeric_cut`
- engine reason: material cut in **revenue**

Independent primary-source adjudication:
- Q1 2026 release reports historical quarterly revenue of approximately $4.6B and separately states full-year 2026 **Consolidated Adjusted EBITDA guidance of $8.2B–$8.5B**.
- Q2 2026 release reports historical quarterly revenue of approximately $4.6B and explicitly states **Consolidated Adjusted EBITDA guidance increased to $8.7B–$9.1B from $8.2B–$8.5B**.
- The releases do **not** establish a comparable full-year revenue-guidance cut.

Conclusion:
- Historical reported revenue leaked into the guidance ledger because forward EBITDA-guidance language was present elsewhere in the evidence window/document.
- This is a generic metric/context binding defect, not a ticker-specific economic judgment.
- Correct guidance deterioration for the verified comparable guidance set is **false**, or unknown if no valid comparable primary metric survives; it cannot be true on a fabricated revenue-guidance pair.

## Governance consequence

- SOE-1.0.0 remains the active model.
- SOE-1.1.0 is not promoted.
- PR #16 remains unmerged/draft.
- Milestone 3 remains blocked.
- Repair is restricted to evidence extraction/binding. No scanner threshold, score, weight, technical rule, catalyst rule, distress threshold, guidance threshold, classification rule, or IEE v1.7.2 logic may change.
