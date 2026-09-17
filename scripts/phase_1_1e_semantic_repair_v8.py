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


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_canonical_extractor() -> None:
    path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
    text = path.read_text()

    text = replace_once(
        text,
        '    r"for\\s+the\\s+quarter\\s+ended|for\\s+the\\s+year\\s+ended|year[- ]to[- ]date)\\b",',
        '    r"preliminary(?:\\s+unaudited)?|for\\s+the\\s+quarter\\s+ended|"\n'
        '    r"for\\s+the\\s+year\\s+ended|year[- ]to[- ]date)\\b",',
        "preliminary actual vocabulary",
    )

    marker = '_QUARTER_WORD = {"first": "1", "second": "2", "third": "3", "fourth": "4"}\n'
    insertion = r'''_CANONICAL_YEAR_QUARTER = re.compile(
    r"\b(?:fiscal(?:\s+year)?\s+)?(20\d{2})\s+"
    r"(first|second|third|fourth)\s+quarter\b",
    re.I,
)
_STRONG_FORWARD_YEAR_PATTERNS = [
    re.compile(
        r"\b(?P<year>20\d{2})\b(?=[^.;\n]{0,60}\b(?:guidance|outlook|forecast)\b)",
        re.I,
    ),
    re.compile(
        r"\b(?:guidance|outlook|forecast|rais(?:e|es|ed|ing)|"
        r"initial|initiat(?:e|es|ed|ing)|revis(?:e|es|ed|ing)|"
        r"updat(?:e|es|ed|ing)|reaffirm(?:s|ed|ing)?)\b"
        r"[^.;\n]{0,60}\b(?P<year>20\d{2})\b",
        re.I,
    ),
]
_COMPARISON_YEAR_PREFIX = re.compile(
    r"\b(?:comparisons?\s+(?:against|to)|compared\s+(?:with|to)|against|versus|vs\.?)"
    r"[^.;]{0,40}$",
    re.I,
)
_SIMPLE_TO_FROM = re.compile(
    r"\bto\s+(?:['\"]?\s*(?:at\s+least|approximately|about)\s*)?"
    r"(?P<dnew>\$)?\s*(?P<new>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<snew>billion|million|thousand|bn|mm|m|b)?['\"]?"
    r"[^.;\n]{0,100}?\bfrom\b[^$;\n]{0,90}?"
    r"(?P<dold>\$)?\s*(?P<old>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<sold>billion|million|thousand|bn|mm|m|b)?",
    re.I,
)
_BREAKEVEN_TO_MONEY = re.compile(
    r"\b(?:between\s+)?breakeven\s+(?:and|to|through|-|–|—)\s*"
    r"(?P<d>\$)?\s*(?P<high>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<scale>billion|million|thousand|bn|mm|m|b)?\b",
    re.I,
)
_BRANDED_NET_SALES = re.compile(
    r"(?:^|[\s(])(?P<brand>[A-Z][A-Z0-9-]{2,})(?:®|™)?\s*$"
)
_BRAND_SCOPE_RESERVED = {
    "TOTAL", "FULL", "GAAP", "NON", "ADJUSTED", "ANNUAL", "FISCAL", "COMPANY",
}

'''
    if "_CANONICAL_YEAR_QUARTER" not in text:
        text = replace_once(text, marker, insertion + marker, "semantic v6 constants")

    helper_block = r'''def _strong_forward_year_binding(clause: str, anchor: int, mention) -> _PeriodBinding | None:
    candidates: list[tuple[int, _PeriodBinding]] = []
    for pattern in _STRONG_FORWARD_YEAR_PATTERNS:
        for match in pattern.finditer(clause):
            year_match = match.group("year")
            start, end = match.start("year"), match.end("year")
            prefix = clause[max(0, start - 60):start]
            suffix = clause[end:min(len(clause), end + 80)]
            around = clause[max(0, start - 35):min(len(clause), end + 35)]
            if re.search(r"\bquarter\b", around, re.I):
                continue
            if _COMPARISON_YEAR_PREFIX.search(prefix):
                continue
            forward_after = _FORWARD_SIGNAL.search(suffix)
            if forward_after and re.search(
                r"\b(?:preliminary|unaudited|results?|actual)\b",
                suffix[:forward_after.start()],
                re.I,
            ):
                continue
            binding = _PeriodBinding(
                f"FY{int(year_match)}",
                GuidancePeriodKind.FULL_YEAR,
                year_match,
                start,
                end,
            )
            distance = min(abs(end - anchor), abs(start - (anchor + len(mention.text))))
            candidates.append((distance, binding))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], -item[1].start))
    nearest = candidates[0][0]
    tied = [item[1] for item in candidates if item[0] == nearest]
    periods = {item.period for item in tied}
    return tied[0] if len(periods) == 1 else None


def _section_period_binding(segment: str, mention) -> _PeriodBinding | None:
    candidates: list[_PeriodBinding] = []
    for pattern in _CANONICAL_FULL_YEAR:
        for match in pattern.finditer(segment):
            year = _normalize_year(match.group(1))
            candidates.append(
                _PeriodBinding(
                    f"FY{year}",
                    GuidancePeriodKind.FULL_YEAR,
                    match.group(0),
                    match.start(),
                    match.end(),
                )
            )
    for pattern in _CANONICAL_QUARTER:
        for match in pattern.finditer(segment):
            token = match.group(1)
            q = token if token.isdigit() else _QUARTER_WORD[token.lower()]
            year = _normalize_year(match.group(2))
            candidates.append(
                _PeriodBinding(
                    f"Q{q}FY{year}",
                    GuidancePeriodKind.QUARTER,
                    match.group(0),
                    match.start(),
                    match.end(),
                )
            )
    for match in _CANONICAL_YEAR_QUARTER.finditer(segment):
        year = int(match.group(1))
        q = _QUARTER_WORD[match.group(2).lower()]
        candidates.append(
            _PeriodBinding(
                f"Q{q}FY{year}",
                GuidancePeriodKind.QUARTER,
                match.group(0),
                match.start(),
                match.end(),
            )
        )
    preceding = [
        item for item in candidates
        if item.end <= mention.start and 0 <= mention.start - item.end <= 450
    ]
    if not preceding:
        return None
    preceding.sort(key=lambda item: (mention.start - item.end, -item.start))
    best_distance = mention.start - preceding[0].end
    tied = [item for item in preceding if mention.start - item.end == best_distance]
    periods = {item.period for item in tied}
    return tied[0] if len(periods) == 1 else None


'''
    if "def _strong_forward_year_binding(" not in text:
        target = "def _canonical_period_binding("
        pos = text.find(target)
        if pos < 0:
            raise RuntimeError("canonical period function not found")
        text = text[:pos] + helper_block + text[pos:]

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
        year = int(match.group(1))
        q = _QUARTER_WORD[match.group(2).lower()]
        add(_PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), match.start(), match.end()))

    near_quarters = [
        item for item in explicit
        if item[2].kind is GuidancePeriodKind.QUARTER and item[1] <= 80
    ]
    if near_quarters:
        near_quarters.sort(key=lambda item: (item[0], item[1], -item[2].end))
        best = near_quarters[0]
        tied = [item for item in near_quarters if item[:2] == best[:2]]
        periods = {item[2].period for item in tied}
        if len(periods) == 1:
            return tied[0][2]

    strong = _strong_forward_year_binding(clause, anchor, mention)
    if strong is not None:
        return strong

    if explicit:
        preceding = [item for item in explicit if item[0] == 0 and item[2].end <= anchor]
        pool = preceding or [item for item in explicit if item[0] == 1 and item[1] <= 240]
        if pool:
            pool.sort(key=lambda item: (item[0], item[1], -item[2].end))
            best_distance = pool[0][1]
            tied = [item for item in pool if item[0] == pool[0][0] and item[1] == best_distance]
            periods = {item[2].period for item in tied}
            return tied[0][2] if len(periods) == 1 else None

    left = max(0, anchor - 150)
    right = min(len(clause), mention_end + 120)
    local = clause[left:right]
    bare: list[tuple[int, int, _PeriodBinding]] = []
    for match in _BARE_YEAR.finditer(local):
        start, end = left + match.start(), left + match.end()
        prefix = clause[max(0, start - 40):start]
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
    start = max(0, min(anchor, value.start) - 180)
    before = clause[start:value.start]
    after = clause[value.end:min(len(clause), value.end + 120)]
    forward_before = bool(_FORWARD_SIGNAL.search(before))
    if not forward_before and re.search(
        r"^\s*(?:,|;)?\s*(?:up|down)\s+\d+(?:\.\d+)?%\b"
        r"(?:\s+(?:YoY|Y/Y|year[- ]over[- ]year))?",
        after,
        re.I,
    ):
        return True
    if not forward_before and re.search(r"\bpreliminary(?:\s+unaudited)?\b", before[-140:], re.I):
        return True
    actuals = list(_ACTUAL_VALUE.finditer(before))
    if not actuals:
        return False
    latest_actual = actuals[-1]
    after_actual = before[latest_actual.end():]
    if _FORWARD_SIGNAL.search(after_actual):
        return False
    return len(before) - latest_actual.end() <= 140''',
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
    prefix = clause[max(0, anchor - 80):anchor]
    brand_match = _BRANDED_NET_SALES.search(prefix)
    if "net sales" in lower and brand_match:
        brand = brand_match.group("brand")
        if brand.upper() not in _BRAND_SCOPE_RESERVED:
            return GuidanceScopeKind.PRODUCT, brand
    if "total product revenue" in lower or "total revenue" in lower or "consolidated revenue" in lower or "net sales" in lower:
        return GuidanceScopeKind.COMPANY, label
    if "segment revenue" in lower:
        return GuidanceScopeKind.SEGMENT, label
    if "product revenue" in lower and "total product revenue" not in lower:
        return GuidanceScopeKind.PRODUCT, label
    prefix = re.split(r"[.;:•|\n\r]", prefix)[-1].strip()
    if _PRODUCT_REVENUE_QUALIFIER.search(prefix):
        return GuidanceScopeKind.PRODUCT, prefix
    segment_match = _SEGMENT_REVENUE_QUALIFIER.search(prefix)
    if segment_match:
        return GuidanceScopeKind.SEGMENT, segment_match.group(0).strip()
    return GuidanceScopeKind.COMPANY, None''',
    )

    value_helpers = r'''def _simple_to_from_value_pair(
    clause: str,
    mention,
) -> tuple[_ValueBinding | None, _ValueBinding | None, GuidanceAction]:
    if mention.metric not in {
        GuidanceMetric.REVENUE,
        GuidanceMetric.EBITDA,
        GuidanceMetric.FCF,
        GuidanceMetric.EPS,
    }:
        return None, None, GuidanceAction.NONE
    match = _SIMPLE_TO_FROM.search(clause)
    if not match:
        return None, None, GuidanceAction.NONE
    between = clause[match.end("new"):match.start("old")]
    if re.search(r"\b(?:to|through|and)\s+\$?\s*\d", between, re.I):
        return None, None, GuidanceAction.NONE
    common_scale = match.group("snew") or match.group("sold")
    has_dollar = bool(match.group("dnew") or match.group("dold"))
    new_unit = _unit_from_scale(match.group("snew") or common_scale, mention.metric, dollar=has_dollar)
    old_unit = _unit_from_scale(match.group("sold") or common_scale, mention.metric, dollar=has_dollar)
    if new_unit is GuidanceUnit.UNKNOWN or old_unit is GuidanceUnit.UNKNOWN or new_unit is not old_unit:
        return None, None, GuidanceAction.NONE
    new = float(match.group("new").replace(",", ""))
    old = float(match.group("old").replace(",", ""))
    current = _ValueBinding(
        new,
        new,
        new_unit,
        GuidanceValueKind.ABSOLUTE_LEVEL,
        match.group("new"),
        match.start("new"),
        match.end("new"),
    )
    prior = _ValueBinding(
        old,
        old,
        old_unit,
        GuidanceValueKind.ABSOLUTE_LEVEL,
        match.group("old"),
        match.start("old"),
        match.end("old"),
    )
    action = GuidanceAction.NONE
    if new < old:
        action = GuidanceAction.LOWER
    elif new > old:
        action = GuidanceAction.RAISE
    return current, prior, action


def _breakeven_value(clause: str, mention) -> _ValueBinding | None:
    if mention.metric not in {GuidanceMetric.EBITDA, GuidanceMetric.FCF}:
        return None
    match = _BREAKEVEN_TO_MONEY.search(clause)
    if not match:
        return None
    has_dollar = bool(match.group("d"))
    unit = _unit_from_scale(match.group("scale"), mention.metric, dollar=has_dollar)
    if unit is GuidanceUnit.UNKNOWN:
        return None
    high = float(match.group("high").replace(",", ""))
    return _ValueBinding(
        0.0,
        high,
        unit,
        GuidanceValueKind.ABSOLUTE_LEVEL,
        match.group(0),
        match.start(),
        match.end(),
    )


def _bind_metric_value(clause: str, mention, anchor: int) -> _ValueBinding | None:
    preceding = _bind_value(clause[:anchor], mention, anchor)
    if preceding is not None and preceding.end <= anchor:
        gap = anchor - preceding.end
        bridge = clause[preceding.end:anchor]
        before_value = clause[max(0, preceding.start - 50):preceding.start]
        if (
            gap <= 40
            and not re.search(r"[.;•]", bridge)
            and not re.search(r"\b(?:previously|prior|from)\b", before_value, re.I)
        ):
            return preceding
    return _bind_value(clause, mention, anchor)


'''
    if "def _simple_to_from_value_pair(" not in text:
        target = "def _directional_value_pair("
        pos = text.find(target)
        if pos < 0:
            raise RuntimeError("directional value function not found")
        text = text[:pos] + value_helpers + text[pos:]

    old_value = '''            previous_now_value, previous_now_prior = _previous_now_value_pair(clause, mention)
            directional_value, directional_prior = _directional_value_pair(clause, anchor, mention, local_action)
            value = previous_now_value or directional_value or _bind_value(clause, mention, anchor)
            explicit_prior = previous_now_prior or directional_prior
'''
    new_value = '''            previous_now_value, previous_now_prior = _previous_now_value_pair(clause, mention)
            to_from_value, to_from_prior, inferred_action = _simple_to_from_value_pair(clause, mention)
            if local_action is GuidanceAction.NONE and inferred_action is not GuidanceAction.NONE:
                local_action = inferred_action
            directional_value, directional_prior = _directional_value_pair(clause, anchor, mention, local_action)
            breakeven_value = _breakeven_value(clause, mention)
            value = previous_now_value or to_from_value or directional_value or breakeven_value or _bind_metric_value(clause, mention, anchor)
            explicit_prior = previous_now_prior or to_from_prior or directional_prior
'''
    text = replace_once(text, old_value, new_value, "semantic value binding stack")

    old_period = '''            period = _canonical_period_binding(clause, anchor, mention)
            if period is None and role is GuidanceFactRole.QUOTED_PRIOR:
                period = _unique_explicit_period_from_segment(segment)
            if period is None:
'''
    new_period = '''            period = _canonical_period_binding(clause, anchor, mention)
            if period is None:
                period = _section_period_binding(segment, mention)
            if period is None and role is GuidanceFactRole.QUOTED_PRIOR:
                period = _unique_explicit_period_from_segment(segment)
            if period is None:
'''
    text = replace_once(text, old_period, new_period, "section period fallback")

    old_shadow = '''            if fact.low == other.low and fact.high == other.high:
                remove.add(i)
                rejected.append(
                    {
                        "reason": "unscaled_shadow_fragment",
                        "metric": fact.metric.value,
                        "period": fact.fiscal_period,
                        "value": [fact.low, fact.high],
                    }
                )
                break
'''
    new_shadow = '''            exact_shadow = fact.low == other.low and fact.high == other.high
            endpoint_shadow = (
                fact.low == fact.high
                and other.low is not None
                and other.high is not None
                and (fact.low == other.low or fact.low == other.high)
            )
            if exact_shadow or endpoint_shadow:
                remove.add(i)
                rejected.append(
                    {
                        "reason": "unscaled_shadow_fragment",
                        "metric": fact.metric.value,
                        "period": fact.fiscal_period,
                        "value": [fact.low, fact.high],
                    }
                )
                break
'''
    text = replace_once(text, old_shadow, new_shadow, "raw endpoint scale shadow")

    text = replace_once(
        text,
        '"raw_document_extractor": "guidance-canonical-raw-v5"',
        '"raw_document_extractor": "guidance-canonical-raw-v6"',
        "raw extractor version",
    )

    path.write_text(text)


