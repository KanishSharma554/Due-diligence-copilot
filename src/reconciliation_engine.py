from __future__ import annotations

from typing import Any, Dict, List, Optional


# ================================================================
# COMPARISON DEFINITIONS
# ================================================================

COMPARISON_GROUPS = {
    "customer_count": [
        "active_customers",
        "reported_customers",
    ],
    "arr": [
        "arr",
        "total_arr",
    ],
    "nrr": [
        "nrr",
    ],
    "churn": [
        "churn",
    ],
    "cac": [
        "cac",
    ],
    "acv": [
        "acv",
    ],
    "gross_margin": [
        "gross_margin",
    ],
    "founder_ownership": [
        "founder_ownership",
    ],
    "closing_cash": [
        "closing_cash",
        "closing_balance",
    ],
}


# ================================================================
# SOURCE PRIORITY
# ================================================================

SOURCE_PRIORITY = {
    "Bank Statement": 100,
    "Cap Table": 100,
    "Financial Model": 90,
    "Customer / Operating Metrics": 90,
    "Investor Presentation": 70,
    "Legal / Corporate Diligence": 50,
}


# ================================================================
# BASIC HELPERS
# ================================================================

def _numeric(value: Any) -> Optional[float]:
    """Convert a value to a numeric value where possible."""

    if isinstance(value, bool):
        return None

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    try:
        cleaned = (
            str(value)
            .replace(",", "")
            .replace("₹", "")
            .replace("Rs.", "")
            .replace("Rs", "")
            .strip()
        )

        return float(cleaned)

    except (TypeError, ValueError):
        return None


def _field_label(field: str) -> str:
    """Convert internal field name into a readable label."""

    labels = {
        "customer_count": "Customer Count",
        "arr": "ARR",
        "nrr": "NRR",
        "churn": "Churn",
        "cac": "CAC",
        "acv": "ACV",
        "gross_margin": "Gross Margin",
        "founder_ownership": "Founder Ownership",
        "closing_cash": "Closing Cash",
    }

    return labels.get(
        field,
        field.replace("_", " ").title(),
    )


def _percentage_field(field: str) -> bool:
    return field in {
        "nrr",
        "churn",
        "gross_margin",
    }


def _display_value(
    field: str,
    value: float,
) -> str:
    """Format values for display."""

    if field == "customer_count":
        return f"{value:,.0f}"

    if field == "founder_ownership":
        return f"{value * 100:.1f}%"

    if _percentage_field(field):
        return f"{value:.1f}%"

    return f"{value:,.2f}"


def _relative_difference(
    value_a: float,
    value_b: float,
) -> float:
    """Calculate relative difference as a percentage."""

    difference = abs(
        value_a - value_b
    )

    base = max(
        abs(value_a),
        abs(value_b),
        0.01,
    )

    return (
        difference / base
    ) * 100


# ================================================================
# SANITY CHECKS
# ================================================================

def _valid_value(
    field: str,
    value: float,
) -> bool:
    """
    Reject clearly invalid values before reconciliation.

    This protects the engine from extraction errors such as
    accidentally assigning NRR = 118% to Gross Margin.
    """

    # Gross margin normally sits between 0% and 100%.
    if field == "gross_margin":
        return 0 <= value <= 100

    # Churn cannot be negative.
    if field == "churn":
        return value >= 0

    # NRR cannot be negative.
    if field == "nrr":
        return value >= 0

    # Customer count must be non-negative.
    if field == "customer_count":
        return value >= 0

    # Ownership must sit between 0% and 100% when stored
    # internally as a decimal.
    if field == "founder_ownership":
        return 0 <= value <= 1

    # Financial figures can technically be negative
    # depending on the metric, so no blanket restriction.
    return True


# ================================================================
# MATERIALITY
# ================================================================

