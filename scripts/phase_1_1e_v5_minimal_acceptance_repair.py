from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_function(text: str, name: str, new_source: str) -> str:
    marker = f"\ndef {name}("
    start = text.find(marker)
    if start < 0:
        raise RuntimeError(f"{name}: function start not found")
    start += 1
    next_start = text.find("\ndef ", start + 1)
    if next_start < 0:
        raise RuntimeError(f"{name}: next function boundary not found")
    return text[:start] + new_source.rstrip() + "\n\n" + text[next_start + 1:]


path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()
if '"raw_document_extractor": "guidance-canonical-raw-v5"' not in text:
    raise RuntimeError("minimal repair must start from the published v5 extractor")

helper_marker = "\ndef _canonical_period_binding("
helper_at = text.find(helper_marker)
if helper_at < 0:
    raise RuntimeError("canonical period helper insertion point not found")

helpers = r'''
_CANONICAL_YEAR_QUARTER = re.compile(
    r"\b(?:fiscal\s+)?(?P<year>20\d{2})\s+"
    r"(?P<quarter>first|second|third|fourth)\s+quarter\b",
    re.I,
)
_COMPARISON_YEAR_PREFIX = re.compile(
    r"\b(?:than|over|versus|vs\.?|compared\s+(?:with|to)|from)\s*$",
    re.I,
)
_SUFFIX_MONEY_RANGE = re.compile(
    r"(?P<d1>\$)?\s*(?P<lo>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s1>billion|million|thousand|bn|mm|m|b)?\s*"
    r"(?:to|through|-|–|—)\s*"
    r"(?P<d2>\$)?\s*(?P<hi>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s2>billion|million|thousand|bn|mm|m|b)?\b",
    re.I,
)
_BREAKEVEN_MONEY = re.compile(
    r"\bbetween\s+breakeven\s+and\s+(?P<d>\$)?\s*"
    r"(?P<hi>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<scale>billion|million|thousand|bn|mm|m|b)?\b",
    re.I,
)


def _suffix_owned_money_range(clause: str, anchor: int, mention) -> _ValueBinding | None:
    candidates: list[_ValueBinding] = []
    for match in _SUFFIX_MONEY_RANGE.finditer(clause):
        if match.end() > anchor:
            continue
        bridge = clause[match.end():anchor]
        if len(bridge) > 24 or not re.fullmatch(r"[\s,:;•()]*", bridge):
            continue
        scale = match.group("s2") or match.group("s1")
        dollar = bool(match.group("d1") or match.group("d2"))
        unit = _unit_from_scale(scale, mention.metric, dollar=dollar)
        if unit is GuidanceUnit.UNKNOWN:
            continue
        low = float(match.group("lo").replace(",", ""))
        high = float(match.group("hi").replace(",", ""))
        if low > high:
            continue
        candidates.append(
            _ValueBinding(
                low,
                high,
                unit,
                GuidanceValueKind.ABSOLUTE_LEVEL,
                match.group(0),
                match.start(),
                match.end(),
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: anchor - item.end)
    return candidates[0]


def _breakeven_value(clause: str, anchor: int, mention) -> _ValueBinding | None:
    if mention.metric not in {GuidanceMetric.EBITDA, GuidanceMetric.FCF}:
        return None
    candidates = []
    for match in _BREAKEVEN_MONEY.finditer(clause):
        distance = min(abs(match.start() - anchor), abs(match.end() - anchor))
        if distance > 180:
            continue
        unit = _unit_from_scale(
            match.group("scale"), mention.metric, dollar=bool(match.group("d"))
        )
        if unit is GuidanceUnit.UNKNOWN:
            continue
        high = float(match.group("hi").replace(",", ""))
        candidates.append(
            (
                distance,
                _ValueBinding(
                    0.0,
                    high,
                    unit,
                    GuidanceValueKind.ABSOLUTE_LEVEL,
                    match.group(0),
                    match.start(),
                    match.end(),
                ),
            )
        )
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _local_guidance_year_before_value(clause: str, value) -> _PeriodBinding | None:
    if value is None:
        return None
    left = max(0, value.start - 190)
    prefix = clause[left:value.start]
    matches: list[_PeriodBinding] = []
    patterns = [
        re.compile(r"\b(?P<year>20\d{2})\b[^.;•]{0,60}\b(?:guidance|outlook)\b", re.I),
        re.compile(r"\b(?:guidance|outlook)\b[^.;•]{0,60}\b(?P<year>20\d{2})\b", re.I),
    ]
    for pattern in patterns:
        for match in pattern.finditer(prefix):
            if re.search(r"\bquarter\b", match.group(0), re.I):
                continue
            context_before = prefix[max(0, match.start() - 45):match.start()]
            if re.search(r"\b(?:prior|previous|comparison)\b", context_before, re.I):
                continue
            year_start = left + match.start("year")
            year_end = left + match.end("year")
            matches.append(
                _PeriodBinding(
                    f"FY{int(match.group('year'))}",
                    GuidancePeriodKind.FULL_YEAR,
                    match.group("year"),
                    year_start,
                    year_end,
                )
            )
    if not matches:
        return None
    matches.sort(key=lambda item: item.end, reverse=True)
    nearest = matches[0]
    if len({item.period for item in matches if nearest.end - item.end <= 8}) > 1:
        return None
    return nearest


def _nearest_preceding_section_period(segment: str, mention) -> _PeriodBinding | None:
    prefix = segment[max(0, mention.start - 700):mention.start]
    offset = max(0, mention.start - 700)
    candidates: list[tuple[int, _PeriodBinding]] = []

    for match in _CANONICAL_YEAR_QUARTER.finditer(prefix):
        context = prefix[max(0, match.start() - 80):min(len(prefix), match.end() + 100)]
        if not _FORWARD_SIGNAL.search(context):
            continue
        year = int(match.group("year"))
        q = _QUARTER_WORD[match.group("quarter").lower()]
        binding = _PeriodBinding(
            f"Q{q}FY{year}",
            GuidancePeriodKind.QUARTER,
            match.group(0),
            offset + match.start(),
            offset + match.end(),
        )
        candidates.append((mention.start - binding.end, binding))

    for pattern in _CANONICAL_FULL_YEAR:
        for match in pattern.finditer(prefix):
            context = prefix[max(0, match.start() - 80):min(len(prefix), match.end() + 110)]
            if not _FORWARD_SIGNAL.search(context):
                continue
            year = _normalize_year(match.group(1))
            binding = _PeriodBinding(
                f"FY{year}",
                GuidancePeriodKind.FULL_YEAR,
                match.group(0),
                offset + match.start(),
                offset + match.end(),
            )
            candidates.append((mention.start - binding.end, binding))

    for pattern in _CANONICAL_QUARTER:
        for match in pattern.finditer(prefix):
            context = prefix[max(0, match.start() - 80):min(len(prefix), match.end() + 110)]
            if not _FORWARD_SIGNAL.search(context):
                continue
            token = match.group(1)
            q = token if token.isdigit() else _QUARTER_WORD[token.lower()]
            year = _normalize_year(match.group(2))
            binding = _PeriodBinding(
                f"Q{q}FY{year}",
                GuidancePeriodKind.QUARTER,
                match.group(0),
                offset + match.start(),
                offset + match.end(),
            )
            candidates.append((mention.start - binding.end, binding))

    candidates = [item for item in candidates if 0 <= item[0] <= 520]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], 0 if item[1].kind is GuidancePeriodKind.FULL_YEAR else 1))
    best_distance = candidates[0][0]
    tied = [item[1] for item in candidates if item[0] == best_distance]
    periods = {item.period for item in tied}
    return tied[0] if len(periods) == 1 else None


def _period_is_next_section(clause: str, value, period: _PeriodBinding) -> bool:
    if value is None or period.start < value.end:
        return False
    bridge = clause[value.end:period.start]
    return bool(re.search(r"[.!?•]|\b(?:fiscal|full[- ]year|quarter)\b", bridge, re.I))


def _ambiguous_updated_previous_table(clause: str) -> bool:
    return bool(
        re.search(r"\bUpdated\s*Previous\b", clause, re.I)
        and len(list(_SUFFIX_MONEY_RANGE.finditer(clause))) >= 2
    )


def _ambiguous_adjusted_gaap_eps(clause: str, anchor: int, mention) -> bool:
    if mention.metric is not GuidanceMetric.EPS:
        return False
    if "gaap" not in mention.text.lower() or "non-gaap" in mention.text.lower():
        return False
    prefix = clause[max(0, anchor - 55):anchor]
    adjusted = list(re.finditer(r"\badjusted\b", prefix, re.I))
    if not adjusted:
        return False
    tail = prefix[adjusted[-1].end():]
    return not re.search(r"\bEPS\b", tail, re.I)


def _delta_midpoint_narrative(clause: str, value) -> bool:
    if value is None:
        return False
    context = clause[max(0, value.start - 80):min(len(clause), value.end + 70)]
    return bool(
        re.search(r"\bby\s+\$?\s*\d", context, re.I)
        and re.search(r"\bto\s+\$?\s*\d", context, re.I)
        and re.search(r"\bat\s+the\s+midpoint\b", context, re.I)
    )
'''
text = text[:helper_at] + helpers + text[helper_at:]

