# SOE-1.1A — Evidence & Guidance Ledger Live Validation

Generated: 2026-09-01T14:53:48.241749+00:00
Rules hash: `bcd0bd71b53a242b4e9d143525d6cd3ea1e0550ae27cca1788540250bf9468ca`

## Exit gate

**INSUFFICIENT_SAMPLE**

- Tickers attempted: 24
- Tickers with extracted guidance facts: 11
- Tickers with comparable primary-source guidance: 3
- Non-null classifications among comparable names: 0
- Comparable-guidance coverage: 0.0%
- Non-null assessments with complete provenance: 100.0%
- SEC/provider errors: 0

Gate requires >=80% classification coverage among names with comparable primary-source guidance and 100% provenance on non-null classifications. A tiny denominator is reported as INSUFFICIENT_SAMPLE rather than treated as a pass.

## Ticker audit

| Ticker | Records | Comparable pairs | Classification | Deterioration | Rule path | Errors |
| --- | ---: | ---: | --- | --- | --- | ---: |
| ADBE | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| CRM | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| PANW | 0 | 0 | NOT_DETERIORATED | False | guidance_v1_1.explicit_standing_no_guidance_policy | 0 |
| CRWD | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| DELL | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| HPE | 2 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| MU | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| QCOM | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| WMT | 8 | 3 | UNKNOWN | None | guidance_v1_1.conflicting_primary_evidence | 0 |
| TGT | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| LOW | 7 | 1 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| HD | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| NKE | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| ULTA | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| FDX | 2 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| UPS | 4 | 1 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| UNH | 1 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| HUM | 3 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| ELV | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| CVS | 2 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| MDT | 7 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| SYK | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| LRCX | 5 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| KLAC | 2 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |

## Null / error reasons

```json
{
  "At least one current non-initiated guidance metric lacks a verified comparable prior record or valid midpoint.": 10,
  "No supported primary-source guidance fact was extracted in the validation window.": 12,
  "Primary-source action language conflicts with the comparable numeric guidance table.": 1,
  "Verified standing company policy of not issuing quantitative guidance; no withdrawal is present.": 1
}
```
