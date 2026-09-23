from __future__ import annotations

from typing import Any, Dict, List, Optional
import re


# ================================================================
# BASIC HELPERS
# ================================================================

def _clean_text(text: str) -> str:
    """Normalize extracted document text."""

    if not text:
        return ""

    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _build_evidence_record(
    file_name: str,
    document_type: str,
    field: str,
    value: Any,
    source_location: str,
    confidence: float,
    context: str,
) -> Dict[str, Any]:
    """Create a standardized evidence record."""

    return {
        "file_name": file_name,
        "document_type": document_type,
        "field": field,
        "value": value,
        "source_location": source_location,
        "confidence": round(confidence, 2),
        "context": context,
    }


def _extract_number(text: str) -> Optional[float]:
    """Extract the first numeric value from a string."""

    if not text:
        return None

    matches = re.findall(
        r"-?\d[\d,]*(?:\.\d+)?",
        text,
    )

    if not matches:
        return None

    try:
        return float(
            matches[0].replace(",", "")
        )
    except ValueError:
        return None


def _extract_last_number(text: str) -> Optional[float]:
    """Extract the last numeric value from a string."""

    if not text:
        return None

    matches = re.findall(
        r"-?\d[\d,]*(?:\.\d+)?",
        text,
    )

    if not matches:
        return None

    try:
        return float(
            matches[-1].replace(",", "")
        )
    except ValueError:
        return None


# ================================================================
# SPREADSHEET HELPERS
# ================================================================

def _find_pipe_rows(text: str) -> List[str]:
    """Extract pipe-separated spreadsheet rows."""

    return [
        line.strip()
        for line in text.splitlines()
        if "|" in line
    ]


def _row_matches(
    row: str,
    keywords: List[str],
) -> bool:
    """Check whether a spreadsheet row contains a keyword."""

    lowered = row.lower()

    return any(
        keyword.lower() in lowered
        for keyword in keywords
    )


def _extract_pipe_value(
    row: str,
) -> Optional[float]:
    """
    For rows such as:

        ARR (₹ Cr) | 5.4 | 10.2 | 18.9

    return the latest value: 18.9
    """

    return _extract_last_number(row)


def _extract_pipe_row_context(
    row: str,
) -> str:
    """Clean spreadsheet row for evidence display."""

    return " | ".join(
        part.strip()
        for part in row.split("|")
    )


# ================================================================
# SPREADSHEET EVIDENCE
# ================================================================

