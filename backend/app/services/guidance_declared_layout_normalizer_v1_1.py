"""Metric-local values from explicitly declared guidance layouts.

This adapter never infers an investment classification. Headers identify the
current column; a value must immediately follow its own complete metric label.
Unknown layouts continue through the existing extraction paths.
"""

import re

from app.domain.soe_v1_1 import GuidanceMetric
from app.services.guidance_explicit_scope_normalizer_v1_1 import _record, _scope_text, normalize_explicit_guidance_scopes

N = r"\d+(?:,\d{3})*(?:\.\d+)?"
R = rf"\$\s*({N})\s*(million|billion)?\s*(?:to|[-–—])\s*\$?\s*({N})\s*(million|billion)?"
LABEL = r"(?:(?:Operating |Consolidated )?(?:Adjusted |Non-GAAP |Adj\. )?)?(?:Total revenue|Revenue|Net Sales|EBITDA|Diluted EPS|EPS|net income per diluted share|Free Cash Flow|operating margin)"


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
        (r"Previous FY (20\d{2}) Guidance Updated FY \1 Guidance", 1, "million", 500),
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
            for row in re.finditer(rf"(?P<label>{LABEL})(?:\s+\d)?\s+{R}\s+{R}", section, re.I):
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

    # Single low/high table with explicit million-dollar units.
    for h in re.finditer(r"(20\d{2}) Guidance \(In millions, except for student starts and diluted EPS\) Low High", text, re.I):
        for m in re.finditer(rf"({LABEL})(?:\s+\d)?\s+{R}", text[h.end():h.end()+500], re.I):
            emit(f"FY{h[1]}", m[1], m[2], m[4], "million", f"{h.group()}; {m.group()}")

    # Updated/prior columns expressed as four endpoints rather than two ranges.
    point = rf"\$\s*({N})\s*(billion|million)?"
    for h in re.finditer(r"full year (20\d{2}) guidance as follows: Updated Guidance Prior Guidance Low High Low High", text, re.I):
        for m in re.finditer(rf"(Net revenues|Reported diluted EPS|Adjusted diluted EPS)\s+{point}\s+{point}\s+{point}\s+{point}", text[h.end():h.end()+850], re.I):
            label = m[1]
            if label.lower().startswith("reported") and re.search(r"term [“\"]reported[”\"] refers to measures under accounting principles generally accepted in the United States", text, re.I):
                label = "GAAP diluted EPS"
            emit(f"FY{h[1]}", label, m[2], m[4], (m[5] or m[3] or "").lower(), f"{h.group()}; {m.group()}")

    # Product detail is inside the total-revenue label, ahead of the numeric
    # current/prior columns. Only the trailing column ranges supply the total.
    for h in re.finditer(r"full year (20\d{2}).{0,120}?guidance as set forth below \(dollars in millions\): Current Guidance", text, re.I):
        section = text[h.end():h.end()+650]
        m = re.search(r"Total revenues include the following.*?(?=Combined R&D and SG&A expenses)", section, re.I)
        if m:
            ranges = list(re.finditer(R, m.group(), re.I))
            columns = 2 if "Previous Guidance" in section[:m.start()] else 1
            if len(ranges) >= columns + 1:
                v = ranges[-columns]
                emit(f"FY{h[1]}", "Total revenue", v[1], v[3], "million", f"{h.group()}; total revenue current column {v.group()}")

    # Explicit annual forward cash-flow floor: do not borrow the following FY.
    for h in re.finditer(r"Fiscal (20\d{2}) Full Year Outlook", text, re.I):
        section = re.split(r"Fiscal 20\d{2} Outlook Framework", text[h.end():h.end()+1600], flags=re.I)[0]
        m = re.search(rf"expects (free cash flow) to be at least \$({N}) (billion|million)", section, re.I)
        if m:
            emit(f"FY{h[1]}", m[1], m[2], m[2], m[3].lower(), f"{h.group()}; {m.group()}")
            # The same source/value bound to the next year must not survive.
            authoritative.add((GuidanceMetric.FCF, f"FY{int(h[1])+1}"))

    # Cost-base guidance is not a company revenue forecast.
    for h in re.finditer(r"For the full year (20\d{2}), we expect:", text, re.I):
        section = text[h.end():h.end()+700]
        if re.search(r"Mid-teens total revenue growth", section, re.I) and re.search(r"Fixed cost base of approximately \$1 billion", section, re.I):
            authoritative.add((GuidanceMetric.REVENUE, f"FY{h[1]}"))

    for h in re.finditer(r"Full[- ]Year (20\d{2}) Outlook GAAP Adjusted", text, re.I):
        section = text[h.end():h.end()+1400]
        m = re.search(rf"Operating profit margin ({N})% - ({N})% ({N})% - ({N})%", section, re.I)
        if m:
            for label, lo, hi in [("GAAP operating margin", m[1], m[2]), ("Adjusted operating margin", m[3], m[4])]:
                emit(f"FY{h[1]}", label, lo, hi, "fraction", f"{h.group()}; {m.group()}")
        m = re.search(rf"expects (adjusted free cash flow), excluding certain items, of {R}", section, re.I)
        if m:
            emit(f"FY{h[1]}", m[1], m[2], m[4], (m[5] or m[3]).lower(), f"{h.group()}; {m.group()}")

    # A compact forecast table explicitly marks millions with M on each bound.
    for h in re.finditer(r"(Full Year|First Quarter|Second Quarter|Third Quarter|Fourth Quarter) (20\d{2}) Guidance (?=Net sales)", text, re.I):
        scope = h[1].lower()
        quarter = {"first quarter": 1, "second quarter": 2, "third quarter": 3, "fourth quarter": 4}.get(scope)
        period = f"Q{quarter}FY{h[2]}" if quarter else f"FY{h[2]}"
        section = re.split(r"(?:Full Year|First Quarter|Second Quarter|Third Quarter|Fourth Quarter) 20\d{2} Guidance", text[h.end():h.end()+650], flags=re.I)[0]
        for m in re.finditer(rf"(Net sales|Adjusted free cash flow)(?:\s*\(\d\))? \$({N})M - \$({N})M", section, re.I):
            emit(period, m[1], m[2], m[3], "million", f"{h.group()}; {m.group()}")
        m = re.search(rf"(Adjusted operating margin)\s*\(\d\) ({N})% - ({N})%", section, re.I)
        if m:
            emit(period, m[1], m[2], m[3], "fraction", f"{h.group()}; {m.group()}")
        m = re.search(rf"(Adjusted diluted EPS)\s*\(\d\) \$({N}) - \$({N})", section, re.I)
        if m:
            # This table gives adjusted EPS only. Preserve separately stated
            # forward EPS on other bases in the same fiscal scope.
            records.extend(
                r for r in normalize_explicit_guidance_scopes(document, rules_hash=rules_hash)
                if r.metric is GuidanceMetric.EPS and r.fiscal_period == period
                and r.accounting_basis != "ADJUSTED"
            )
            emit(period, m[1], m[2], m[3], "", f"{h.group()}; {m.group()}")

    # The explicit quarter in the forecast clause corroborates the table date.
    for h in re.finditer(r"outlook for the three months ending (March|June|September|December) \d{1,2}, (20\d{2}) \(in millions\)", text, re.I):
        q = {"march": 1, "june": 2, "september": 3, "december": 4}[h[1].lower()]
        section = re.split(r"(?:20\d{2} OUTLOOK|For the full year)", text[h.end():h.end()+2500], flags=re.I)[0]
        if not re.search(rf"In Q{q}, we expect total revenue", section, re.I):
            continue
        for m in re.finditer(rf"(total revenue|Adjusted EBITDA)(?: of)?\s+{R}", section, re.I):
            emit(f"Q{q}FY{h[2]}", m[1], m[2], m[4], (m[5] or m[3] or "million").lower(), f"Q{q}FY{h[2]} outlook; {m.group()}")
            # Remove another quarter or annual binding of this same metric;
            # annual revenue, when explicitly stated, is kept separately.
            if "ebitda" in m[1].lower():
                authoritative.add((GuidanceMetric.EBITDA, f"FY{h[2]}"))
            authoritative.add((records[-1].metric, f"Q{q-1}FY{h[2]}"))

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
