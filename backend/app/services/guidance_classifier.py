from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.domain.soe_v1_1 import (
    GuidanceAction,
    GuidanceAssessment,
    GuidanceClassification,
    GuidanceMetric,
    GuidanceMetricDelta,
    GuidanceMetricRecord,
    GuidancePolicyEvidence,
)


_MARGIN_METRICS = {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}


def _guidance_rules(rules: dict[str, Any]) -> dict[str, Any]:
    config = rules.get("guidance_v1_1")
    if not isinstance(config, dict):
        raise ValueError("SOE-1.1 guidance rules are missing")
    return config


def _latest_by_key(records: list[GuidanceMetricRecord]) -> dict[tuple[str, str, str], GuidanceMetricRecord]:
    latest: dict[tuple[str, str, str], GuidanceMetricRecord] = {}
    for record in records:
        if not record.verified:
            continue
        key = record.comparison_key
        existing = latest.get(key)
        if existing is None or (record.source_timestamp, str(record.record_id)) > (
            existing.source_timestamp,
            str(existing.record_id),
        ):
            latest[key] = record
    return latest


def _unique_sources(records: list[GuidanceMetricRecord], policy: GuidancePolicyEvidence | None) -> list[str]:
    sources = {record.source_url for record in records if record.verified and record.source_url}
    if policy and policy.verified and policy.source_url:
        sources.add(policy.source_url)
    return sorted(sources)


def _unknown(
    ticker: str,
    rules_hash: str,
    current: list[GuidanceMetricRecord],
    prior: list[GuidanceMetricRecord],
    *,
    as_of: datetime,
    reasons: list[str],
    metric_deltas: list[GuidanceMetricDelta] | None = None,
    policy: GuidancePolicyEvidence | None = None,
    rule_path: str = "guidance_v1_1.unknown",
) -> GuidanceAssessment:
    deltas = metric_deltas or []
    return GuidanceAssessment(
        rules_hash=rules_hash,
        ticker=ticker,
        as_of=as_of,
        current_guidance_record_ids=[item.record_id for item in current if item.verified],
        prior_guidance_record_ids=[item.record_id for item in prior if item.verified],
        comparable_metrics=[item.metric for item in deltas if item.comparable],
        metric_deltas=deltas,
        explicit_cut_or_withdrawal=False,
        classification=GuidanceClassification.UNKNOWN,
        guidance_deterioration=None,
        rule_path=rule_path,
        reasons=reasons,
        sources=_unique_sources(current + prior, policy),
    )


