# SOE-1.1A — Evidence & Guidance Ledger Live Validation

Generated: 2026-09-01T16:54:37.002417+00:00
Rules hash: `bcd0bd71b53a242b4e9d143525d6cd3ea1e0550ae27cca1788540250bf9468ca`

## Exit gate

**INSUFFICIENT_SAMPLE**

- Tickers attempted: 24
- Tickers with extracted guidance facts: 21
- Tickers with comparable primary-source guidance: 7
- Non-null classifications among comparable names: 6
- Comparable-guidance coverage: 85.7%
- Non-null assessments with complete provenance: 100.0%
- SEC/provider errors: 0

Gate requires >=80% classification coverage among names with comparable primary-source guidance and 100% provenance on non-null classifications. A tiny denominator is reported as INSUFFICIENT_SAMPLE rather than treated as a pass.

## Ticker audit

| Ticker | Records | Comparable pairs | Classification | Deterioration | Rule path | Errors |
| --- | ---: | ---: | --- | --- | --- | ---: |
| ADBE | 22 | 4 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| CRM | 6 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| PANW | 2 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| CRWD | 6 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| DELL | 9 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| HPE | 14 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| MU | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| QCOM | 5 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| WMT | 8 | 1 | DETERIORATED | True | guidance_v1_1.material_numeric_cut | 0 |
| TGT | 22 | 3 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| LOW | 21 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| HD | 9 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| NKE | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| ULTA | 2 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| FDX | 1 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| UPS | 14 | 2 | UNKNOWN | None | guidance_v1_1.conflicting_primary_evidence | 0 |
| UNH | 3 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| HUM | 28 | 3 | DETERIORATED | True | guidance_v1_1.explicit_lower_or_withdrawal | 0 |
| ELV | 19 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| CVS | 15 | 3 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| MDT | 11 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| SYK | 3 | 1 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| LRCX | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| KLAC | 4 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |

## Null / error reasons

```json
{
  "All verified comparable current quantitative guidance metrics remain within frozen non-deterioration tolerances or are higher.": 4,
  "At least one current quantitative non-initiated guidance metric lacks a verified comparable prior record.": 1,
  "Comparable guidance reached the frozen material-cut threshold for: eps.": 1,
  "No comparable prior/current quantitative guidance metric pair is available.": 13,
  "No supported primary-source guidance fact was extracted in the validation window.": 3,
  "Primary-source action language conflicts with the comparable numeric guidance table for the same metric/period.": 1,
  "Verified explicit management action: LOWER.": 1
}
```
