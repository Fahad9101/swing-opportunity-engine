# SOE-1.1A — Evidence & Guidance Ledger Live Validation

Generated: 2026-09-02T10:58:42.644460+00:00
Rules hash: `bcd0bd71b53a242b4e9d143525d6cd3ea1e0550ae27cca1788540250bf9468ca`

## Exit gate

**PASS**

- Tickers attempted: 48
- Tickers with extracted guidance facts: 44
- Tickers with comparable primary-source guidance: 13
- Non-null classifications among comparable names: 12
- Comparable-guidance coverage: 92.3%
- Non-null assessments with complete provenance: 100.0%
- SEC/provider errors: 0
- Archived SEC submissions files fetched: 0

Gate requires >=80% classification coverage among names with comparable primary-source guidance and 100% provenance on non-null classifications. A tiny denominator is reported as INSUFFICIENT_SAMPLE rather than treated as a pass.

## Ticker audit

| Ticker | Records | Comparable pairs | Archive files | Classification | Deterioration | Rule path | Errors |
| --- | ---: | ---: | ---: | --- | --- | --- | ---: |
| ADBE | 30 | 4 | 0 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| CRM | 14 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| PANW | 5 | 1 | 0 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| CRWD | 6 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| DELL | 4 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_assessment_eligible_primary_guidance | 0 |
| HPE | 40 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| MU | 5 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| QCOM | 1 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_assessment_eligible_primary_guidance | 0 |
| WMT | 17 | 1 | 0 | DETERIORATED | True | guidance_v1_1.material_numeric_cut | 0 |
| TGT | 28 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| LOW | 23 | 2 | 0 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| HD | 2 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| NKE | 0 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| ULTA | 3 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| FDX | 2 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| UPS | 19 | 1 | 0 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| UNH | 3 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| HUM | 73 | 1 | 0 | DETERIORATED | True | guidance_v1_1.explicit_lower_or_withdrawal | 0 |
| ELV | 24 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| CVS | 24 | 2 | 0 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| MDT | 14 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| SYK | 9 | 1 | 0 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| LRCX | 0 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| KLAC | 8 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| ORCL | 7 | 1 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| INTU | 40 | 2 | 0 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| NOW | 7 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| SNPS | 21 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| AMD | 13 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| NVDA | 8 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| AVGO | 33 | 0 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| AMAT | 3 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| COST | 1 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| BBY | 16 | 0 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| SBUX | 8 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| ROST | 3 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| TJX | 25 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| CAT | 12 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| DE | 0 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| HON | 18 | 1 | 0 | DETERIORATED | True | guidance_v1_1.material_numeric_cut | 0 |
| ETN | 11 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| CARR | 15 | 0 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| URI | 12 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| ABT | 23 | 2 | 0 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| TMO | 0 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| DHR | 14 | 1 | 0 | NOT_DETERIORATED | False | guidance_v1_1.comparable_set_within_tolerance | 0 |
| ISRG | 5 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| BSX | 23 | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |

## Null / error reasons

```json
{
  "All verified comparable current quantitative guidance metrics remain within frozen non-deterioration tolerances or are higher.": 9,
  "At least one current quantitative non-initiated guidance metric lacks a verified comparable prior record.": 4,
  "Comparable guidance reached the frozen material-cut threshold for: eps.": 1,
  "Comparable guidance reached the frozen material-cut threshold for: revenue.": 1,
  "Extracted primary-source records exist, but none are eligible for deterministic guidance assessment.": 2,
  "No comparable prior/current quantitative guidance metric pair is available.": 26,
  "No supported primary-source guidance fact was extracted in the validation window.": 4,
  "Verified explicit management action: LOWER.": 1
}
```