text = replace_function(
    text,
    "_canonical_period_binding",
    r'''def _canonical_period_binding(clause: str, anchor: int, mention) -> _PeriodBinding | None:
    mention_end = anchor + len(mention.text)
    explicit: list[tuple[int, int, _PeriodBinding]] = []

    def add(binding: _PeriodBinding) -> None:
        if not _admissible_period_candidate(clause, anchor, binding):
            return
        if binding.end <= anchor:
            direction = 0
            distance = anchor - binding.end
        elif binding.start >= mention_end:
            direction = 1
            distance = binding.start - mention_end
        else:
            direction = 0
            distance = 0
        explicit.append((direction, distance, binding))

    for pattern in _CANONICAL_FULL_YEAR:
        for match in pattern.finditer(clause):
            year = _normalize_year(match.group(1))
            add(_PeriodBinding(f"FY{year}", GuidancePeriodKind.FULL_YEAR, match.group(0), match.start(), match.end()))

    for pattern in _CANONICAL_QUARTER:
        for match in pattern.finditer(clause):
            token = match.group(1)
            q = token if token.isdigit() else _QUARTER_WORD[token.lower()]
            year = _normalize_year(match.group(2))
            add(_PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), match.start(), match.end()))

    for match in _CANONICAL_YEAR_QUARTER.finditer(clause):
        year = int(match.group("year"))
        q = _QUARTER_WORD[match.group("quarter").lower()]
        add(_PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), match.start(), match.end()))

    if explicit:
        preceding = [item for item in explicit if item[0] == 0 and item[2].end <= anchor]
        pool = preceding or [item for item in explicit if item[0] == 1 and item[1] <= 240]
        if pool:
            pool.sort(key=lambda item: (item[0], item[1], -item[2].end))
            best_distance = pool[0][1]
            tied = [item for item in pool if item[0] == pool[0][0] and item[1] == best_distance]
            periods = {item[2].period for item in tied}
            if len(periods) == 1:
                return tied[0][2]

    left = max(0, anchor - 150)
    right = min(len(clause), mention_end + 120)
    local = clause[left:right]
    bare: list[tuple[int, int, _PeriodBinding]] = []
    for match in _BARE_YEAR.finditer(local):
        start, end = left + match.start(), left + match.end()
        prefix = clause[max(0, start - 24):start]
        if re.search(r"(?:Q[1-4]|[1-4]Q)\s*(?:FY)?\s*'?\s*$", prefix, re.I):
            continue
        if _COMPARISON_YEAR_PREFIX.search(prefix):
            continue
        around = clause[max(0, start - 90): min(len(clause), end + 110)]
        if not _FORWARD_SIGNAL.search(around):
            continue
        binding = _PeriodBinding(f"FY{int(match.group(1))}", GuidancePeriodKind.FULL_YEAR, match.group(0), start, end)
        if not _admissible_period_candidate(clause, anchor, binding):
            continue
        if end <= anchor:
            bare.append((0, anchor - end, binding))
        else:
            bare.append((1, max(0, start - mention_end), binding))
    if not bare:
        return None
    preceding = [item for item in bare if item[0] == 0]
    pool = preceding or [item for item in bare if item[1] <= 100]
    if not pool:
        return None
    pool.sort(key=lambda item: (item[0], item[1], -item[2].end))
    best = pool[0]
    tied = [item for item in pool if item[:2] == best[:2]]
    periods = {item[2].period for item in tied}
    return best[2] if len(periods) == 1 else None''',
)