def _is_material_difference(
    field: str,
    value_a: float,
    value_b: float,
) -> bool:
    """
    Determine whether two values represent a material discrepancy.
    """

    # Never compare clearly invalid extracted values.
    if not _valid_value(
        field,
        value_a,
    ):
        return False

    if not _valid_value(
        field,
        value_b,
    ):
        return False

    difference = abs(
        value_a - value_b
    )

    # ------------------------------------------------------------
    # CUSTOMER COUNT
    # ------------------------------------------------------------

    if field == "customer_count":
        return difference >= 1

    # ------------------------------------------------------------
    # FOUNDER OWNERSHIP
    #
    # Stored internally:
    # 60% = 0.60
    # 65% = 0.65
    # ------------------------------------------------------------

    if field == "founder_ownership":
        return difference > 0.01

    # ------------------------------------------------------------
    # PERCENTAGE METRICS
    # ------------------------------------------------------------

    if field in {
        "nrr",
        "churn",
        "gross_margin",
    }:
        return difference > 1.0

    # ------------------------------------------------------------
    # FINANCIAL METRICS
    # ------------------------------------------------------------

    base = max(
        abs(value_a),
        abs(value_b),
        0.01,
    )

    relative_difference = (
        difference / base
    )

    return relative_difference > 0.01


# ================================================================
# SEVERITY
# ================================================================

def _severity(
    field: str,
    value_a: float,
    value_b: float,
) -> str:
    """Assign High / Medium / Low severity."""

    difference = abs(
        value_a - value_b
    )

    # ------------------------------------------------------------
    # CUSTOMER COUNT
    # ------------------------------------------------------------

    if field == "customer_count":

        if difference >= 20:
            return "High"

        if difference >= 5:
            return "Medium"

        return "Low"

    # ------------------------------------------------------------
    # FOUNDER OWNERSHIP
    # ------------------------------------------------------------

    if field == "founder_ownership":

        if difference >= 0.05:
            return "High"

        if difference >= 0.02:
            return "Medium"

        return "Low"

    # ------------------------------------------------------------
    # PERCENTAGE METRICS
    # ------------------------------------------------------------

    if field in {
        "nrr",
        "churn",
        "gross_margin",
    }:

        if difference >= 10:
            return "High"

        if difference >= 3:
            return "Medium"

        return "Low"

    # ------------------------------------------------------------
    # GENERIC FINANCIAL METRICS
    # ------------------------------------------------------------

    relative = (
        difference
        / max(
            abs(value_a),
            abs(value_b),
            0.01,
        )
    )

    if relative >= 0.15:
        return "High"

    if relative >= 0.05:
        return "Medium"

    return "Low"


# ================================================================
# FIELD -> COMPARISON GROUP
# ================================================================

def _field_to_group() -> Dict[str, str]:
    """
    Reverse-map evidence fields to comparison groups.
    """

    result: Dict[str, str] = {}

    for group, fields in COMPARISON_GROUPS.items():

        for field in fields:
            result[field] = group

    return result


# ================================================================
# SOURCE PRIORITY
# ================================================================

def _source_priority(
    item: Dict[str, Any],
) -> int:
    """Return the priority for a document type."""

    return SOURCE_PRIORITY.get(
        item.get(
            "document_type",
            "",
        ),
        0,
    )


# ================================================================
# DEDUPLICATE EVIDENCE
# ================================================================