def classify_guidance(
    current: list[GuidanceMetricRecord],
    prior: list[GuidanceMetricRecord],
    rules: dict[str, Any],
    *,
    rules_hash: str,
    policy: GuidancePolicyEvidence | None = None,
    as_of: datetime | None = None,
) -> GuidanceAssessment:
    """Pure deterministic SOE-1.1 guidance classifier.

    Network access, document parsing, and LLM calls are intentionally prohibited
    from this function. Missing or incompatible evidence resolves to UNKNOWN.
    """
    config = _guidance_rules(rules)
    current_verified = [item for item in current if item.verified]
    prior_verified = [item for item in prior if item.verified]
    all_records = current_verified + prior_verified
    ticker = all_records[0].ticker if all_records else (policy.ticker if policy else "")
    if not ticker:
        raise ValueError("Ticker is required for guidance classification")
    if any(item.ticker != ticker for item in all_records):
        raise ValueError("Guidance records from different tickers cannot be compared")
    timestamps = [item.source_timestamp for item in all_records]
    if policy and policy.verified:
        timestamps.append(policy.source_timestamp)
    as_of = as_of or (max(timestamps) if timestamps else datetime.now(UTC))

    explicit_negative = [
        item
        for item in current_verified
        if item.explicit_action in {GuidanceAction.WITHDRAW, GuidanceAction.LOWER}
    ]
    if explicit_negative:
        actions = ", ".join(sorted({item.explicit_action.value for item in explicit_negative}))
        return GuidanceAssessment(
            rules_hash=rules_hash,
            ticker=ticker,
            as_of=as_of,
            current_guidance_record_ids=[item.record_id for item in current_verified],
            prior_guidance_record_ids=[item.record_id for item in prior_verified],
            explicit_cut_or_withdrawal=True,
            classification=GuidanceClassification.DETERIORATED,
            guidance_deterioration=True,
            rule_path="guidance_v1_1.explicit_lower_or_withdrawal",
            reasons=[f"Verified explicit management action: {actions}."],
            sources=_unique_sources(all_records, policy),
        )

    if policy and policy.verified and policy.standing_no_guidance_policy and not current_verified:
        return GuidanceAssessment(
            rules_hash=rules_hash,
            ticker=ticker,
            as_of=as_of,
            classification=GuidanceClassification.NOT_DETERIORATED,
            guidance_deterioration=False,
            rule_path="guidance_v1_1.explicit_standing_no_guidance_policy",
            reasons=[
                "Verified standing company policy of not issuing quantitative guidance; no withdrawal is present."
            ],
            sources=_unique_sources([], policy),
        )

    current_map = _latest_by_key(current_verified)
    prior_map = _latest_by_key(prior_verified)
    current_records = list(current_map.values())
    prior_records = list(prior_map.values())

    material = config["material_cut_thresholds"]
    small = config["multi_metric_small_cut"]
    thresholds_pct = {
        GuidanceMetric.REVENUE: float(material["revenue_pct"]),
        GuidanceMetric.EPS: float(material["eps_pct"]),
        GuidanceMetric.EBITDA: float(material["ebitda_pct"]),
        GuidanceMetric.FCF: float(material["fcf_pct"]),
    }
    small_pct = float(small["revenue_eps_ebitda_fcf_min_pct"])
    margin_material_bps = float(material["margin_bps"])
    margin_small_bps = float(small["margin_min_bps"])

    deltas: list[GuidanceMetricDelta] = []
    unmatched_required: list[GuidanceMetricRecord] = []
    material_cuts: list[GuidanceMetricDelta] = []
    small_cuts: list[GuidanceMetricDelta] = []

    for key, current_record in current_map.items():
        prior_record = prior_map.get(key)
        if prior_record is None:
            if current_record.explicit_action != GuidanceAction.INITIATE:
                unmatched_required.append(current_record)
            continue

        if current_record.metric in _MARGIN_METRICS:
            if current_record.midpoint is None or prior_record.midpoint is None:
                deltas.append(
                    GuidanceMetricDelta(
                        metric=current_record.metric,
                        fiscal_period=current_record.fiscal_period,
                        accounting_basis=current_record.accounting_basis,
                        current_record_id=current_record.record_id,
                        prior_record_id=prior_record.record_id,
                        current_midpoint=current_record.midpoint,
                        prior_midpoint=prior_record.midpoint,
                        material_threshold=margin_material_bps,
                        small_cut_threshold=margin_small_bps,
                        comparable=False,
                        reason="Missing current or prior margin midpoint.",
                    )
                )
                unmatched_required.append(current_record)
                continue
            delta_bps = (current_record.midpoint - prior_record.midpoint) * 10_000
            result = GuidanceMetricDelta(
                metric=current_record.metric,
                fiscal_period=current_record.fiscal_period,
                accounting_basis=current_record.accounting_basis,
                current_record_id=current_record.record_id,
                prior_record_id=prior_record.record_id,
                current_midpoint=current_record.midpoint,
                prior_midpoint=prior_record.midpoint,
                delta_bps=delta_bps,
                material_threshold=margin_material_bps,
                small_cut_threshold=margin_small_bps,
                material_cut=delta_bps <= -margin_material_bps,
                small_cut=delta_bps <= -margin_small_bps,
            )
        else:
            threshold = thresholds_pct[current_record.metric]
            if current_record.midpoint is None or prior_record.midpoint is None:
                deltas.append(
                    GuidanceMetricDelta(
                        metric=current_record.metric,
                        fiscal_period=current_record.fiscal_period,
                        accounting_basis=current_record.accounting_basis,
                        current_record_id=current_record.record_id,
                        prior_record_id=prior_record.record_id,
                        current_midpoint=current_record.midpoint,
                        prior_midpoint=prior_record.midpoint,
                        material_threshold=threshold,
                        small_cut_threshold=small_pct,
                        comparable=False,
                        reason="Missing current or prior midpoint.",
                    )
                )
                unmatched_required.append(current_record)
                continue
            if prior_record.midpoint <= 0 or current_record.midpoint <= 0:
                deltas.append(
                    GuidanceMetricDelta(
                        metric=current_record.metric,
                        fiscal_period=current_record.fiscal_period,
                        accounting_basis=current_record.accounting_basis,
                        current_record_id=current_record.record_id,
                        prior_record_id=prior_record.record_id,
                        current_midpoint=current_record.midpoint,
                        prior_midpoint=prior_record.midpoint,
                        material_threshold=threshold,
                        small_cut_threshold=small_pct,
                        comparable=False,
                        reason="Zero/negative or sign-unstable midpoint is not economically comparable by percentage.",
                    )
                )
                unmatched_required.append(current_record)
                continue
            delta_pct = current_record.midpoint / prior_record.midpoint - 1
            result = GuidanceMetricDelta(
                metric=current_record.metric,
                fiscal_period=current_record.fiscal_period,
                accounting_basis=current_record.accounting_basis,
                current_record_id=current_record.record_id,
                prior_record_id=prior_record.record_id,
                current_midpoint=current_record.midpoint,
                prior_midpoint=prior_record.midpoint,
                delta_pct=delta_pct,
                material_threshold=threshold,
                small_cut_threshold=small_pct,
                material_cut=delta_pct <= -threshold,
                small_cut=delta_pct <= -small_pct,
            )
        deltas.append(result)
        if result.material_cut:
            material_cuts.append(result)
        if result.small_cut:
            small_cuts.append(result)

    enough_small_cuts = len({item.metric for item in small_cuts}) >= int(small["minimum_cut_metrics"])
    positive_action_conflict = any(
        item.explicit_action in {GuidanceAction.RAISE, GuidanceAction.REAFFIRM}
        for item in current_verified
    ) and (bool(material_cuts) or enough_small_cuts)
    if positive_action_conflict:
        return _unknown(
            ticker,
            rules_hash,
            current_records,
            prior_records,
            as_of=as_of,
            reasons=["Primary-source action language conflicts with the comparable numeric guidance table."],
            metric_deltas=deltas,
            policy=policy,
            rule_path="guidance_v1_1.conflicting_primary_evidence",
        )

    if material_cuts:
        names = ", ".join(sorted({item.metric.value for item in material_cuts}))
        return GuidanceAssessment(
            rules_hash=rules_hash,
            ticker=ticker,
            as_of=as_of,
            current_guidance_record_ids=[item.record_id for item in current_records],
            prior_guidance_record_ids=[item.record_id for item in prior_records],
            comparable_metrics=[item.metric for item in deltas if item.comparable],
            metric_deltas=deltas,
            classification=GuidanceClassification.DETERIORATED,
            guidance_deterioration=True,
            rule_path="guidance_v1_1.material_numeric_cut",
            reasons=[f"Comparable guidance reached the frozen material-cut threshold for: {names}."],
            sources=_unique_sources(current_records + prior_records, policy),
        )

    if enough_small_cuts:
        names = ", ".join(sorted({item.metric.value for item in small_cuts}))
        return GuidanceAssessment(
            rules_hash=rules_hash,
            ticker=ticker,
            as_of=as_of,
            current_guidance_record_ids=[item.record_id for item in current_records],
            prior_guidance_record_ids=[item.record_id for item in prior_records],
            comparable_metrics=[item.metric for item in deltas if item.comparable],
            metric_deltas=deltas,
            classification=GuidanceClassification.DETERIORATED,
            guidance_deterioration=True,
            rule_path="guidance_v1_1.multi_metric_small_cut",
            reasons=[
                f"At least {int(small['minimum_cut_metrics'])} comparable metrics reached the frozen small-cut threshold: {names}."
            ],
            sources=_unique_sources(current_records + prior_records, policy),
        )

    comparable = [item for item in deltas if item.comparable]
    if unmatched_required:
        return _unknown(
            ticker,
            rules_hash,
            current_records,
            prior_records,
            as_of=as_of,
            reasons=[
                "At least one current non-initiated guidance metric lacks a verified comparable prior record or valid midpoint."
            ],
            metric_deltas=deltas,
            policy=policy,
            rule_path="guidance_v1_1.incomplete_comparable_set",
        )
    if not comparable:
        return _unknown(
            ticker,
            rules_hash,
            current_records,
            prior_records,
            as_of=as_of,
            reasons=["No comparable prior/current guidance metric pair is available."],
            metric_deltas=deltas,
            policy=policy,
            rule_path="guidance_v1_1.no_comparable_prior",
        )

    return GuidanceAssessment(
        rules_hash=rules_hash,
        ticker=ticker,
        as_of=as_of,
        current_guidance_record_ids=[item.record_id for item in current_records],
        prior_guidance_record_ids=[item.record_id for item in prior_records],
        comparable_metrics=[item.metric for item in comparable],
        metric_deltas=deltas,
        classification=GuidanceClassification.NOT_DETERIORATED,
        guidance_deterioration=False,
        rule_path="guidance_v1_1.comparable_set_within_tolerance",
        reasons=[
            "All verified comparable current guidance metrics remain within frozen non-deterioration tolerances or are higher."
        ],
        sources=_unique_sources(current_records + prior_records, policy),
    )