text = replace_function(
    text,
    "_value_is_historical_actual",
    r'''def _value_is_historical_actual(clause: str, anchor: int, value) -> bool:
    if value is None:
        return False
    metric_to_value = clause[anchor:value.start] if value.start >= anchor else ""
    before = clause[max(0, min(anchor, value.start) - 150):value.start]
    after = clause[value.end:min(len(clause), value.end + 110)]
    forward_owned = bool(_EXPLICIT_FORWARD.search(metric_to_value))

    if not forward_owned and re.search(r"\bpreliminary\s+unaudited\b", before, re.I):
        return True

    if (
        not forward_owned
        and value.low is not None
        and value.high is not None
        and abs(value.low - value.high) <= 1e-12
        and re.match(
            r"^\s*(?:,|;)?\s*(?:up|down)\s+\d+(?:\.\d+)?%\b"
            r"(?:\s+(?:YoY|Y/Y|year[- ]over[- ]year))?",
            after,
            re.I,
        )
    ):
        return True

    actuals = list(_ACTUAL_VALUE.finditer(before))
    if not actuals:
        return False
    latest_actual = actuals[-1]
    after_actual = before[latest_actual.end():]
    if _FORWARD_SIGNAL.search(after_actual):
        return False
    return len(before) - latest_actual.end() <= 120''',
)