def _deduplicate_evidence(
    evidence_store: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Remove exact duplicate evidence records.
    """

    seen = set()

    unique: List[
        Dict[str, Any]
    ] = []

    for item in evidence_store:

        numeric_value = _numeric(
            item.get("value")
        )

        key = (
            item.get("file_name"),
            item.get("field"),
            numeric_value
            if numeric_value is not None
            else str(
                item.get("value")
            ),
        )

        if key in seen:
            continue

        seen.add(key)

        unique.append(item)

    return unique


# ================================================================
# PREPARE EVIDENCE
# ================================================================

def _prepare_evidence(
    evidence_store: List[Dict[str, Any]],
) -> Dict[
    str,
    Dict[
        float,
        List[Dict[str, Any]]
    ],
]:
    """
    Organize evidence as:

        comparison_group
            -> normalized value
                -> evidence records

    Example:

        customer_count
            -> 143 -> two supporting files
            -> 165 -> one supporting file
    """

    field_to_group = _field_to_group()

    prepared: Dict[
        str,
        Dict[
            float,
            List[Dict[str, Any]]
        ],
    ] = {}

    evidence_store = _deduplicate_evidence(
        evidence_store
    )

    for item in evidence_store:

        field = item.get(
            "field"
        )

        if field not in field_to_group:
            continue

        value = _numeric(
            item.get("value")
        )

        if value is None:
            continue

        group = field_to_group[field]

        # Ignore obviously invalid values.
        if not _valid_value(
            group,
            value,
        ):
            continue

        prepared.setdefault(
            group,
            {}
        )

        prepared[group].setdefault(
            value,
            []
        )

        prepared[group][value].append(
            item
        )

    return prepared


# ================================================================
# SELECT BEST SOURCE
# ================================================================

def _best_source(
    evidence_items: List[
        Dict[str, Any]
    ],
) -> Dict[str, Any]:
    """
    Select the strongest source supporting a value.
    """

    ranked = sorted(
        evidence_items,
        key=lambda x: (
            _source_priority(x),
            float(
                x.get(
                    "confidence",
                    0,
                )
            ),
        ),
        reverse=True,
    )

    return ranked[0]


# ================================================================
# SOURCE SUMMARY
# ================================================================

def _source_summary(
    evidence_items: List[
        Dict[str, Any]
    ],
) -> List[Dict[str, Any]]:
    """
    Preserve all sources supporting a particular value.
    """

    summaries = []

    seen = set()

    for item in evidence_items:

        key = (
            item.get(
                "file_name"
            ),
            item.get(
                "field"
            ),
        )

        if key in seen:
            continue

        seen.add(key)

        summaries.append(
            {
                "file_name": item.get(
                    "file_name"
                ),
                "document_type": item.get(
                    "document_type"
                ),
                "field": item.get(
                    "field"
                ),
                "source_location": item.get(
                    "source_location"
                ),
                "confidence": item.get(
                    "confidence"
                ),
                "context": item.get(
                    "context"
                ),
            }
        )

    return summaries


# ================================================================
# CREATE RECONCILIATION
# ================================================================

def _create_reconciliation(
    group: str,
    value_a: float,
    records_a: List[
        Dict[str, Any]
    ],
    value_b: float,
    records_b: List[
        Dict[str, Any]
    ],
) -> Optional[
    Dict[str, Any]
]:

    if not _is_material_difference(
        group,
        value_a,
        value_b,
    ):
        return None

    source_a = _best_source(
        records_a
    )

    source_b = _best_source(
        records_b
    )

    # ------------------------------------------------------------
    # Critical safeguard:
    #
    # If the same source document is supporting both values,
    # do not report a cross-document discrepancy.
    # ------------------------------------------------------------

    files_a = {
        item.get(
            "file_name"
        )
        for item in records_a
    }

    files_b = {
        item.get(
            "file_name"
        )
        for item in records_b
    }

    if files_a.intersection(
        files_b
    ):
        return None

    difference = abs(
        value_a - value_b
    )

    relative_difference = (
        _relative_difference(
            value_a,
            value_b,
        )
    )

    return {
        "comparison_group": group,

        "field": group,

        "field_label": _field_label(
            group
        ),

        "status": "Discrepancy",

        "severity": _severity(
            group,
            value_a,
            value_b,
        ),

        "value_a": value_a,

        "value_b": value_b,

        "display_value_a": _display_value(
            group,
            value_a,
        ),

        "display_value_b": _display_value(
            group,
            value_b,
        ),

        "absolute_difference": difference,

        "relative_difference_pct": round(
            relative_difference,
            2,
        ),

        "source_a": {
            "file_name": source_a.get(
                "file_name"
            ),

            "document_type": source_a.get(
                "document_type"
            ),

            "field": source_a.get(
                "field"
            ),

            "source_location": source_a.get(
                "source_location"
            ),

            "confidence": source_a.get(
                "confidence"
            ),

            "context": source_a.get(
                "context"
            ),

            "supporting_sources": (
                _source_summary(
                    records_a
                )
            ),
        },

        "source_b": {
            "file_name": source_b.get(
                "file_name"
            ),

            "document_type": source_b.get(
                "document_type"
            ),

            "field": source_b.get(
                "field"
            ),

            "source_location": source_b.get(
                "source_location"
            ),

            "confidence": source_b.get(
                "confidence"
            ),

            "context": source_b.get(
                "context"
            ),

            "supporting_sources": (
                _source_summary(
                    records_b
                )
            ),
        },

        "explanation": (
            f"{_field_label(group)} "
            f"differs across the reviewed "
            f"documents."
        ),
    }


# ================================================================
# MAIN RECONCILIATION ENGINE
# ================================================================

def reconcile_evidence(
    evidence_store: List[
        Dict[str, Any]
    ],
) -> List[
    Dict[str, Any]
]:

    prepared = _prepare_evidence(
        evidence_store
    )

    reconciliations: List[
        Dict[str, Any]
    ] = []

    for group, values in prepared.items():

        unique_values = list(
            values.keys()
        )

        # A reconciliation requires at least
        # two distinct values.
        if len(unique_values) < 2:
            continue

        for i in range(
            len(unique_values)
        ):

            value_a = unique_values[i]

            for j in range(
                i + 1,
                len(unique_values),
            ):

                value_b = unique_values[j]

                result = (
                    _create_reconciliation(
                        group=group,
                        value_a=value_a,
                        records_a=values[
                            value_a
                        ],
                        value_b=value_b,
                        records_b=values[
                            value_b
                        ],
                    )
                )

                if result:
                    reconciliations.append(
                        result
                    )

    # ------------------------------------------------------------
    # Final deduplication.
    # Treat:
    #
    # 143 vs 165
    #
    # and:
    #
    # 165 vs 143
    #
    # as the same finding.
    # ------------------------------------------------------------

    final_results: List[
        Dict[str, Any]
    ] = []

    seen_findings = set()

    for item in reconciliations:

        value_a = round(
            float(
                item.get(
                    "value_a",
                    0,
                )
            ),
            6,
        )

        value_b = round(
            float(
                item.get(
                    "value_b",
                    0,
                )
            ),
            6,
        )

        field = item.get(
            "field"
        )

        normalized_pair = tuple(
            sorted(
                [
                    value_a,
                    value_b,
                ]
            )
        )

        key = (
            field,
            normalized_pair,
        )

        if key in seen_findings:
            continue

        seen_findings.add(
            key
        )

        final_results.append(
            item
        )

    # ------------------------------------------------------------
    # Sort:
    #
    # High
    # Medium
    # Low
    #
    # within each severity, most material first.
    # ------------------------------------------------------------

    severity_order = {
        "High": 0,
        "Medium": 1,
        "Low": 2,
    }

    final_results.sort(
        key=lambda x: (
            severity_order.get(
                x.get(
                    "severity",
                    "Low",
                ),
                3,
            ),
            -float(
                x.get(
                    "relative_difference_pct",
                    0,
                )
            ),
        )
    )

    return final_results


# ================================================================
# SUMMARY
# ================================================================

def summarize_reconciliations(
    reconciliations: List[
        Dict[str, Any]
    ],
) -> Dict[str, Any]:
    """
    Generate dashboard-ready reconciliation statistics.
    """

    summary = {
        "total_discrepancies": len(
            reconciliations
        ),
        "high": 0,
        "medium": 0,
        "low": 0,
        "fields": {},
    }

    for item in reconciliations:

        severity = (
            item.get(
                "severity",
                "Low",
            )
            .lower()
        )

        if severity in summary:
            summary[severity] += 1

        field = item.get(
            "field",
            "unknown",
        )

        summary["fields"][field] = (
            summary["fields"].get(
                field,
                0,
            )
            + 1
        )

    return summary