def _extract_spreadsheet_evidence(
    text: str,
    file_name: str,
    document_type: str,
) -> List[Dict[str, Any]]:
    """
    Extract evidence from Excel content represented as
    pipe-separated text.
    """

    evidence: List[Dict[str, Any]] = []

    rows = _find_pipe_rows(text)

    for row in rows:

        lowered = row.lower()

        # Ignore obvious header rows.
        if (
            lowered.startswith("sheet")
            or lowered.startswith("metric")
            or lowered.startswith("description")
        ):
            continue

        # --------------------------------------------------------
        # FINANCIAL MODEL
        # --------------------------------------------------------

        if document_type == "Financial Model":

            mappings = [
                (
                    "closing_cash",
                    ["closing cash"],
                ),
                (
                    "revenue",
                    ["revenue"],
                ),
                (
                    "active_customers",
                    ["active customers"],
                ),
                (
                    "arr",
                    ["arr"],
                ),
                (
                    "gross_margin",
                    ["gross margin"],
                ),
                (
                    "ebitda",
                    ["ebitda"],
                ),
                (
                    "ebitda_margin",
                    ["ebitda margin"],
                ),
                (
                    "net_profit",
                    ["net profit"],
                ),
                (
                    "churn",
                    ["churn"],
                ),
                (
                    "nrr",
                    ["nrr"],
                ),
                (
                    "cac",
                    ["cac"],
                ),
                (
                    "acv",
                    ["acv"],
                ),
                (
                    "monthly_burn",
                    ["monthly burn"],
                ),
            ]

            for field, keywords in mappings:

                if not _row_matches(
                    row,
                    keywords,
                ):
                    continue

                # Do not confuse EBITDA Margin with EBITDA.
                if (
                    field == "ebitda"
                    and "ebitda margin" in lowered
                ):
                    continue

                value = _extract_pipe_value(row)

                if value is None:
                    continue

                # Some Excel extracts store percentages as decimals:
                #
                # 1.18  -> 118%
                # 0.539 -> 53.9%
                #
                if field in {
                    "nrr",
                    "churn",
                    "gross_margin",
                }:
                    if abs(value) <= 2:
                        value *= 100

                if field == "active_customers":
                    value = int(value)

                evidence.append(
                    _build_evidence_record(
                        file_name=file_name,
                        document_type=document_type,
                        field=field,
                        value=value,
                        source_location=(
                            "Financial model "
                            "spreadsheet row"
                        ),
                        confidence=0.97,
                        context=(
                            _extract_pipe_row_context(
                                row
                            )
                        ),
                    )
                )

                break

        # --------------------------------------------------------
        # CUSTOMER / OPERATING METRICS
        # --------------------------------------------------------

        elif document_type == "Customer / Operating Metrics":

            mappings = [
                (
                    "active_customers",
                    ["active customers"],
                ),
                (
                    "total_arr",
                    ["arr", "total arr"],
                ),
                (
                    "churn",
                    ["churn"],
                ),
                (
                    "nrr",
                    ["nrr"],
                ),
                (
                    "cac",
                    ["cac"],
                ),
                (
                    "acv",
                    ["acv"],
                ),
            ]

            for field, keywords in mappings:

                if not _row_matches(
                    row,
                    keywords,
                ):
                    continue

                # Important:
                # Top 10 Customers ARR is concentration ARR,
                # not total company ARR.
                if (
                    field == "total_arr"
                    and (
                        "top 10" in lowered
                        or "top ten" in lowered
                        or "concentration" in lowered
                    )
                ):
                    continue

                value = _extract_pipe_value(row)

                if value is None:
                    continue

                if field == "active_customers":
                    value = int(value)

                if field in {
                    "nrr",
                    "churn",
                }:
                    if abs(value) <= 2:
                        value *= 100

                evidence.append(
                    _build_evidence_record(
                        file_name=file_name,
                        document_type=document_type,
                        field=field,
                        value=value,
                        source_location=(
                            "Customer metrics "
                            "spreadsheet row"
                        ),
                        confidence=0.97,
                        context=(
                            _extract_pipe_row_context(
                                row
                            )
                        ),
                    )
                )

                break

        # --------------------------------------------------------
        # CAP TABLE
        # --------------------------------------------------------

        elif document_type == "Cap Table":

            if not _row_matches(
                row,
                [
                    "founder ownership",
                    "founders ownership",
                ],
            ):
                continue

            value = _extract_pipe_value(row)

            if value is None:
                continue

            # Store ownership internally as decimal:
            # 60 -> 0.60
            if value > 1:
                value /= 100

            evidence.append(
                _build_evidence_record(
                    file_name=file_name,
                    document_type=document_type,
                    field="founder_ownership",
                    value=value,
                    source_location=(
                        "Cap table "
                        "spreadsheet row"
                    ),
                    confidence=0.98,
                    context=(
                        _extract_pipe_row_context(
                            row
                        )
                    ),
                )
            )

    return evidence


# ================================================================
# BANK STATEMENT
# ================================================================

def _extract_bank_statement_evidence(
    text: str,
    file_name: str,
    document_type: str,
) -> List[Dict[str, Any]]:

    evidence: List[Dict[str, Any]] = []

    patterns = {
        "opening_balance": [
            r"opening balance\s*[:\-]?\s*[₹Rs\.\s]*"
            r"([\d,]+(?:\.\d+)?)",
        ],
        "total_credits": [
            r"total credits?\s*[:\-]?\s*[₹Rs\.\s]*"
            r"([\d,]+(?:\.\d+)?)",
        ],
        "total_debits": [
            r"total debits?\s*[:\-]?\s*[₹Rs\.\s]*"
            r"([\d,]+(?:\.\d+)?)",
        ],
        "closing_balance": [
            r"closing balance\s*[:\-]?\s*[₹Rs\.\s]*"
            r"([\d,]+(?:\.\d+)?)",
        ],
    }

    for field, field_patterns in patterns.items():

        for pattern in field_patterns:

            for match in re.finditer(
                pattern,
                text,
                flags=re.IGNORECASE,
            ):

                value = _extract_number(
                    match.group(0)
                )

                if value is None:
                    continue

                start = max(
                    0,
                    match.start() - 120,
                )

                end = min(
                    len(text),
                    match.end() + 150,
                )

                evidence.append(
                    _build_evidence_record(
                        file_name=file_name,
                        document_type=document_type,
                        field=field,
                        value=value,
                        source_location=(
                            "Bank statement text"
                        ),
                        confidence=0.97,
                        context=text[
                            start:end
                        ].strip(),
                    )
                )

    return evidence


