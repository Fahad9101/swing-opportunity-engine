# Phase 1.1E Manual Audit — Round 7 Early-Stop

## Governance result

**FAIL — systematic fiscal-period guidance-binding defect.**

The fresh independent audit for full-market run `33961113688` was stopped as soon as a systematic defect was confirmed, per `SOE-1.1E-SHADOW-V1`. A numerical 100-name concordance percentage is intentionally not reported because the contract separately blocks activation when a systematic audit error is identified.

## Automated run

- Head SHA: `b71198c171d94a8e01c2b6a5321f18f2f13ce857`
- Universe: 5,151
- Universal survivors: 2,315
- Fully scored candidate: 73
- Guidance coverage: 96.43%
- Nonfinancial distress coverage: 100%
- Catalyst materiality coverage: 100%
- Catalyst surprise coverage: 100%
- Automated decision: `PENDING_MANUAL_AUDIT`
- All machine integrity gates: PASS
- Deterministic regression suite before the run: 486 passed, 0 failed

## Blocking manual finding

### INSM — guidance

Engine classification:
- `NOT_DETERIORATED`
- rule path: `guidance_v1_1.comparable_set_within_tolerance`
- engine reports `comparable_pairs = 1`

Independent primary-source adjudication:
- Insmed's October 30, 2025 release explicitly states **full-year 2025 global ARIKAYCE revenue guidance of $420M–$430M**.
- Insmed's February 19, 2026 release explicitly states **full-year 2026 ARIKAYCE revenue guidance of $450M–$470M**.
- The October 2025 release contains no FY2026 ARIKAYCE revenue guidance.
- FY2025 and FY2026 guidance are different fiscal periods and are therefore not a valid comparable pair under the frozen guidance contract.

Conclusion:
- The final label happened to be non-deteriorated, but the evidence ledger is structurally wrong because a cross-fiscal-year pair was admitted as comparable.
- This is a generic fiscal-period binding/comparability defect, not a ticker-specific judgment.
- Correct handling is to keep FY2025 and FY2026 ARIKAYCE guidance in separate comparison keys; absent another same-period prior/current pair, the comparable-guidance result must be unknown rather than inferred from cross-year values.

Primary SEC evidence:
- https://www.sec.gov/Archives/edgar/data/1104506/000114036125039789/ef20057768_ex99-1.htm
- https://www.sec.gov/Archives/edgar/data/1104506/000114036126006116/ef20066055_ex99-1.htm

## Governance consequence

- SOE-1.0.0 remains the active model.
- SOE-1.1.0 is not promoted.
- PR #16 remains unmerged/draft.
- Milestone 3 remains blocked.
- Repair is restricted to evidence extraction/binding. No scanner threshold, score, weight, technical rule, catalyst rule, distress threshold, guidance threshold, classification rule, or IEE v1.7.2 logic may change.
