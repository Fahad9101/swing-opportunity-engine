# SOE-1.1A — Evidence & Guidance Ledger Live Validation

Generated: 2026-09-01T18:05:14.600774+00:00
Rules hash: `bcd0bd71b53a242b4e9d143525d6cd3ea1e0550ae27cca1788540250bf9468ca`

## Exit gate

**INSUFFICIENT_SAMPLE**

- Tickers attempted: 24
- Tickers with extracted guidance facts: 22
- Tickers with comparable primary-source guidance: 8
- Non-null classifications among comparable names: 6
- Comparable-guidance coverage: 75.0%
- Non-null assessments with complete provenance: 100.0%
- SEC/provider errors: 0
- Archived SEC submissions files fetched: 0

Gate requires >=80% classification coverage among names with comparable primary-source guidance and 100% provenance on non-null classifications. A tiny denominator is reported as INSUFFICIENT_SAMPLE rather than treated as a pass.

## Ticker audit

| Ticker | Records | Comparable pairs | Archive files | Classification | Deterioration | Rule path | Errors |
| --- | ---: | ---: | ---: | --- | --- | --- | ---: |
| ADBE | 30 | 4 | 0 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| CRM | 14 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| PANW | 6 | 1 | 0 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| CRWD | 9 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| DELL | 12 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| HPE | 45 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| MU | 5 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| QCOM | 7 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| WMT | 21 | 1 | 0 | DETERIORATED | True | guidance_v1_1.material_numeric_cut | 0 |
| TGT | 42 | 3 | 0 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| LOW | 36 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| HD | 14 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| NKE | 0 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| ULTA | 4 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| FDX | 2 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| UPS | 17 | 2 | 0 | UNKNOWN | None | guidance_v1_1.conflicting_primary_evidence | 0 |
| UNH | 4 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| HUM | 82 | 3 | 0 | DETERIORATED | True | guidance_v1_1.explicit_lower_or_withdrawal | 0 |
| ELV | 30 | 0 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| CVS | 29 | 3 | 0 | UNKNOWN | None | guidance_v1_1.conflicting_primary_evidence | 0 |
| MDT | 11 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| SYK | 10 | 1 | 0 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| LRCX | 0 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| KLAC | 7 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |

## Null / error reasons

```json
{
  "All verified comparable current quantitative guidance metrics remain within frozen non-deterioration tolerances or are higher.": 4,
  "At least one current quantitative non-initiated guidance metric lacks a verified comparable prior record.": 1,
  "Comparable guidance reached the frozen material-cut threshold for: eps.": 1,
  "No comparable prior/current quantitative guidance metric pair is available.": 13,
  "No supported primary-source guidance fact was extracted in the validation window.": 2,
  "Primary-source action language conflicts with the comparable numeric guidance table for the same metric/period.": 2,
  "Verified explicit management action: LOWER.": 1
}
```
