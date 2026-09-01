# SOE-1.1A — Evidence & Guidance Ledger Live Validation

Generated: 2026-09-01T15:56:00.813601+00:00
Rules hash: `bcd0bd71b53a242b4e9d143525d6cd3ea1e0550ae27cca1788540250bf9468ca`

## Exit gate

**FAIL**

- Tickers attempted: 24
- Tickers with extracted guidance facts: 22
- Tickers with comparable primary-source guidance: 12
- Non-null classifications among comparable names: 4
- Comparable-guidance coverage: 33.3%
- Non-null assessments with complete provenance: 100.0%
- SEC/provider errors: 0

Gate requires >=80% classification coverage among names with comparable primary-source guidance and 100% provenance on non-null classifications. A tiny denominator is reported as INSUFFICIENT_SAMPLE rather than treated as a pass.

## Ticker audit

| Ticker | Records | Comparable pairs | Classification | Deterioration | Rule path | Errors |
| --- | ---: | ---: | --- | --- | --- | ---: |
| ADBE | 36 | 10 | UNKNOWN | None | guidance_v1_1.conflicting_primary_evidence | 0 |
| CRM | 5 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| PANW | 5 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| CRWD | 16 | 3 | UNKNOWN | None | guidance_v1_1.conflicting_primary_evidence | 0 |
| DELL | 9 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| HPE | 16 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| MU | 1 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| QCOM | 5 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| WMT | 9 | 1 | UNKNOWN | None | guidance_v1_1.conflicting_primary_evidence | 0 |
| TGT | 28 | 6 | DETERIORATED | True | guidance_v1_1.explicit_lower_or_withdrawal | 0 |
| LOW | 28 | 7 | DETERIORATED | True | guidance_v1_1.material_numeric_cut | 0 |
| HD | 23 | 3 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| NKE | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| ULTA | 4 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| FDX | 1 | 0 | UNKNOWN | None | guidance_v1_1.no_comparable_prior | 0 |
| UPS | 22 | 5 | UNKNOWN | None | guidance_v1_1.conflicting_primary_evidence | 0 |
| UNH | 3 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| HUM | 32 | 9 | DETERIORATED | True | guidance_v1_1.explicit_lower_or_withdrawal | 0 |
| ELV | 20 | 3 | DETERIORATED | True | guidance_v1_1.explicit_lower_or_withdrawal | 0 |
| CVS | 13 | 3 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| MDT | 17 | 2 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| SYK | 3 | 1 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |
| LRCX | 0 | 0 | UNKNOWN | None | guidance_v1_1.no_extracted_primary_guidance | 0 |
| KLAC | 4 | 0 | UNKNOWN | None | guidance_v1_1.incomplete_comparable_set | 0 |

## Null / error reasons

```json
{
  "At least one current non-initiated guidance metric lacks a verified comparable prior record or valid midpoint.": 11,
  "Comparable guidance reached the frozen material-cut threshold for: revenue.": 1,
  "No comparable prior/current guidance metric pair is available.": 3,
  "No supported primary-source guidance fact was extracted in the validation window.": 2,
  "Primary-source action language conflicts with the comparable numeric guidance table.": 4,
  "Verified explicit management action: LOWER.": 3
}
```