# ================================================================
# PRESENTATION HELPERS
# ================================================================

def _number_from_previous_lines(
    lines: List[str],
    label_index: int,
    search_distance: int = 2,
) -> Optional[float]:
    """
    Find a plain numeric line immediately preceding
    a label.

    Example:

        165
        Enterprise customers
    """

    candidates = []

    start = max(
        0,
        label_index - search_distance,
    )

    for i in range(
        start,
        label_index,
    ):

        line = lines[i].strip()

        match = re.fullmatch(
            r"\d[\d,]*(?:\.\d+)?",
            line,
        )

        if match:

            candidates.append(
                (
                    label_index - i,
                    float(
                        match.group(0).replace(
                            ",",
                            "",
                        )
                    ),
                )
            )

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: x[0]
    )

    return candidates[0][1]


def _percentage_before_label(
    lines: List[str],
    label_index: int,
    search_distance: int = 3,
) -> Optional[float]:
    """
    Prefer a percentage immediately BEFORE the label.

    This is important for presentation structures like:

        54%
        Gross Margin

    It prevents a nearby 118% NRR from becoming Gross Margin.
    """

    # First preference: immediately preceding line.
    if label_index > 0:

        previous_line = (
            lines[label_index - 1]
            .strip()
        )

        match = re.fullmatch(
            r"(-?\d+(?:\.\d+)?)\s*%",
            previous_line,
        )

        if match:
            return float(
                match.group(1)
            )

    # Fallback: search backwards only.
    start = max(
        0,
        label_index - search_distance,
    )

    for i in range(
        label_index - 1,
        start - 1,
        -1,
    ):

        line = lines[i].strip()

        match = re.fullmatch(
            r"(-?\d+(?:\.\d+)?)\s*%",
            line,
        )

        if match:
            return float(
                match.group(1)
            )

    return None


def _percentage_after_label(
    lines: List[str],
    label_index: int,
    search_distance: int = 3,
) -> Optional[float]:
    """
    Search forward for a percentage.

    Used only where the presentation structure puts
    the label before the value.
    """

    end = min(
        len(lines),
        label_index + search_distance + 1,
    )

    for i in range(
        label_index + 1,
        end,
    ):

        line = lines[i].strip()

        match = re.fullmatch(
            r"(-?\d+(?:\.\d+)?)\s*%",
            line,
        )

        if match:
            return float(
                match.group(1)
            )

    return None


def _money_cr_near_label(
    lines: List[str],
    label_index: int,
    search_distance: int = 4,
) -> Optional[float]:
    """
    Find ₹X Cr close to a label.
    """

    # Search immediately before first.
    start = max(
        0,
        label_index - search_distance,
    )

    for i in range(
        label_index - 1,
        start - 1,
        -1,
    ):

        line = lines[i].strip()

        match = re.fullmatch(
            r"₹\s*([\d,]+(?:\.\d+)?)\s*Cr",
            line,
            flags=re.IGNORECASE,
        )

        if match:
            return float(
                match.group(1).replace(
                    ",",
                    "",
                )
            )

    # Then search after.
    end = min(
        len(lines),
        label_index + search_distance + 1,
    )

    for i in range(
        label_index + 1,
        end,
    ):

        line = lines[i].strip()

        match = re.fullmatch(
            r"₹\s*([\d,]+(?:\.\d+)?)\s*Cr",
            line,
            flags=re.IGNORECASE,
        )

        if match:
            return float(
                match.group(1).replace(
                    ",",
                    "",
                )
            )

    return None


