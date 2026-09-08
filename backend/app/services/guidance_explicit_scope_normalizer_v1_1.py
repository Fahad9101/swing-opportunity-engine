"""Normalize explicit guidance scopes without changing investment rules.

Only forward clauses and unambiguous column headers enter this path. Historical
comparisons, adjacent metrics and quarter/annual columns cannot supply scope.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from app.domain.soe_v1_1 import (
    ExtractionMethod,
    GuidanceMetric,
    GuidanceMetricRecord,
    SourceDocument,
)
from app.services.fact_extraction_service import html_to_text

_NUM = r"\d+(?:\.\d+)?"
_RANGE = rf"\$\s*({_NUM})\s*(million|billion)?\s*(?:to|and|[-–—])\s*\$?\s*({_NUM})\s*(million|billion)?"
_LABEL = r"(?:(?:non[- ]GAAP|adjusted|GAAP)\s+)?(?:diluted\s+)?(?:EPS|(?:net income|earnings) per (?:diluted )?share(?:, diluted)?|EBITDA|(?:consolidated |total )?(?:net sales|revenue))"
_ROW = re.compile(
    rf"(?P<label>{_LABEL})\s+(?:(?:is|are)\s+)?(?:now\s+)?(?:expected\s+to\s+(?:be\s+in\s+the\s+range\s+of|range\s+between|be\s+between)|(?:to\s+)?range\s+between|to\s+be\s+in\s+the\s+range\s+of|to\s+be\s+between|between|of|(?:guidance\s+)?(?:raised|increased)\s+to)\s+{_RANGE}",
    re.I,
)
_ANNUAL = re.compile(
    r"\b(?:(?:full[- ]year|fiscal year)\s+(20\d{2})|(20\d{2})\s+full year)\b", re.I
)
_QUARTER = re.compile(
    r"\b(first|second|third|fourth)\s+(?:fiscal\s+)?quarter(?:\s+ending\s+[A-Za-z]+\s+\d{1,2},|\s+(?:of\s+)?(?:fiscal year\s+)?)\s*(20\d{2})\b",
    re.I,
)
_END = re.compile(
    r"\b(?:Conference Call|About [A-Z]|Forward[- ]Looking|Non-GAAP Financial Measures|Financial Results|Financial Highlights)\b"
)
_QUARTERS = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def _record(document, rules_hash, period, label, low, high, scale, evidence):
    label = label.lower()
    metric = (
        GuidanceMetric.EPS
        if re.search(r"eps|per .*share", label)
        else GuidanceMetric.EBITDA if "ebitda" in label else GuidanceMetric.REVENUE
    )
    if "operating margin" in label:
        metric = GuidanceMetric.OPERATING_MARGIN
    basis = (
        "ADJUSTED"
        if re.search(r"non[- ]gaap|adjusted", label)
        else "GAAP" if "gaap" in label else "UNSPECIFIED"
    )
    multiplier = (
        1
        if metric is GuidanceMetric.EPS
        else {"million": 1e6, "billion": 1e9}.get(scale, 1)
    )
    if metric is GuidanceMetric.OPERATING_MARGIN:
        multiplier = 0.01
    unit = (
        "fraction"
        if metric is GuidanceMetric.OPERATING_MARGIN
        else "USD/share" if metric is GuidanceMetric.EPS else "USD"
    )
    return GuidanceMetricRecord(
        rules_hash=rules_hash,
        ticker=document.ticker,
        fiscal_period=period,
        metric=metric,
        accounting_basis=basis,
        low=float(low) * multiplier,
        high=float(high) * multiplier,
        unit=unit,
        source=document.source,
        source_url=document.source_url,
        source_accession=document.accession,
        source_timestamp=document.source_timestamp,
        as_of=document.source_timestamp,
        fetched_at=document.fetched_at,
        stale=document.stale,
        verified=True,
        extraction_method=ExtractionMethod.STRUCTURED,
        evidence_span=evidence,
        source_document_hash=document.content_hash,
    )


class _InlineText(HTMLParser):
    """Keep numeric text split by inline styling, but separate block/table cells."""

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.boundaries: list[tuple[str, bool]] = []
        self.hidden = 0

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        style = dict(attrs).get("style") or ""
        boundary = tag not in {
            "span",
            "font",
            "b",
            "strong",
            "i",
            "em",
            "u",
            "a",
        } or bool(re.search(r"display\s*:\s*(?:block|inline-block|table)", style, re.I))
        if boundary:
            self.parts.append(" ")
        if tag not in {"br", "hr", "img", "input", "meta", "link"}:
            self.boundaries.append((tag, boundary))

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        for index in range(len(self.boundaries) - 1, -1, -1):
            if self.boundaries[index][0] == tag:
                if self.boundaries[index][1]:
                    self.parts.append(" ")
                del self.boundaries[index:]
                break


def _scope_text(content):
    if "<" not in content or ">" not in content:
        return re.sub(r"\s+", " ", html_to_text(content)).strip()
    parser = _InlineText()
    parser.feed(content)
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def normalize_explicit_guidance_scopes(
    document: SourceDocument, *, rules_hash: str
) -> list[GuidanceMetricRecord]:
    text = _scope_text(document.content or "")
    records = []
    scopes = [
        (m.start(), m.end(), f"FY{m.group(1) or m.group(2)}", m.group())
        for m in _ANNUAL.finditer(text)
    ]
    for match in _QUARTER.finditer(text):
        year = match.group(2)
        if "ending" in match.group().lower():
            # A calendar end date does not identify a fiscal year. Require a
            # matching explicit quarter/FY statement elsewhere in this filing.
            corroboration = re.findall(
                rf"\b{match.group(1)} quarter of fiscal year (20\d{{2}})\b", text, re.I
            )
            if len(set(corroboration)) != 1:
                continue
            year = corroboration[0]
        scopes.append(
            (
                match.start(),
                match.end(),
                f"Q{_QUARTERS[match.group(1).lower()]}FY{year}",
                match.group(),
            )
        )
    scopes.sort()
    for index, (start, end, period, header) in enumerate(scopes):
        # A reported-results year is never sufficient to open a guidance scope.
        if not re.search(
            r"\b(?:guidance|outlook|expects?)\b",
            text[max(0, start - 80) : end + 130],
            re.I,
        ):
            continue
        stop = min(
            len(text),
            end + 1400,
            scopes[index + 1][0] if index + 1 < len(scopes) else len(text),
        )
        section = text[end:stop]
        boundary = _END.search(section)
        if boundary:
            section = section[: boundary.start()]
        for row in _ROW.finditer(section):
            prefix = section[max(0, row.start() - 35) : row.start()]
            if re.search(
                r"(?:product|segment|subscription|services?)\s+$", prefix, re.I
            ):
                continue
            label = row.group("label")
            low, scale1, high, scale2 = row.group(2, 3, 4, 5)
            if float(low) > float(high) or (
                scale1 and scale2 and scale1.lower() != scale2.lower()
            ):
                continue
            # 'between/of' alone must be supported by an explicit forward verb
            # in the header or immediate clause, not a distant earnings headline.
            leading_action = re.search(
                r"(?:expects?|guidance|outlook)[^.!?]{0,60}$",
                text[max(0, start - 80) : start],
                re.I,
            )
            forward_context = " ".join(
                (
                    header,
                    row.group(),
                    prefix,
                    leading_action.group() if leading_action else "",
                )
            )
            if not re.search(
                r"expected|guidance|outlook|expects?", forward_context, re.I
            ):
                continue
            records.append(
                _record(
                    document,
                    rules_hash,
                    period,
                    label,
                    low,
                    high,
                    (scale2 or scale1 or "").lower(),
                    f"{period} guidance; {header}; {row.group()}",
                )
            )

        # Explicitly stated margin corresponding to the forward income range.
        for margin in re.finditer(
            rf"Non-GAAP operating income between {_RANGE}, representing a "
            rf"(non-GAAP operating margin) of ({_NUM})% at the midpoint of the range",
            section,
            re.I,
        ):
            records.append(
                _record(
                    document,
                    rules_hash,
                    period,
                    margin[5],
                    margin[6],
                    margin[6],
                    "fraction",
                    f"{period} guidance; {header}; {margin.group()}",
                )
            )

    # Single metric point guidance with its own explicit year. Do not borrow the
    # following reported fiscal year (e.g. an annual-results highlights heading).
    for m in re.finditer(
        rf"\b(20\d{{2}})\s+(revenue)\s+guidance\s+of\s+\$({_NUM})\s+(million|billion)\b(?!\s*(?:to|and|[-–—])\s*\$?\d)",
        text,
        re.I,
    ):
        records.append(
            _record(
                document,
                rules_hash,
                f"FY{m[1]}",
                m[2],
                m[3],
                m[3],
                m[4].lower(),
                m.group(),
            )
        )

    # Quarter + annual table with an explicit shared unit. Keep both columns.
    header = re.compile(
        r"Metric \(in millions, except per share amounts\) FY (20\d{2}) Q([1-4]) Guidance FY \1 Guidance",
        re.I,
    )
    rows = re.compile(rf"(?P<label>{_LABEL})\s+{_RANGE}\s+{_RANGE}", re.I)
    for h in header.finditer(text):
        section = text[h.end() : h.end() + 900]
        for m in rows.finditer(section):
            if m.start() and re.search(
                r"(?:product|segment|subscription)\s+$", section[: m.start()], re.I
            ):
                continue
            for period, lo, hi in [
                (f"Q{h[2]}FY{h[1]}", m[2], m[4]),
                (f"FY{h[1]}", m[6], m[8]),
            ]:
                if float(lo) <= float(hi):
                    records.append(
                        _record(
                            document,
                            rules_hash,
                            period,
                            m["label"],
                            lo,
                            hi,
                            "million",
                            f'{period} guidance (USD millions except per share); {m["label"]} ${lo} - ${hi}',
                        )
                    )

    # Multi-year presentation: reported actual, prior, updated, growth, next FY.
    # Require the entire column layout; only the current two FY columns emit.
    hpat = re.compile(
        r"Updated Fiscal Year (20\d{2}) and (20\d{2}) Guidance.{0,150}?\(\$ in millions, except percentages\) (20\d{2}) As Reported \1 \2\(1\) Prior Guidance as of [A-Za-z]+ \d{1,2}, \1 Updated Guidance Δ YoY Growth Guidance Δ YoY Growth",
        re.I,
    )
    for h in hpat.finditer(text):
        if int(h[2]) != int(h[1]) + 1 or int(h[3]) != int(h[1]) - 1:
            continue
        for m in re.finditer(
            rf"(Revenue|Adjusted EBITDA)\s+\${_NUM}\s+{_RANGE}\s+{_RANGE}\s+\+{_NUM}%\s+~?{_RANGE}",
            text[h.end() : h.end() + 650],
            re.I,
        ):
            for period, lo, hi in [
                (f"FY{h[1]}", m[6], m[8]),
                (f"FY{h[2]}", m[10], m[12]),
            ]:
                if float(lo) <= float(hi):
                    records.append(
                        _record(
                            document,
                            rules_hash,
                            period,
                            m[1],
                            lo,
                            hi,
                            "million",
                            f"{period} guidance (USD millions); {m[1]} ${lo} - ${hi}",
                        )
                    )
    unique = {}
    for r in records:
        unique[(r.metric, r.fiscal_period, r.accounting_basis, r.low, r.high)] = r
    return list(unique.values())
