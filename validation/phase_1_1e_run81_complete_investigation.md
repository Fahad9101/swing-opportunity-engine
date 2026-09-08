# Phase 1.1E: complete run 81 investigation and combined extraction repair

Run 34168937582, artifact 10037117050, code 35f8877c448c357661f13bb4362bc1a29cbc4897 remains **FAIL**. The investigation continued through all 100 queue entries after the initial ROCK finding. The accompanying JSON records each entry, its sources and hashes, the checks performed, and their limits. All 164 distinct cited source files were retrieved.

## Findings and repairs

| Root cause | Affected guidance samples | Repair |
| --- | --- | --- |
| Annual scope, accounting basis, or accompanying metric lost | ROCK, LB, CDNA, FIG | Bind explicitly forward clauses to their section; preserve EPS bases, EBITDA, and stated operating margin; remove conflicting generic records. |
| Multiple fiscal-year columns flattened together | KRMN | Require the complete reported/prior/updated/next-year header and emit current values under the correct years. |
| Point guidance borrows a historical year | INFQ | Bind the point to its explicit guidance year; reject range truncation. |
| Quarter and annual columns lose scope and units | BRZE | Preserve both columns, million-dollar units, and adjusted EPS. |
| Adjacent quarter guidance becomes annual guidance | FN, ZBRA | Retain quarter and annual scopes separately. A quarter end date alone cannot establish a fiscal year. |
| Product revenue substitutes for total revenue; inline styling splits digits | PTCT | Extract the explicit total-revenue clause and preserve inline text while separating block/table cells. |

ROCK's revenue and EPS reductions satisfy the existing multi-metric small-cut rule. FN's cited documents guide different quarters and cannot establish an annual comparable pair. These corrections change extracted evidence, not the classifier or its investment interpretation.

## Audit scope

- 14 guidance comparisons: 10 extraction defects; four checked comparisons without a confirmed discrepancy (CXT, NMAX, BG, EE).
- 38 distress samples: independently applied arithmetic to persisted inputs; fresh SEC companyfacts replay reproduced debt, net cash, leverage, and interest coverage without differences. The replay uses the existing normalizer and is not an independent XBRL implementation. Primary-document keyword review found no additional confirmed hard-distress condition; VSH's covenant text is explicitly conditional. This does not independently certify every sector route, captured FCF/runway input, or filing-selection decision.
- 48 catalyst entries: arithmetic agrees with frozen earnings components. All 42 distinct cited earnings releases, results presentations, or periodic filings support completed financial results. Future Nasdaq calendar dates and captured consensus inputs were not independently revalidated by this source check.

The JSON deliberately does not manufacture a manual acceptance concordance percentage from these differing checks. No activation sign-off is granted. A fresh run and acceptance audit remain required.

## Engineering and verification

The change adds one normalization helper and connects it to the existing Phase 1.1E extraction wrapper. Provider acquisition, persistence schema, screening, scoring, ranking, API, UI, default model selection, both frozen rule files, and IEE are unchanged.

- Full deterministic suite: **548 passed, 0 failed**, two existing dependency deprecation warnings.
- Sixteen new regression cases cover the confirmed source-binding defects, reported/ambiguous rows, reversed ranges, fiscal/calendar distinctions, and HTML boundaries.
- Replayed all 28 guidance source documents through the guarded extraction path. Replay timestamps are diagnostic placeholders; only values, units, basis and scope are assessed by that replay, not source chronology or point-in-time classification.
- Both frozen rules retain their recorded hashes in the JSON.

Data providers remain free/public. Run 81 had 12 baseline provider errors and 12 enrichment errors; passing automated coverage does not erase these errors. No paid provider was added.

Remaining debt: extraction still contains several narrowly bounded normalization stages; independent verification of captured consensus, future event dates, sector routing and all distress inputs remains part of acceptance work. The exact next step is fresh **Phase 1.1E full-market validation and independent acceptance audit**. Do not start Milestone 3 or activate SOE-1.1 on the basis of this repair.