def patch_tests() -> None:
    path = ROOT / "backend/tests/test_guidance_raw_canonical_extractor.py"
    text = path.read_text()
    marker = "def test_semantic_v6_compact_table_value_precedes_metric():"
    if marker in text:
        return
    text += r'''


def test_semantic_v6_compact_table_value_precedes_metric():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "TABLE2",
            "Raised full-year 2025 guidance to: $452 - $458 million revenue; "
            "$138.5 - $141.5 million Adjusted EBITDA.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    ebitda = [fact for fact in extraction.facts if fact.metric.value == "ebitda"]
    assert any((fact.low, fact.high) == (452.0, 458.0) for fact in revenue)
    assert any((fact.low, fact.high) == (138.5, 141.5) for fact in ebitda)
    assert all((fact.low, fact.high) != (452.0, 458.0) for fact in ebitda)


def test_semantic_v6_results_before_guidance_heading_do_not_leak():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "RESULTS2",
            "Adjusted EBITDA of $102.6 million, up 11.5% YoY. "
            "Raising 2025 Guidance (all comparisons against the full year 2024, unless otherwise noted). "
            "Revenue range of $2.20 billion to $2.26 billion.",
        )
    )
    ebitda = [fact for fact in extraction.facts if fact.metric.value == "ebitda"]
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert all(fact.low != 102.6 for fact in ebitda)
    assert any(fact.fiscal_period == "FY2025" and (fact.low, fact.high) == (2.20, 2.26) for fact in revenue)
    assert all(fact.fiscal_period != "FY2024" for fact in revenue)


def test_semantic_v6_preliminary_actual_does_not_inherit_next_year_guidance():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "PRELIM",
            "Full year 2025 preliminary unaudited revenue was approximately $860 million. "
            "Initial 2026 revenue guidance established at $950 million to $990 million.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert any(fact.fiscal_period == "FY2026" and (fact.low, fact.high) == (950.0, 990.0) for fact in revenue)
    assert all(fact.low != 860.0 for fact in revenue)


def test_semantic_v6_fiscal_year_then_quarter_word_order():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "QORDER",
            "Fiscal 2026 Third Quarter Outlook. HPE estimates revenue to be $11.5 billion to $12.1 billion.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert any(fact.fiscal_period == "Q3FY2026" and (fact.low, fact.high) == (11.5, 12.1) for fact in revenue)


def test_semantic_v6_branded_net_sales_are_not_company_scope():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "BRAND",
            "2026 ARCALYST net sales guidance is expected to be between $980 million and $995 million.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert revenue
    assert all(fact.scope_kind is not GuidanceScopeKind.COMPANY for fact in revenue)


def test_semantic_v6_scale_shadow_single_endpoint_is_suppressed():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "SCALE2",
            "For full year 2026, we are raising our revenue guidance to between $8.150 - $8.158 billion.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert any((fact.low, fact.high, fact.unit.value) == (8.15, 8.158, "USD_BILLION") for fact in revenue)
    assert all(not (fact.low == fact.high == 8.15 and fact.unit.value == "USD") for fact in revenue)
    assert all(not (fact.low == fact.high == 8.158 and fact.unit.value == "USD") for fact in revenue)


def test_semantic_v6_to_from_guidance_creates_current_and_prior_roles():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "TOFROM",
            "FY 2026 GAAP EPS guidance to 'at least $6.52' from previous estimate of 'at least $8.36'.",
        )
    )
    eps = [fact for fact in extraction.facts if fact.metric.value == "eps"]
    current = [fact for fact in eps if fact.role is GuidanceFactRole.CURRENT]
    prior = [fact for fact in eps if fact.role is GuidanceFactRole.QUOTED_PRIOR]
    assert any(fact.low == 6.52 for fact in current)
    assert any(fact.low == 8.36 for fact in prior)
    assert any(fact.low == 6.52 and fact.explicit_action is GuidanceAction.LOWER for fact in current)


def test_semantic_v6_breakeven_range_normalizes_to_zero():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "BREAKEVEN",
            "FY 2025 Adjusted EBITDA is expected to be between breakeven and $10 million.",
        )
    )
    ebitda = [fact for fact in extraction.facts if fact.metric.value == "ebitda"]
    assert any((fact.low, fact.high, fact.unit.value) == (0.0, 10.0, "USD_MILLION") for fact in ebitda)


def test_semantic_v6_section_heading_supplies_missing_bullet_period():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "SECTION",
            "Full Year 2026 Guidance\n"
            "Increasing revenue guidance to a range of $1.811 billion to $1.824 billion.\n"
            "Increasing adjusted EBITDA guidance to a range of $404.1 million to $406.3 million.\n"
            "Increasing free cash flow guidance to a range of $254.8 million to $255.8 million.",
        )
    )
    fcf = [fact for fact in extraction.facts if fact.metric.value == "fcf"]
    assert any(fact.fiscal_period == "FY2026" and (fact.low, fact.high) == (254.8, 255.8) for fact in fcf)
'''
    path.write_text(text)


patch_canonical_extractor()
patch_tests()
