from __future__ import annotations

from typing import Any, Dict, List, Optional


# ================================================================
# SEVERITY
# ================================================================

SEVERITY_ORDER = {
    "High": 0,
    "Medium": 1,
    "Low": 2,
}


# ================================================================
# HELPERS
# ================================================================

def _risk_record(
    risk_id: str,
    title: str,
    category: str,
    severity: str,
    description: str,
    implication: str,
    evidence: List[Dict[str, Any]],
    recommendation: str,
) -> Dict[str, Any]:
    """
    Standard structure for every risk finding.
    """

    return {
        "risk_id": risk_id,
        "title": title,
        "category": category,
        "severity": severity,
        "description": description,
        "implication": implication,
        "evidence": evidence,
        "recommendation": recommendation,
    }


def _get_value(
    financials: Dict[str, Any],
    section: str,
    field: str,
) -> Optional[float]:
    """
    Safely retrieve a financial-engine output.
    """

    try:
        value = (
            financials
            .get(section, {})
            .get(field)
        )

        if value is None:
            return None

        return float(value)

    except (TypeError, ValueError):
        return None


# ================================================================
# RECONCILIATION RISKS
# ================================================================

def build_reconciliation_risks(
    reconciliations: List[
        Dict[str, Any]
    ],
) -> List[
    Dict[str, Any]
]:

    risks = []

    for index, item in enumerate(
        reconciliations,
        start=1,
    ):

        field = item.get(
            "field_label",
            item.get(
                "field",
                "Unknown",
            ),
        )

        severity = item.get(
            "severity",
            "Medium",
        )

        value_a = item.get(
            "display_value_a",
            "",
        )

        value_b = item.get(
            "display_value_b",
            "",
        )

        source_a = (
            item
            .get("source_a", {})
            .get("file_name", "")
        )

        source_b = (
            item
            .get("source_b", {})
            .get("file_name", "")
        )

        # --------------------------------------------------------
        # Customer count
        # --------------------------------------------------------

        if item.get("field") == "customer_count":

            title = (
                "Customer count inconsistency"
            )

            category = "Commercial"

            description = (
                f"Customer count differs across reviewed "
                f"documents: {value_a} versus {value_b}."
            )

            implication = (
                "Reported traction should be reconciled "
                "before relying on customer-count claims."
            )

            recommendation = (
                "Confirm the definition, reporting date, and "
                "source system underlying the customer count."
            )

        # --------------------------------------------------------
        # Cash
        # --------------------------------------------------------

        elif item.get("field") == "closing_cash":

            title = (
                "Cash balance variance"
            )

            category = "Financial"

            description = (
                f"Closing cash differs across the financial model "
                f"and bank statement: {value_a} versus {value_b}."
            )

            implication = (
                "The variance may affect the company's reported "
                "liquidity position and available runway."
            )

            recommendation = (
                "Reconcile the bank balance to the financial model "
                "and identify the ₹0.31 Cr variance."
            )

        # --------------------------------------------------------
        # Ownership
        # --------------------------------------------------------

        elif item.get(
            "field"
        ) == "founder_ownership":

            title = (
                "Founder ownership inconsistency"
            )

            category = "Ownership"

            description = (
                f"Founder ownership differs across reviewed "
                f"documents: {value_a} versus {value_b}."
            )

            implication = (
                "The ownership structure should be reconciled "
                "before assessing dilution and transaction proceeds."
            )

            recommendation = (
                "Use the current cap table as the primary source "
                "and confirm the investor presentation has been updated."
            )

        # --------------------------------------------------------
        # Generic reconciliation risk
        # --------------------------------------------------------

        else:

            title = (
                f"{field} inconsistency"
            )

            category = "Reconciliation"

            description = (
                f"{field} differs across reviewed documents: "
                f"{value_a} versus {value_b}."
            )

            implication = (
                "The underlying figure should be reconciled "
                "before being relied upon."
            )

            recommendation = (
                "Confirm the authoritative source and reporting period."
            )

        evidence = [
            {
                "type": "Cross-document reconciliation",
                "field": field,
                "value_a": value_a,
                "value_b": value_b,
                "source_a": source_a,
                "source_b": source_b,
                "relative_difference_pct": item.get(
                    "relative_difference_pct"
                ),
            }
        ]

        risks.append(
            _risk_record(
                risk_id=f"REC-{index:03d}",
                title=title,
                category=category,
                severity=severity,
                description=description,
                implication=implication,
                evidence=evidence,
                recommendation=recommendation,
            )
        )

    return risks


# ================================================================
# LEGAL RISKS
# ================================================================