def _lakh_near_label(
    lines: List[str],
    label_index: int,
    search_distance: int = 4,
) -> Optional[float]:
    """
    Find a value expressed in Lakhs near a label.
    """

    start = max(
        0,
        label_index - search_distance,
    )

    end = min(
        len(lines),
        label_index + search_distance + 1,
    )

    candidates = []

    for i in range(
        start,
        end,
    ):

        if i == label_index:
            continue

        line = lines[i].strip()

        match = re.fullmatch(
            r"₹?\s*([\d,]+(?:\.\d+)?)\s*Lakh",
            line,
            flags=re.IGNORECASE,
        )

        if match:

            candidates.append(
                (
                    abs(
                        i - label_index
                    ),
                    float(
                        match.group(1).replace(
                            ",",
                            "",
                        )
                    ),
                )
            )

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: x[0]
    )

    return candidates[0][1]


# ================================================================
# INVESTOR PRESENTATION
# ================================================================

def _extract_investor_presentation_evidence(
    text: str,
    file_name: str,
    document_type: str,
) -> List[Dict[str, Any]]:
    """
    Extract metrics from PPT text where labels and values
    are frequently placed on separate lines.
    """

    evidence: List[Dict[str, Any]] = []

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    # ------------------------------------------------------------
    # CUSTOMER COUNT
    #
    # Expected structure:
    #
    # 165
    # Enterprise customers
    # ------------------------------------------------------------

    for i, line in enumerate(lines):

        if (
            line.lower()
            == "enterprise customers"
        ):

            value = _number_from_previous_lines(
                lines,
                i,
                search_distance=2,
            )

            if value is not None:

                evidence.append(
                    _build_evidence_record(
                        file_name=file_name,
                        document_type=document_type,
                        field="reported_customers",
                        value=int(value),
                        source_location=(
                            "Investor presentation "
                            "slide"
                        ),
                        confidence=0.98,
                        context="\n".join(
                            lines[
                                max(0, i - 2):
                                min(len(lines), i + 2)
                            ]
                        ),
                    )
                )

                break

    # ------------------------------------------------------------
    # ARR
    #
    # Expected:
    #
    # ₹18.9 Cr
    # ARR
    #
    # We only look for a money amount close to the
    # actual ARR label.
    # ------------------------------------------------------------

    for i, line in enumerate(lines):

        if line.lower() == "arr":

            value = _money_cr_near_label(
                lines,
                i,
                search_distance=3,
            )

            if value is not None:

                evidence.append(
                    _build_evidence_record(
                        file_name=file_name,
                        document_type=document_type,
                        field="arr",
                        value=value,
                        source_location=(
                            "Investor presentation "
                            "slide"
                        ),
                        confidence=0.98,
                        context="\n".join(
                            lines[
                                max(0, i - 3):
                                min(len(lines), i + 3)
                            ]
                        ),
                    )
                )

                break

    # ------------------------------------------------------------
    # NRR
    #
    # Expected:
    #
    # 118%
    # Net Revenue Retention
    #
    # Search backwards first.
    # ------------------------------------------------------------

    for i, line in enumerate(lines):

        if (
            line.lower()
            == "net revenue retention"
        ):

            value = _percentage_before_label(
                lines,
                i,
                search_distance=3,
            )

            if value is None:

                value = _percentage_after_label(
                    lines,
                    i,
                    search_distance=3,
                )

            if value is not None:

                evidence.append(
                    _build_evidence_record(
                        file_name=file_name,
                        document_type=document_type,
                        field="nrr",
                        value=value,
                        source_location=(
                            "Investor presentation "
                            "slide"
                        ),
                        confidence=0.98,
                        context="\n".join(
                            lines[
                                max(0, i - 3):
                                min(len(lines), i + 3)
                            ]
                        ),
                    )
                )

                break

    # ------------------------------------------------------------
    # GROSS MARGIN
    #
    # Expected structure:
    #
    # 54%
    # Gross Margin
    #
    # IMPORTANT:
    # Search backwards only first.
    # ------------------------------------------------------------

    for i, line in enumerate(lines):

        if line.lower() != "gross margin":
            continue

        value = _percentage_before_label(
            lines,
            i,
            search_distance=3,
        )

        # Only use a forward value if there is no backward
        # percentage at all.
        if value is None:
            value = _percentage_after_label(
                lines,
                i,
                search_distance=2,
            )

        if value is not None:

            evidence.append(
                _build_evidence_record(
                    file_name=file_name,
                    document_type=document_type,
                    field="gross_margin",
                    value=value,
                    source_location=(
                        "Investor presentation slide"
                    ),
                    confidence=0.98,
                    context="\n".join(
                        lines[
                            max(0, i - 3):
                            min(len(lines), i + 3)
                        ]
                    ),
                )
            )

            break

    # ------------------------------------------------------------
    # CAC
    # ------------------------------------------------------------

    for i, line in enumerate(lines):

        if line.lower() == "cac":

            value = _lakh_near_label(
                lines,
                i,
                search_distance=4,
            )

            if value is not None:

                evidence.append(
                    _build_evidence_record(
                        file_name=file_name,
                        document_type=document_type,
                        field="cac",
                        value=value,
                        source_location=(
                            "Investor presentation slide"
                        ),
                        confidence=0.95,
                        context="\n".join(
                            lines[
                                max(0, i - 3):
                                min(len(lines), i + 4)
                            ]
                        ),
                    )
                )

                break

    # ------------------------------------------------------------
    # ACV
    # ------------------------------------------------------------

    for i, line in enumerate(lines):

        if line.lower() == "acv":

            value = _lakh_near_label(
                lines,
                i,
                search_distance=4,
            )

            if value is not None:

                evidence.append(
                    _build_evidence_record(
                        file_name=file_name,
                        document_type=document_type,
                        field="acv",
                        value=value,
                        source_location=(
                            "Investor presentation slide"
                        ),
                        confidence=0.95,
                        context="\n".join(
                            lines[
                                max(0, i - 3):
                                min(len(lines), i + 4)
                            ]
                        ),
                    )
                )

                break

    # ------------------------------------------------------------
    # CAPITAL RAISED
    # ------------------------------------------------------------

    for i, line in enumerate(lines):

        if (
            "capital raised to date"
            in line.lower()
            or line.lower() == "capital raised"
        ):

            value = _money_cr_near_label(
                lines,
                i,
                search_distance=4,
            )

            if value is not None:

                evidence.append(
                    _build_evidence_record(
                        file_name=file_name,
                        document_type=document_type,
                        field="capital_raised",
                        value=value,
                        source_location=(
                            "Investor presentation slide"
                        ),
                        confidence=0.98,
                        context="\n".join(
                            lines[
                                max(0, i - 4):
                                min(len(lines), i + 5)
                            ]
                        ),
                    )
                )

                break

    # ------------------------------------------------------------
    # TARGET RAISE
    # ------------------------------------------------------------

    for i, line in enumerate(lines):

        if (
            line.lower() == "target raise"
            or "target raise" in line.lower()
        ):

            value = _money_cr_near_label(
                lines,
                i,
                search_distance=4,
            )

            if value is not None:

                evidence.append(
                    _build_evidence_record(
                        file_name=file_name,
                        document_type=document_type,
                        field="target_raise",
                        value=value,
                        source_location=(
                            "Investor presentation slide"
                        ),
                        confidence=0.98,
                        context="\n".join(
                            lines[
                                max(0, i - 4):
                                min(len(lines), i + 5)
                            ]
                        ),
                    )
                )

                break

    # ------------------------------------------------------------
    # FOUNDER OWNERSHIP
    # ------------------------------------------------------------

    for i, line in enumerate(lines):

        if (
            line.lower() == "founders"
            or line.lower() == "founder ownership"
        ):

            value = _percentage_before_label(
                lines,
                i,
                search_distance=3,
            )

            if value is None:

                value = _percentage_after_label(
                    lines,
                    i,
                    search_distance=3,
                )

            if value is not None:

                if value > 1:
                    value /= 100

                evidence.append(
                    _build_evidence_record(
                        file_name=file_name,
                        document_type=document_type,
                        field="founder_ownership",
                        value=value,
                        source_location=(
                            "Investor presentation "
                            "slide"
                        ),
                        confidence=0.97,
                        context="\n".join(
                            lines[
                                max(0, i - 3):
                                min(len(lines), i + 3)
                            ]
                        ),
                    )
                )

                break

    return evidence


