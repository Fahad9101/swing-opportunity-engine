"""Metric-local values from explicitly declared guidance layouts.

This adapter never infers an investment classification. Headers identify the
current column; a value must immediately follow its own complete metric label.
Unknown layouts continue through the existing extraction paths.
"""

import re

from app.domain.soe_v1_1 import GuidanceMetric
from app.services.guidance_explicit_scope_normalizer_v1_1 import _record, _scope_text

N = r"\d+(?:,\d{3})*(?:\.\d+)?"
R = rf"\$\s*({N})\s*(million|billion)?\s*(?:to|[-–—])\s*\$?\s*({N})\s*(million|billion)?"
LABEL = r"(?:(?:Operating |Consolidated )?(?:Adjusted |Non-GAAP |Adj\. )?)?(?:Total revenue|Revenue|Net Sales|EBITDA|EPS|net income per diluted share|Free Cash Flow|operating margin)"


def normalize_declared_layouts(document, *, rules_hash):
    """Return records and metric/period keys superseding unsafe flattened rows."""
    text = _scope_text(document.content or "")
    records = []
    authoritative = set()

    def emit(period, label, low, high, scale, evidence):
        if float(low.replace(",", "")) > float(high.replace(",", "")):
            return
        record = _record(
            document, rules_hash, period, label, low, high, scale, evidence
        )
        records.append(record)
        authoritative.add((record.metric, period))

    # These complete headers explicitly state column order and fiscal scope.
    layouts = [
        (
            r"Guidance Item Current Guidance for Full-Year (20\d{2})\s*(?:\d\s+)?Prior Guidance for Full-Year \1",
            0,
            "",
            1250,
        ),
        (
            r"Current Guidance Fiscal (20\d{2}) Prior Guidance Fiscal \1\* Guidance Change at Midpoint\*\*",
            0,
            "million",
            1750,
        ),
        (
            r"(20\d{2}) Guidance \(In millions, except per share amounts\) Previous Guidance \([A-Za-z]+ \d{1,2}, \1\) Revised Guidance \([A-Za-z]+ \d{1,2}, \1\)",
            1,
            "million",
            450,
        ),
    ]
    for pattern, column, scale, length in layouts:
        for header in re.finditer(pattern, text, re.I):
            period = f"FY{header[1]}"
            section = text[header.end() : header.end() + length]
            for row in re.finditer(rf"(?P<label>{LABEL})\s+{R}\s+{R}", section, re.I):
                prefix = section[max(0, row.start() - 20) : row.start()]
                if re.search(r"(?:subscription|segment|product)\s+$", prefix, re.I):
                    continue
                offset = column * 4
                emit(
                    period,
                    row["label"],
                    row[2 + offset],
                    row[4 + offset],
                    (row[5 + offset] or row[3 + offset] or scale).lower(),
                    f"{period} guidance; {header.group()}; {row.group()}",
                )
            # Percentage points belong only to their own operating-margin row.
            for row in re.finditer(
                rf"(Non-GAAP operating margin)\s+({N})%\s+({N})%", section, re.I
            ):
                emit(
                    period,
                    row[1],
                    row[2],
                    row[2],
                    "fraction",
                    f"{period} guidance; {row.group()}",
                )
            # 'Adjusted EBITDA Expense' is an expense, never EBITDA earnings.
            if re.search(r"Adjusted EBITDA Expense\s+\$", section, re.I):
                authoritative.add((GuidanceMetric.EBITDA, period))

    # Actual and guidance columns in a presentation, with row-specific units.
    for h in re.finditer(
        r"Fiscal Year (20\d{2}) Guidance\s+\d+\s+Key Metric FY (20\d{2}) FY \1 Y\s*-\s*o-?\s*-?y Change",
        text,
        re.I,
    ):
        if int(h[1]) != int(h[2]) + 1:
            continue
        for row in re.finditer(
            rf"(Net Sales|Adj\. EBITDA) \(in Millions\)\s+\${N}\s+{R}",
            text[h.end() : h.end() + 500],
            re.I,
        ):
            emit(
                f"FY{h[1]}",
                row[1],
                row[2],
                row[4],
                "million",
                f"FY{h[1]} guidance in millions; {row.group()}",
            )

    # A forward point with an explicit year and metric (not a reported result).
    for m in re.finditer(
        rf"expect (20\d{{2}}) (Adjusted EBITDA) to be ~?\$({N}) (million|billion)\b",
        text,
        re.I,
    ):
        emit(f"FY{m[1]}", m[2], m[3], m[3], m[4].lower(), m.group())

    # Stated operating margin accompanying the annual outlook. Gross margin
    # and the company's pro-forma EPS basis are not substituted for this metric.
    for h in re.finditer(
        r"(?:Fiscal Year (20\d{2}) Guidance:|(20\d{2}) Fiscal Year Guidance\s*\(\d\)\s*:)",
        text,
        re.I,
    ):
        section = text[h.end() : h.end() + 700]
        section = re.split(
            r"Dividend Recommendation|Conference Call", section, flags=re.I
        )[0]
        if not re.search(r"We (?:now anticipate|expect)", section, re.I):
            continue
        m = re.search(
            rf"based (?:upon|on) gross margin of {N}%, (operating margin) of ({N})%",
            section,
            re.I,
        )
        if m:
            emit(
                f"FY{h[1] or h[2]}",
                m[1],
                m[2],
                m[2],
                "fraction",
                f"{h.group()} {m.group()}",
            )
        definition = re.search(
            r"non-GAAP financial measures: [^.!?]{0,100}?pro forma net income \(earnings\) per share",
            text,
            re.I,
        )
        eps = re.search(rf"pro forma EPS (?:to be|of) \$({N})\b", section, re.I)
        if definition and eps:
            # The issuer explicitly defines this measure as non-GAAP. Do not
            # infer that accounting basis from 'pro forma' alone.
            emit(
                f"FY{h[1] or h[2]}",
                "Non-GAAP EPS",
                eps[1],
                eps[1],
                "",
                f"{h.group()} {eps.group()}; {definition.group()}",
            )

    # The release explicitly separates the GAAP and adjusted EPS lower bounds.
    for m in re.finditer(
        rf"FY (20\d{{2}}) GAAP EPS guidance of 'at least \$({N})'; 'at least \$({N})' on an Adjusted basis",
        text,
        re.I,
    ):
        for label, value in [("GAAP EPS", m[2]), ("Adjusted EPS", m[3])]:
            emit(f"FY{m[1]}", label, value, value, "", m.group())

    return records, authoritative


def historical_republication_periods(document):
    """A source expressly declining reaffirmation supplies no new FY update."""
    text = _scope_text(document.content or "")
    return {
        f"FY{m[1]}"
        for m in re.finditer(
            r"Guidance provided as of [A-Za-z]+ \d{1,2}, (20\d{2}) and is neither being reaffirmed nor updated today",
            text,
            re.I,
        )
    }