def build_legal_risks(
    evidence_store: List[
        Dict[str, Any]
    ],
) -> List[
    Dict[str, Any]
]:

    risks = []

    # ------------------------------------------------------------
    # IP assignment
    # ------------------------------------------------------------

    ip_evidence = [
        item
        for item in evidence_store
        if item.get(
            "field"
        ) == "ip_assignment"
    ]

    if ip_evidence:

        risks.append(
            _risk_record(
                risk_id="LEGAL-001",
                title=(
                    "Incomplete contractor IP assignment"
                ),
                category="Legal / IP",
                severity="High",
                description=(
                    "Legal diligence identifies incomplete "
                    "intellectual-property assignment documentation "
                    "for a former external contractor."
                ),
                implication=(
                    "There may be uncertainty regarding ownership "
                    "of work product or intellectual property created "
                    "under the contractor relationship."
                ),
                evidence=[
                    {
                        "type": "Legal diligence",
                        "file_name": item.get(
                            "file_name"
                        ),
                        "source_location": item.get(
                            "source_location"
                        ),
                        "context": item.get(
                            "context"
                        ),
                    }
                    for item in ip_evidence
                ],
                recommendation=(
                    "Obtain and review the underlying contractor "
                    "agreement and execute any missing IP assignment "
                    "documentation before closing."
                ),
            )
        )

    # ------------------------------------------------------------
    # Data processing
    # ------------------------------------------------------------

    data_evidence = [
        item
        for item in evidence_store
        if item.get(
            "field"
        ) == "data_processing"
    ]

    if data_evidence:

        risks.append(
            _risk_record(
                risk_id="LEGAL-002",
                title=(
                    "Data-processing documentation update outstanding"
                ),
                category="Legal / Compliance",
                severity="Medium",
                description=(
                    "Legal diligence notes that data-processing "
                    "documentation is being updated to reflect the "
                    "company's current customer data architecture."
                ),
                implication=(
                    "Current privacy and data-processing documentation "
                    "may not yet fully reflect operational practices."
                ),
                evidence=[
                    {
                        "type": "Legal diligence",
                        "file_name": item.get(
                            "file_name"
                        ),
                        "source_location": item.get(
                            "source_location"
                        ),
                        "context": item.get(
                            "context"
                        ),
                    }
                    for item in data_evidence
                ],
                recommendation=(
                    "Confirm completion of the revised data-processing "
                    "and privacy documentation."
                ),
            )
        )

    return risks


# ================================================================
# FINANCIAL RISKS
# ================================================================

def build_financial_risks(
    financials: Dict[str, Any],
) -> List[
    Dict[str, Any]
]:

    risks = []

    # ------------------------------------------------------------
    # Runway
    # ------------------------------------------------------------

    runway = _get_value(
        financials,
        "cash",
        "estimated_runway_months",
    )

    if (
        runway is not None
        and runway < 9
    ):

        severity = (
            "High"
            if runway < 6
            else "Medium"
        )

        risks.append(
            _risk_record(
                risk_id="FIN-001",
                title=(
                    "Limited cash runway"
                ),
                category="Liquidity",
                severity=severity,
                description=(
                    f"Estimated runway is approximately "
                    f"{runway:.1f} months based on current "
                    f"bank cash and monthly burn."
                ),
                implication=(
                    "The company may require additional funding "
                    "to sustain operations if burn remains at "
                    "current levels."
                ),
                evidence=[
                    {
                        "type": "Financial calculation",
                        "bank_cash_cr": financials.get(
                            "cash",
                            {},
                        ).get(
                            "bank_closing_cash_cr"
                        ),
                        "monthly_burn_lakh": financials.get(
                            "cash",
                            {},
                        ).get(
                            "monthly_burn_lakh"
                        ),
                        "runway_months": runway,
                    }
                ],
                recommendation=(
                    "Assess funding timing, burn sensitivity, "
                    "and the path to the stated break-even plan."
                ),
            )
        )

    # ------------------------------------------------------------
    # EBITDA
    # ------------------------------------------------------------

    ebitda_margin = _get_value(
        financials,
        "margins",
        "calculated_ebitda_margin_pct",
    )

    if (
        ebitda_margin is not None
        and ebitda_margin < 0
    ):

        risks.append(
            _risk_record(
                risk_id="FIN-002",
                title=(
                    "Negative EBITDA margin"
                ),
                category="Profitability",
                severity="Medium",
                description=(
                    f"Calculated EBITDA margin is "
                    f"{ebitda_margin:.1f}%."
                ),
                implication=(
                    "The company is currently operating below "
                    "EBITDA break-even and remains dependent on "
                    "future operating leverage and/or external capital."
                ),
                evidence=[
                    {
                        "type": "Financial calculation",
                        "revenue_cr": financials.get(
                            "margins",
                            {},
                        ).get(
                            "revenue_cr"
                        ),
                        "ebitda_cr": financials.get(
                            "margins",
                            {},
                        ).get(
                            "ebitda_cr"
                        ),
                        "calculated_ebitda_margin_pct": ebitda_margin,
                    }
                ],
                recommendation=(
                    "Review the assumptions behind gross-margin "
                    "improvement, operating leverage and the "
                    "24-month path to break-even."
                ),
            )
        )

    return risks


# ================================================================
# MASTER RISK ENGINE
# ================================================================

def build_risk_register(
    evidence_store: List[
        Dict[str, Any]
    ],
    reconciliations: List[
        Dict[str, Any]
    ],
    financials: Dict[str, Any],
) -> List[
    Dict[str, Any]
]:

    risks = []

    risks.extend(
        build_reconciliation_risks(
            reconciliations
        )
    )

    risks.extend(
        build_legal_risks(
            evidence_store
        )
    )

    risks.extend(
        build_financial_risks(
            financials
        )
    )

    # ------------------------------------------------------------
    # Sort by severity.
    # ------------------------------------------------------------

    risks.sort(
        key=lambda x: (
            SEVERITY_ORDER.get(
                x.get(
                    "severity",
                    "Low",
                ),
                3,
            ),
            x.get(
                "risk_id",
                "",
            ),
        )
    )

    return risks


# ================================================================
# SUMMARY
# ================================================================

def summarize_risk_register(
    risks: List[
        Dict[str, Any]
    ],
) -> Dict[str, Any]:

    summary = {
        "total_risks": len(
            risks
        ),
        "high": 0,
        "medium": 0,
        "low": 0,
        "by_category": {},
    }

    for risk in risks:

        severity = (
            risk.get(
                "severity",
                "Low",
            )
            .lower()
        )

        if severity in summary:
            summary[severity] += 1

        category = risk.get(
            "category",
            "Other",
        )

        summary[
            "by_category"
        ][category] = (
            summary[
                "by_category"
            ].get(
                category,
                0,
            )
            + 1
        )

    return summary