# ================================================================
# LEGAL / CORPORATE DILIGENCE
# ================================================================

def _extract_legal_evidence(
    text: str,
    file_name: str,
    document_type: str,
) -> List[Dict[str, Any]]:

    evidence: List[Dict[str, Any]] = []

    risk_keywords = {
        "ip_assignment": [
            "ip assignment",
            "intellectual property assignment",
            "contractor ip",
            "former contractor",
        ],
        "data_processing": [
            "data processing",
            "data-processing",
        ],
        "litigation": [
            "litigation",
            "legal proceedings",
            "dispute",
        ],
        "compliance": [
            "compliance",
            "regulatory",
        ],
    }

    lowered = text.lower()

    for field, keywords in risk_keywords.items():

        for keyword in keywords:

            idx = lowered.find(
                keyword
            )

            if idx == -1:
                continue

            start = max(
                0,
                idx - 180,
            )

            end = min(
                len(text),
                idx + 350,
            )

            evidence.append(
                _build_evidence_record(
                    file_name=file_name,
                    document_type=document_type,
                    field=field,
                    value=True,
                    source_location=(
                        "Legal diligence text"
                    ),
                    confidence=0.88,
                    context=text[
                        start:end
                    ].strip(),
                )
            )

            break

    return evidence


# ================================================================
# MAIN DOCUMENT EXTRACTION
# ================================================================