text = replace_function(
    text,
    "_fact_role",
    r'''def _fact_role(clause: str, value) -> GuidanceFactRole:
    if value is None:
        return GuidanceFactRole.CURRENT
    before = clause[max(0, value.start - 180):value.start]
    # "previously updated on May 7, 2026" identifies the date of the current
    # reaffirmed outlook; it is not a quoted-prior value owner.
    before = re.sub(
        r"\bpreviously\s+updated\s+on\s+[A-Za-z]+\s+\d{1,2},?\s+20\d{2}\b",
        "",
        before,
        flags=re.I,
    )
    if (
        re.search(r"\b(?:from\s+(?:our\s+)?)?prior(?:\s+[A-Za-z0-9*.-]+){0,5}\s+(?:guidance|outlook|forecast)\b", before, re.I)
        or re.search(r"\bprevious(?:\s+[A-Za-z0-9*.-]+){0,5}\s+(?:guidance|outlook|forecast)\b", before, re.I)
        or re.search(r"\bpreviously(?:\s+(?:expected|forecast|guided|provided|stated))?\b", before, re.I)
    ):
        return GuidanceFactRole.QUOTED_PRIOR
    return GuidanceFactRole.CURRENT''',
)

text = replace_function(
    text,
    "_canonical_scope",
    r'''def _canonical_scope(clause: str, anchor: int, mention, value) -> tuple[GuidanceScopeKind, str | None]:
    value_end = value.end if value is not None else anchor + len(mention.text)
    local_context = clause[max(0, anchor - 100): min(len(clause), value_end)]
    contribution = _NON_COMPANY_CONTRIBUTION.search(local_context)
    if contribution:
        kind = GuidanceScopeKind.PRODUCT if re.search(r"\bproducts?\b", contribution.group(0), re.I) else GuidanceScopeKind.SEGMENT
        return kind, contribution.group(0).strip()
    if mention.metric is not GuidanceMetric.REVENUE:
        return GuidanceScopeKind.COMPANY, None
    label = mention.text.strip()
    lower = label.lower()
    prefix = clause[max(0, anchor - 70):anchor]
    prefix = re.split(r"[.;:•|\n\r]", prefix)[-1].strip()

    # Branded net-sales guidance (e.g. an all-caps drug/product name immediately
    # owning "net sales") is product guidance, not consolidated company revenue.
    if "net sales" in lower:
        brand = re.search(r"\b([A-Z][A-Z0-9®™-]{2,})\s*$", prefix)
        if brand:
            return GuidanceScopeKind.PRODUCT, brand.group(1)

    if "total product revenue" in lower or "total revenue" in lower or "consolidated revenue" in lower or "net sales" in lower:
        return GuidanceScopeKind.COMPANY, label
    if "segment revenue" in lower:
        return GuidanceScopeKind.SEGMENT, label
    if "product revenue" in lower and "total product revenue" not in lower:
        return GuidanceScopeKind.PRODUCT, label
    if _PRODUCT_REVENUE_QUALIFIER.search(prefix):
        return GuidanceScopeKind.PRODUCT, prefix
    segment_match = _SEGMENT_REVENUE_QUALIFIER.search(prefix)
    if segment_match:
        return GuidanceScopeKind.SEGMENT, segment_match.group(0).strip()
    return GuidanceScopeKind.COMPANY, None''',
)

