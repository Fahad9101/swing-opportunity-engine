from __future__ import annotations

from pathlib import Path

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