def extract_evidence_from_document(
    document: Dict[str, Any],
    classification: Dict[str, Any],
) -> List[Dict[str, Any]]:

    file_name = document.get(
        "file_name",
        "Unknown",
    )

    document_type = classification.get(
        "document_type",
        "Unknown",
    )

    text = _clean_text(
        document.get(
            "text",
            "",
        )
    )

    if not text:
        return []

    if document_type in {
        "Financial Model",
        "Customer / Operating Metrics",
        "Cap Table",
    }:

        return _extract_spreadsheet_evidence(
            text=text,
            file_name=file_name,
            document_type=document_type,
        )

    if document_type == "Bank Statement":

        return _extract_bank_statement_evidence(
            text=text,
            file_name=file_name,
            document_type=document_type,
        )

    if document_type == "Investor Presentation":

        return _extract_investor_presentation_evidence(
            text=text,
            file_name=file_name,
            document_type=document_type,
        )

    if document_type == "Legal / Corporate Diligence":

        return _extract_legal_evidence(
            text=text,
            file_name=file_name,
            document_type=document_type,
        )

    return []


# ================================================================
# BUILD EVIDENCE STORE
# ================================================================

def build_evidence_store(
    documents: List[Dict[str, Any]],
    classifications: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    classification_by_file = {
        item["file_name"]: item
        for item in classifications
    }

    evidence_store: List[Dict[str, Any]] = []

    for document in documents:

        file_name = document.get(
            "file_name"
        )

        classification = (
            classification_by_file.get(
                file_name,
                {
                    "document_type": "Unknown"
                },
            )
        )

        evidence_store.extend(
            extract_evidence_from_document(
                document=document,
                classification=classification,
            )
        )

    return evidence_store


# ================================================================
# SUMMARY
# ================================================================

def summarize_evidence_store(
    evidence_store: List[Dict[str, Any]],
) -> Dict[str, Any]:

    by_type: Dict[str, int] = {}
    by_field: Dict[str, int] = {}

    for item in evidence_store:

        document_type = item.get(
            "document_type",
            "Unknown",
        )

        field = item.get(
            "field",
            "Unknown",
        )

        by_type[document_type] = (
            by_type.get(
                document_type,
                0,
            )
            + 1
        )

        by_field[field] = (
            by_field.get(
                field,
                0,
            )
            + 1
        )

    return {
        "total_evidence_items": len(
            evidence_store
        ),
        "items_by_document_type": by_type,
        "items_by_field": by_field,
    }