text = replace_function(
    text,
    "_suppress_document_fragments",
    r'''def _suppress_document_fragments(facts: Iterable[TypedGuidanceFact], rejected: list[dict]) -> list[TypedGuidanceFact]:
    items = list(facts)
    remove: set[int] = set()
    for i, fact in enumerate(items):
        if i in remove or fact.low is None or fact.high is None or fact.low == fact.high:
            continue
        for j, other in enumerate(items):
            if i == j or j in remove or not _same_economic_identity(fact, other):
                continue
            if other.low is None or other.high is None or other.low != other.high:
                continue
            if fact.unit in _MONEY_UNIT_SCALE and other.unit in _MONEY_UNIT_SCALE:
                lo = _money_base(fact.low, fact.unit); hi = _money_base(fact.high, fact.unit); point = _money_base(other.low, other.unit)
            elif fact.unit == other.unit:
                lo, hi, point = fact.low, fact.high, other.low
            else:
                continue
            if lo is None or hi is None or point is None:
                continue
            tolerance = max(1e-8, abs(point) * 1e-8)
            if abs(point - lo) <= tolerance or abs(point - hi) <= tolerance:
                remove.add(j)
                rejected.append({"reason": "same_document_range_endpoint_fragment", "metric": other.metric.value, "period": other.fiscal_period, "value": point})

    scaled_units = {GuidanceUnit.USD_THOUSAND, GuidanceUnit.USD_MILLION, GuidanceUnit.USD_BILLION}
    for i, fact in enumerate(items):
        if i in remove or fact.low is None or fact.high is None or fact.unit is not GuidanceUnit.USD:
            continue
        for j, other in enumerate(items):
            if i == j or j in remove or other.unit not in scaled_units:
                continue
            if not _same_economic_identity(fact, other):
                continue
            exact_shadow = fact.low == other.low and fact.high == other.high
            endpoint_shadow = (
                fact.low == fact.high
                and other.low is not None
                and other.high is not None
                and (abs(fact.low - other.low) <= 1e-12 or abs(fact.low - other.high) <= 1e-12)
            )
            if exact_shadow or endpoint_shadow:
                remove.add(i)
                rejected.append({
                    "reason": "unscaled_shadow_fragment",
                    "metric": fact.metric.value,
                    "period": fact.fiscal_period,
                    "value": [fact.low, fact.high],
                })
                break

    best_by_key: dict[tuple, int] = {}
    for i, fact in enumerate(items):
        if i in remove:
            continue
        low = _money_base(fact.low, fact.unit) if fact.unit in _MONEY_UNIT_SCALE else fact.low
        high = _money_base(fact.high, fact.unit) if fact.unit in _MONEY_UNIT_SCALE else fact.high
        key = (fact.ticker, fact.metric.value, fact.fiscal_period, fact.accounting_basis, fact.scope_kind.value, "" if fact.scope_kind is GuidanceScopeKind.COMPANY else (fact.scope_label or ""), fact.role.value, fact.value_kind.value, low, high, fact.explicit_action.value)
        prior = best_by_key.get(key)
        if prior is None:
            best_by_key[key] = i
            continue
        prior_fact = items[prior]
        score = (fact.low != fact.high, fact.unit in {GuidanceUnit.USD_MILLION, GuidanceUnit.USD_BILLION, GuidanceUnit.USD_THOUSAND})
        prior_score = (prior_fact.low != prior_fact.high, prior_fact.unit in {GuidanceUnit.USD_MILLION, GuidanceUnit.USD_BILLION, GuidanceUnit.USD_THOUSAND})
        if score > prior_score:
            remove.add(prior); best_by_key[key] = i
        else:
            remove.add(i)
    return [fact for idx, fact in enumerate(items) if idx not in remove]''',
)

