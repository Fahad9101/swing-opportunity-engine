# Swing Opportunity Engine

SOE discovers U.S.-equity swing opportunities under frozen, versioned rules and hands candidates to the separate Investment Execution Engine for final analysis.

## Runtime governance

- Active frozen runtime model: `SOE-1.0.0`.
- Active frozen rules file: `config/soe_v1_0_rules.yaml`.
- Investment Execution Engine v1.7.2 remains separate and unchanged.
- SOE-1.1.0 is under shadow development and is not an active production model.
- Missing data remains null; no missing input is converted to zero or a favorable state.

## Milestone 2.5 free/public data foundation

The production-capable free/public data stack uses Nasdaq Trader for the tradable universe, SEC EDGAR for historical fundamentals, public market-data endpoints for EOD prices, and targeted public sources for estimates, ownership, catalysts and biotech evidence. Milestone 2.5J completed a real full-market validation across 5,156 securities and demonstrated genuine scanner qualifiers while also proving the structural fields that remained unresolved under SOE-1.0.0.

## SOE-1.1 structural-input program

SOE-1.1 is designed only to populate four unresolved deterministic fields while preserving all unaffected SOE-1.0.0 rules and weights:

1. catalyst materiality,
2. catalyst surprise/re-rating potential,
3. guidance deterioration,
4. balance-sheet distress.

The proposed SOE-1.1 rules remain isolated from the default runtime until all activation gates pass.

### Phase 1.1A — Evidence & Guidance Ledger

Phase 1.1A builds a primary-source SEC evidence ledger and deterministic tri-state `guidance_deterioration` classifier. The frozen deterioration thresholds remain:

- revenue midpoint cut >=2%,
- EPS / EBITDA / FCF midpoint cut >=5%,
- gross or operating margin cut >=100 bps,
- or the frozen multi-metric small-cut rule.

The evidence layer now supports targeted SEC filing/exhibit retrieval, immutable provenance, quarter/full-year normalization, current/prior same-key pairing, explicit guidance action handling, and true SEC historical-submissions backfill.

The historical backfill follows the official `filings.files` references contained in company submissions JSON, fetches only archive files whose SEC-reported date range overlaps the configured validation lookback, merges them with `filings.recent`, de-duplicates accessions, and preserves SEC fair-access throttling and local caching. Increasing validation depth does not change any SOE scoring or classification threshold.

Phase 1.1A remains in shadow validation until the live gate reaches at least 10 genuinely comparable primary-source guidance names, at least 80% non-null classification coverage among those comparable names, and 100% provenance on non-null classifications.
