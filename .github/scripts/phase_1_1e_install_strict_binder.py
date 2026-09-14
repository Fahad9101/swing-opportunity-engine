from __future__ import annotations

from pathlib import Path

# Repair the two semantic edge cases exposed by the first guarded binder run
# before wiring the binder into the production canonical path.
BINDER_PATH = Path("backend/app/services/guidance_evidence_binder.py")
binder = BINDER_PATH.read_text()

old_projection = (
    '    r"project(?:s|ed|ing)|provid(?:e|es|ed|ing)|issu(?:e|es|ed|ing)|"\n'
)
new_projection = (
    '    r"project(?:s|ed|ing)\\s+(?:full[- ]year|fiscal|annual|quarterly?|revenue|revenues|sales|EPS|earnings|EBITDA|free\\s+cash\\s+flow|FCF|gross\\s+margin|operating\\s+margin)|"\n'
    '    r"provid(?:e|es|ed|ing)|issu(?:e|es|ed|ing)|"\n'
)
if old_projection not in binder:
    raise SystemExit("binder projection-signal anchor not found")
binder = binder.replace(old_projection, new_projection, 1)

old_period_guard = '''    if fact.period_kind is GuidancePeriodKind.FULL_YEAR and not explicit_periods:
        if re.search(r"\\b(?:first|second|third|fourth)\\s+(?:fiscal\\s+)?quarter\\b", binding_sentence, re.I):
            return False, "period: bare year was taken from a quarterly guidance sentence"
'''
new_period_guard = '''    if fact.period_kind is GuidancePeriodKind.FULL_YEAR and not explicit_periods:
        quarter_pattern = re.compile(r"\\b(?:first|second|third|fourth)\\s+(?:fiscal\\s+)?quarter\\b", re.I)
        for quarter_match in quarter_pattern.finditer(binding_sentence):
            before = binding_sentence[max(0, quarter_match.start() - 90):quarter_match.start()]
            after = binding_sentence[quarter_match.end():min(len(binding_sentence), quarter_match.end() + 110)]
            # A quarter may describe when management will provide the next update,
            # not the period of the guidance being reviewed (e.g. IOVA). That
            # timing reference must not displace the issuer's FY guidance state.
            if re.search(
                r"\\b(?:update|announcement)\\b.{0,32}\\b(?:during|in)\\s+(?:the\\s+)?$",
                before,
                re.I,
            ):
                continue
            local = f"{before[-70:]} {after[:90]}"
            if re.search(
                r"\\b(?:guidance|outlook|forecast|expects?|expected|revenue|revenues|net\\s+sales|EPS|earnings\\s+per\\s+share|EBITDA|free\\s+cash\\s+flow|FCF|gross\\s+margin|operating\\s+margin)\\b",
                local,
                re.I,
            ):
                return False, "period: bare year was taken from a quarterly guidance sentence"
'''
if old_period_guard not in binder:
    raise SystemExit("binder full-year quarter guard anchor not found")
binder = binder.replace(old_period_guard, new_period_guard, 1)
BINDER_PATH.write_text(binder)

PATH = Path("backend/app/services/canonical_shadow_guidance_service.py")
text = PATH.read_text()

old_import = "from app.services.guidance_canonical_ledger_service import CanonicalGuidanceLedger\nfrom app.services.guidance_canonical_service import CanonicalGuidanceNormalizer, GuidanceInvariantValidator\n"
new_import = "from app.services.guidance_canonical_ledger_service import CanonicalGuidanceLedger\nfrom app.services.guidance_canonical_service import CanonicalGuidanceNormalizer, GuidanceInvariantValidator\nfrom app.services.guidance_evidence_binder import GuidanceEvidenceBinder\n"
if old_import not in text:
    raise SystemExit("canonical service import anchor not found")
text = text.replace(old_import, new_import, 1)

old_state = "    validator = GuidanceInvariantValidator()\n    validated = []\n    policies: list[GuidancePolicyEvidence] = []\n"
new_state = "    validator = GuidanceInvariantValidator()\n    binder = GuidanceEvidenceBinder()\n    validated = []\n    binder_rejected_count = 0\n    binder_quarantine: list[dict[str, Any]] = []\n    policies: list[GuidancePolicyEvidence] = []\n"
if old_state not in text:
    raise SystemExit("canonical service state anchor not found")
text = text.replace(old_state, new_state, 1)

old_validation = "        if extraction.facts:\n            source_documents[document.source_url] = _source_manifest_row(document)\n        validated.extend(validator.validate(fact) for fact in extraction.facts)\n"
new_validation = "        if extraction.facts:\n            source_documents[document.source_url] = _source_manifest_row(document)\n        for fact in extraction.facts:\n            binding = binder.bind(fact, document)\n            if binding.accepted:\n                validated.append(validator.validate(fact))\n                continue\n            binder_rejected_count += 1\n            binder_quarantine.append(\n                {\n                    \"ticker\": fact.ticker,\n                    \"metric\": fact.metric.value,\n                    \"fiscal_period\": fact.fiscal_period,\n                    \"accounting_basis\": fact.accounting_basis,\n                    \"dimensions\": dict(binding.dimensions),\n                    \"reasons\": list(binding.reasons),\n                    \"source_url\": document.source_url,\n                    \"source_timestamp\": document.source_timestamp.isoformat(),\n                    \"evidence_span\": fact.provenance[0].evidence.full_text,\n                }\n            )\n            validated.append(binding.as_quarantined(fact))\n"
if old_validation not in text:
    raise SystemExit("canonical service validation anchor not found")
text = text.replace(old_validation, new_validation, 1)

old_meta = "        \"canonical_accepted_facts\": len(canonical.accepted),\n        \"canonical_quarantined_facts\": len(canonical.quarantined),\n        \"canonical_quarantine\": [_quarantine_summary(item) for item in canonical.quarantined],\n        \"rejected_candidates\": rejected_candidate_count,\n"
new_meta = "        \"canonical_accepted_facts\": len(canonical.accepted),\n        \"canonical_quarantined_facts\": len(canonical.quarantined),\n        \"canonical_quarantine\": [_quarantine_summary(item) for item in canonical.quarantined],\n        \"evidence_binder_version\": \"strict-v1\",\n        \"evidence_binder_rejected_facts\": binder_rejected_count,\n        \"evidence_binder_quarantine\": binder_quarantine,\n        \"rejected_candidates\": rejected_candidate_count,\n"
if old_meta not in text:
    raise SystemExit("canonical service metadata anchor not found")
text = text.replace(old_meta, new_meta, 1)

PATH.write_text(text)