text = replace_function(
    text,
    "extract_canonical_typed_guidance_facts",
    r'''def extract_canonical_typed_guidance_facts(document: SourceDocument) -> RawTypedGuidanceExtraction:
    text = html_to_text(document.content or "")
    facts: list[TypedGuidanceFact] = []
    rejected: list[dict] = []
    seen: set[tuple] = set()
    for segment in _segments(text):
        mentions = _metric_mentions(segment)
        if not mentions:
            continue
        for index, mention in enumerate(mentions):
            clause, anchor = _metric_clause(segment, mentions, index)
            local = clause[max(0, anchor - 140): min(len(clause), anchor + len(mention.text) + 160)]
            explicit_forward = _explicit_forward_context(local)
            local_action = _metric_action(segment, clause, anchor, mention)
            if not explicit_forward and local_action is GuidanceAction.NONE:
                continue
            if _ambiguous_parallel_period_table(clause):
                rejected.append({"reason": "ambiguous_parallel_period_table", "metric": mention.metric.value, "evidence": clause[:500]}); continue
            if _ambiguous_current_prior_table(clause):
                rejected.append({"reason": "ambiguous_current_prior_table", "metric": mention.metric.value, "evidence": clause[:500]}); continue
            if _ambiguous_updated_previous_table(clause):
                rejected.append({"reason": "ambiguous_updated_previous_table", "metric": mention.metric.value, "evidence": clause[:500]}); continue
            if _ambiguous_adjusted_gaap_eps(clause, anchor, mention):
                rejected.append({"reason": "ambiguous_accounting_basis", "metric": mention.metric.value, "evidence": clause[:500]}); continue

            previous_now_value, previous_now_prior = _previous_now_value_pair(clause, mention)
            directional_value, directional_prior = _directional_value_pair(clause, anchor, mention, local_action)
            breakeven_value = _breakeven_value(clause, anchor, mention)
            suffix_value = _suffix_owned_money_range(clause, anchor, mention)
            value = previous_now_value or directional_value or breakeven_value or suffix_value or _bind_value(clause, mention, anchor)
            explicit_prior = previous_now_prior or directional_prior

            if value is not None and value.low > value.high:
                rejected.append({"reason": "invalid_reversed_range", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue
            if _delta_midpoint_narrative(clause, value):
                rejected.append({"reason": "delta_to_midpoint_narrative", "metric": mention.metric.value, "value_text": value.text if value else None, "evidence": clause[:500]}); continue
            if value is not None and not _value_has_local_metric_owner(clause, anchor, mention, value):
                rejected.append({"reason": "metric_value_locality", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue
            if value is not None and _value_is_historical_actual(clause, anchor, value):
                rejected.append({"reason": "historical_actual", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue

            role = GuidanceFactRole.CURRENT if previous_now_value is not None else _fact_role(clause, value)
            period = _canonical_period_binding(clause, anchor, mention)

            local_period = _local_guidance_year_before_value(clause, value)
            if local_period is not None:
                if period is None:
                    period = local_period
                elif period.period != local_period.period:
                    if not (
                        period.kind is GuidancePeriodKind.QUARTER
                        and period.period.endswith(local_period.period.replace("FY", "FY"))
                    ):
                        period = local_period

            if period is not None and _period_is_next_section(clause, value, period):
                period = _nearest_preceding_section_period(segment, mention)

            if period is None and role is GuidanceFactRole.QUOTED_PRIOR:
                period = _unique_explicit_period_from_segment(segment)
            if period is None and (explicit_forward or local_action is not GuidanceAction.NONE):
                period = _nearest_preceding_section_period(segment, mention)
            if period is None:
                rejected.append({"reason": "ambiguous_or_missing_period", "metric": mention.metric.value, "evidence": clause[:500]}); continue

            if value is not None and value.end <= period.start <= anchor:
                rejected.append({
                    "reason": "value_crosses_period_boundary",
                    "metric": mention.metric.value,
                    "value_text": value.text,
                    "period": period.period,
                    "evidence": clause[:500],
                }); continue
            if value is None and local_action not in {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM, GuidanceAction.WITHDRAW}:
                rejected.append({"reason": "missing_bound_value", "metric": mention.metric.value, "evidence": clause[:500]}); continue

            scope_kind, scope_label = _canonical_scope(clause, anchor, mention, value)
            basis = _basis(segment, mention)
            fact = _build_fact(document=document, mention=mention, period=period, basis=basis, scope_kind=scope_kind, scope_label=scope_label, role=role, action=local_action, value=value, clause=clause, anchor=anchor)
            key = (fact.ticker, fact.metric.value, fact.fiscal_period, fact.accounting_basis, fact.scope_kind.value, fact.scope_label or "", fact.role.value, fact.low, fact.high, fact.unit.value, fact.value_kind.value, fact.explicit_action.value)
            if key not in seen:
                seen.add(key); facts.append(fact)
            if explicit_prior is not None:
                prior_fact = _build_fact(document=document, mention=mention, period=period, basis=basis, scope_kind=scope_kind, scope_label=scope_label, role=GuidanceFactRole.QUOTED_PRIOR, action=GuidanceAction.NONE, value=explicit_prior, clause=clause, anchor=anchor)
                prior_key = (prior_fact.ticker, prior_fact.metric.value, prior_fact.fiscal_period, prior_fact.accounting_basis, prior_fact.scope_kind.value, prior_fact.scope_label or "", prior_fact.role.value, prior_fact.low, prior_fact.high, prior_fact.unit.value, prior_fact.value_kind.value, prior_fact.explicit_action.value)
                if prior_key not in seen:
                    seen.add(prior_key); facts.append(prior_fact)
    facts = _suppress_document_fragments(facts, rejected)
    return RawTypedGuidanceExtraction(ticker=document.ticker, document_id=document.document_id, facts=tuple(facts), rejected_candidates=tuple(rejected))''',
)

