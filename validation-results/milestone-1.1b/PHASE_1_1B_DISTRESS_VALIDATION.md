# Phase 1.1B Balance-Sheet Distress Validation

- Basket: `SOE-1.1B-DISTRESS-V1-56`
- Model: `SOE-1.1.0`
- Rules hash: `bcd0bd71b53a242b4e9d143525d6cd3ea1e0550ae27cca1788540250bf9468ca`
- Tickers attempted: **56**
- Non-financial names with sufficient inputs: **30**
- Non-financial classified: **14**
- Classification coverage: **46.67%**
- Financial corporate fallback count: **0**
- False-safe missing-data count: **0**
- Non-null provenance complete: **100.00%**
- Provider/execution errors: **0**
- Exit gate: **FAIL**

## Classification counts

- DISTRESSED: 4
- NOT_DISTRESSED: 10
- UNKNOWN: 42

## Per-name audit

- **AAPL** (corporate): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **MSFT** (corporate): NOT_DISTRESSED | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.net_cash_safe`
- **GOOGL** (corporate): NOT_DISTRESSED | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.net_cash_safe`
- **META** (corporate): NOT_DISTRESSED | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.net_cash_safe`
- **NVDA** (corporate): DISTRESSED | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.universal_hard_override`
- **AVGO** (corporate): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **AMD** (corporate): NOT_DISTRESSED | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.net_cash_safe`
- **ORCL** (corporate): NOT_DISTRESSED | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.net_cash_safe`
- **CRM** (corporate): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **ADBE** (corporate): NOT_DISTRESSED | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.net_cash_safe`
- **PANW** (corporate): NOT_DISTRESSED | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.net_cash_safe`
- **DELL** (corporate): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **CAT** (corporate): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **DE** (corporate): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **HON** (corporate): DISTRESSED | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.universal_hard_override`
- **ETN** (corporate): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **CARR** (corporate): DISTRESSED | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.universal_hard_override`
- **URI** (corporate): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **WMT** (corporate): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **TGT** (corporate): NOT_DISTRESSED | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.leverage_coverage_safe`
- **LOW** (corporate): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **HD** (corporate): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **COST** (corporate): NOT_DISTRESSED | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.net_cash_safe`
- **SBUX** (corporate): NOT_DISTRESSED | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.leverage_coverage_safe`
- **UPS** (corporate): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **FDX** (corporate): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **ABT** (corporate): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **DHR** (corporate): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **TMO** (corporate): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **ISRG** (corporate): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **BSX** (corporate): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **SYK** (corporate): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.corporate.unknown`
- **NEE** (utilities): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.utilities.unknown`
- **DUK** (utilities): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.utilities.unknown`
- **SO** (utilities): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.utilities.unknown`
- **AEP** (utilities): UNKNOWN | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.utilities.unknown`
- **EXC** (utilities): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.utilities.unknown`
- **XEL** (utilities): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.utilities.unknown`
- **PLD** (reits): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.reits.unknown`
- **AMT** (reits): DISTRESSED | sufficient=True | screen=True | path=`balance_sheet_distress_v1_1.universal_hard_override`
- **EQIX** (reits): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.reits.unknown`
- **O** (reits): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.reits.unknown`
- **SPG** (reits): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.reits.unknown`
- **VICI** (reits): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.reits.unknown`
- **JPM** (banks): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.banks.unknown`
- **BAC** (banks): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.banks.unknown`
- **WFC** (banks): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.banks.unknown`
- **C** (banks): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.banks.unknown`
- **USB** (banks): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.banks.unknown`
- **PNC** (banks): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.banks.unknown`
- **CB** (insurers): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.insurers.unknown`
- **ALL** (insurers): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.insurers.unknown`
- **TRV** (insurers): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.insurers.unknown`
- **PGR** (insurers): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.insurers.unknown`
- **MET** (insurers): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.insurers.unknown`
- **PRU** (insurers): UNKNOWN | sufficient=False | screen=True | path=`balance_sheet_distress_v1_1.insurers.unknown`