text = text.replace(
    '"raw_document_extractor": "guidance-canonical-raw-v5"',
    '"raw_document_extractor": "guidance-canonical-raw-v6-candidate"',
)
path.write_text(text)

# Add regression tests derived directly from the audited v5 divergence corpus.
test_path = ROOT / "backend/tests/test_guidance_raw_canonical_extractor.py"
tests = test_path.read_text()
marker = "def test_v5_minimal_repair_blacksky_reaffirm_is_current():"
if marker not in tests:
    tests += r'''


def test_v5_minimal_repair_blacksky_reaffirm_is_current():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "BKSYFIX",
            "2026 Outlook. BlackSky is reaffirming its full year 2026 outlook, which was previously updated on May 7, 2026. "
            "The Company expects full year revenue between $130 million and $150 million, Adjusted EBITDA between $12 million and $24 million.",
        )
    )
    facts = [fact for fact in extraction.facts if fact.fiscal_period == "FY2026"]
    assert facts
    assert all(fact.role is GuidanceFactRole.CURRENT for fact in facts)


def test_v5_minimal_repair_breakeven_range_is_zero_to_upper_bound():
    extraction = extract_canonical_typed_guidance_facts(
        _document("BKEVEN", "Full year 2025 Adjusted EBITDA is expected to be between breakeven and $10 million.")
    )
    ebitda = [fact for fact in extraction.facts if fact.metric.value == "ebitda"]
    assert any((fact.low, fact.high) == (0.0, 10.0) for fact in ebitda)


def test_v5_minimal_repair_suffix_owned_compact_ranges_bind_correct_metric():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "KRMNFIX",
            "Raised full-year 2025 guidance to: $452 - $458 million revenue; $138.5 - $141.5 million Adjusted EBITDA.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    ebitda = [fact for fact in extraction.facts if fact.metric.value == "ebitda"]
    assert any((fact.low, fact.high) == (452.0, 458.0) for fact in revenue)
    assert any((fact.low, fact.high) == (138.5, 141.5) for fact in ebitda)


def test_v5_minimal_repair_updated_previous_compact_table_fails_closed():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "FRPTFIX",
            "2025 Guidance UpdatedPrevious ~13%13 - 16% Net Sales Growth YoY $190 - $195M $190M - $210M Adjusted EBITDA ~$140M ~$175M Capital Expenditures.",
        )
    )
    assert not extraction.facts
    assert any(item["reason"] == "ambiguous_updated_previous_table" for item in extraction.rejected_candidates)


def test_v5_minimal_repair_adjacent_forward_guidance_year_outranks_historical_period():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "ATROFIX",
            "Full year 2024 preliminary unaudited revenue was approximately $796 million, an increase over 2023; Initial 2025 revenue guidance established at $820 million to $860 million.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert any(fact.fiscal_period == "FY2025" and (fact.low, fact.high) == (820.0, 860.0) for fact in revenue)
    assert all(not (fact.fiscal_period == "FY2024" and (fact.low, fact.high) == (820.0, 860.0)) for fact in revenue)


def test_v5_minimal_repair_year_before_quarter_header_binds_quarter():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "HPEQ",
            "Fiscal 2026 Fourth Quarter Outlook HPE estimates revenue to be in the range of $13.9 billion to $14.8 billion.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert any(fact.fiscal_period == "Q4FY2026" and (fact.low, fact.high) == (13.9, 14.8) for fact in revenue)


def test_v5_minimal_repair_following_section_period_cannot_steal_prior_value():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "HPEFCF",
            "Fiscal 2026 Full Year Outlook. HPE is raising its free cash flow guidance and now expects free cash flow to be at least $3.75 billion. Fiscal 2027 Outlook Framework. The company is raising its revenue growth outlook.",
        )
    )
    fcf = [fact for fact in extraction.facts if fact.metric.value == "fcf"]
    assert any(fact.fiscal_period == "FY2026" and fact.low == 3.75 for fact in fcf)
    assert all(fact.fiscal_period != "FY2027" for fact in fcf)


def test_v5_minimal_repair_historical_point_result_with_yoy_tail_is_rejected():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "SPXCFIX",
            "Adjusted EBITDA of $126.7 million, up 16.3% YoY. Raising 2025 Guidance. Adjusted EBITDA guidance is $485 million to $510 million for full-year 2025.",
        )
    )
    ebitda = [fact for fact in extraction.facts if fact.metric.value == "ebitda"]
    assert all(fact.low != 126.7 for fact in ebitda)
    assert any((fact.low, fact.high) == (485.0, 510.0) for fact in ebitda)


def test_v5_minimal_repair_branded_net_sales_is_product_scope():
    extraction = extract_canonical_typed_guidance_facts(
        _document("KNSAFIX", "We have raised our 2026 ARCALYST net sales guidance to between $930 million and $945 million.")
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert revenue
    assert all(fact.scope_kind is GuidanceScopeKind.PRODUCT for fact in revenue)


def test_v5_minimal_repair_unscaled_range_endpoint_shadow_is_suppressed():
    extraction = extract_canonical_typed_guidance_facts(
        _document("PLTRFIX", "For full year 2026, we are raising our revenue guidance to between $8.150 - $8.158 billion.")
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert any((fact.low, fact.high, fact.unit.value) == (8.15, 8.158, "USD_BILLION") for fact in revenue)
    assert all(not (fact.low == fact.high == 8.15 and fact.unit.value == "USD") for fact in revenue)


def test_v5_minimal_repair_ambiguous_adjusted_gaap_headline_fails_closed():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "HUMFIX",
            "Affirms Adjusted FY 2026 GAAP EPS guidance of 'at least $9.00'; while revising GAAP EPS guidance to 'at least $8.36' from the previous estimate of 'at least $8.89'. FY 2026 Earnings Guidance. Humana revises its GAAP EPS guidance to at least $8.36 from at least $8.89, while affirming its Adjusted EPS guidance of at least $9.00.",
        )
    )
    gaap = [fact for fact in extraction.facts if fact.metric.value == "eps" and fact.accounting_basis == "GAAP"]
    assert all(fact.low != 9.0 for fact in gaap)
    assert any(fact.low == 8.36 for fact in gaap)


def test_v5_minimal_repair_delta_to_midpoint_narrative_is_not_a_range():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "ZETAMID",
            "Full Year 2026 Guidance. Increasing full year 2026 revenue guidance by $33 million to $1,818 million at the midpoint. Increasing revenue guidance to a range of $1,811 million to $1,824 million.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert all((fact.low, fact.high) != (33.0, 1818.0) for fact in revenue)
    assert any((fact.low, fact.high) == (1811.0, 1824.0) for fact in revenue)


def test_v5_minimal_repair_section_period_recovers_full_year_fcf():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "ZETAFCF",
            "Increasing 2026 Guidance. Full Year 2026. Increasing free cash flow guidance to a range of $254.8 million to $255.8 million, up from prior guidance.",
        )
    )
    fcf = [fact for fact in extraction.facts if fact.metric.value == "fcf"]
    assert any(fact.fiscal_period == "FY2026" and (fact.low, fact.high) == (254.8, 255.8) for fact in fcf)
'''
    test_path.write_text(tests)
