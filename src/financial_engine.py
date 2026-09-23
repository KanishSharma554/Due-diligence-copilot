from __future__ import annotations

from typing import Any, Dict, List, Optional


# ================================================================
# HELPERS
# ================================================================

def _numeric(value: Any) -> Optional[float]:
    """Convert a value to float where possible."""

    if value is None:
        return None

    if isinstance(value, bool):
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
            .replace("%", "")
            .strip()
        )

        return float(cleaned)

    except (TypeError, ValueError):
        return None


def _round(
    value: Optional[float],
    digits: int = 2,
) -> Optional[float]:
    if value is None:
        return None

    return round(
        value,
        digits,
    )


def _margin(
    numerator: float,
    denominator: float,
) -> Optional[float]:
    """Calculate a margin in percentage points."""

    if denominator == 0:
        return None

    return (
        numerator / denominator
    ) * 100


def _normalise_percentage(
    value: Optional[float],
) -> Optional[float]:
    """
    Normalize percentage values.

    Supported representations:

        0.539   -> 53.9
        -0.144  -> -14.4
        53.9    -> 53.9
        -14.4   -> -14.4
    """

    if value is None:
        return None

    # Decimal representation.
    if abs(value) <= 1:
        return value * 100

    return value


# ================================================================
# EVIDENCE LOOKUP
# ================================================================

def _get_latest_value(
    evidence_store: List[Dict[str, Any]],
    field: str,
    preferred_document_types: Optional[
        List[str]
    ] = None,
) -> Optional[float]:
    """
    Retrieve the strongest evidence value for a field.
    """

    candidates = []

    for item in evidence_store:

        if item.get("field") != field:
            continue

        value = _numeric(
            item.get("value")
        )

        if value is None:
            continue

        candidates.append(item)

    if not candidates:
        return None

    if preferred_document_types:

        preferred = [
            item
            for item in candidates
            if item.get("document_type")
            in preferred_document_types
        ]

        if preferred:
            candidates = preferred

    candidates.sort(
        key=lambda x: float(
            x.get(
                "confidence",
                0,
            )
        ),
        reverse=True,
    )

    return _numeric(
        candidates[0].get("value")
    )


def _get_all_values(
    evidence_store: List[Dict[str, Any]],
    field: str,
    document_type: Optional[str] = None,
) -> List[Dict[str, Any]]:

    results = []

    for item in evidence_store:

        if item.get("field") != field:
            continue

        if (
            document_type is not None
            and item.get("document_type")
            != document_type
        ):
            continue

        value = _numeric(
            item.get("value")
        )

        if value is None:
            continue

        results.append(item)

    return results


# ================================================================
# REVENUE
# ================================================================

def calculate_revenue_metrics(
    evidence_store: List[Dict[str, Any]],
) -> Dict[str, Any]:

    revenue = _get_latest_value(
        evidence_store,
        "revenue",
        [
            "Financial Model",
        ],
    )

    return {
        "available": revenue is not None,
        "current_revenue_cr": _round(
            revenue
        ),
    }


# ================================================================
# CUSTOMER METRICS
# ================================================================

def calculate_customer_metrics(
    evidence_store: List[Dict[str, Any]],
) -> Dict[str, Any]:

    active_customers = _get_latest_value(
        evidence_store,
        "active_customers",
        [
            "Customer / Operating Metrics",
            "Financial Model",
        ],
    )

    arr = _get_latest_value(
        evidence_store,
        "total_arr",
        [
            "Customer / Operating Metrics",
        ],
    )

    if arr is None:
        arr = _get_latest_value(
            evidence_store,
            "arr",
            [
                "Financial Model",
            ],
        )

    acv = _get_latest_value(
        evidence_store,
        "acv",
        [
            "Customer / Operating Metrics",
            "Financial Model",
            "Investor Presentation",
        ],
    )

    result = {
        "active_customers": active_customers,
        "arr_cr": _round(arr),
        "acv_lakh": _round(acv),
    }

    if (
        arr is not None
        and active_customers is not None
        and active_customers > 0
    ):

        result[
            "calculated_arr_per_customer_lakh"
        ] = _round(
            (arr * 100)
            / active_customers
        )

    return result


# ================================================================
# MARGIN ANALYSIS
# ================================================================

def calculate_margin_metrics(
    evidence_store: List[Dict[str, Any]],
) -> Dict[str, Any]:

    revenue = _get_latest_value(
        evidence_store,
        "revenue",
        [
            "Financial Model",
        ],
    )

    ebitda = _get_latest_value(
        evidence_store,
        "ebitda",
        [
            "Financial Model",
        ],
    )

    reported_gross_margin = _get_latest_value(
        evidence_store,
        "gross_margin",
        [
            "Financial Model",
        ],
    )

    reported_ebitda_margin = _get_latest_value(
        evidence_store,
        "ebitda_margin",
        [
            "Financial Model",
        ],
    )

    # ------------------------------------------------------------
    # Normalize percentages regardless of whether the upstream
    # evidence is represented as decimal or percentage points.
    # ------------------------------------------------------------

    reported_gross_margin = (
        _normalise_percentage(
            reported_gross_margin
        )
    )

    reported_ebitda_margin = (
        _normalise_percentage(
            reported_ebitda_margin
        )
    )

    calculated_ebitda_margin = None

    if (
        revenue is not None
        and ebitda is not None
    ):

        calculated_ebitda_margin = _margin(
            ebitda,
            revenue,
        )

    return {
        "revenue_cr": _round(
            revenue
        ),

        "ebitda_cr": _round(
            ebitda
        ),

        "reported_gross_margin_pct": _round(
            reported_gross_margin
        ),

        "reported_ebitda_margin_pct": _round(
            reported_ebitda_margin
        ),

        "calculated_ebitda_margin_pct": _round(
            calculated_ebitda_margin
        ),
    }


# ================================================================
# CASH ANALYSIS
# ================================================================

def calculate_cash_metrics(
    evidence_store: List[Dict[str, Any]],
) -> Dict[str, Any]:

    model_cash = _get_latest_value(
        evidence_store,
        "closing_cash",
        [
            "Financial Model",
        ],
    )

    bank_cash = _get_latest_value(
        evidence_store,
        "closing_balance",
        [
            "Bank Statement",
        ],
    )

    monthly_burn = _get_latest_value(
        evidence_store,
        "monthly_burn",
        [
            "Financial Model",
        ],
    )

    result = {
        "model_closing_cash_cr": _round(
            model_cash
        ),
        "bank_closing_cash_cr": _round(
            bank_cash
        ),
        "monthly_burn_lakh": _round(
            monthly_burn
        ),
    }

    if (
        model_cash is not None
        and bank_cash is not None
    ):

        result[
            "cash_variance_cr"
        ] = _round(
            abs(
                model_cash
                - bank_cash
            )
        )

    if (
        bank_cash is not None
        and monthly_burn is not None
        and monthly_burn > 0
    ):

        result[
            "estimated_runway_months"
        ] = _round(
            (
                bank_cash * 100
            ) / monthly_burn
        )

    return result


# ================================================================
# OPERATING METRICS
# ================================================================

def calculate_operating_metrics(
    evidence_store: List[Dict[str, Any]],
) -> Dict[str, Any]:

    nrr = _get_latest_value(
        evidence_store,
        "nrr",
        [
            "Customer / Operating Metrics",
            "Financial Model",
            "Investor Presentation",
        ],
    )

    churn = _get_latest_value(
        evidence_store,
        "churn",
        [
            "Customer / Operating Metrics",
            "Financial Model",
        ],
    )

    cac = _get_latest_value(
        evidence_store,
        "cac",
        [
            "Customer / Operating Metrics",
            "Financial Model",
            "Investor Presentation",
        ],
    )

    acv = _get_latest_value(
        evidence_store,
        "acv",
        [
            "Customer / Operating Metrics",
            "Financial Model",
            "Investor Presentation",
        ],
    )

    nrr = _normalise_percentage(nrr)
    churn = _normalise_percentage(churn)

    result = {
        "nrr_pct": _round(nrr),
        "churn_pct": _round(churn),
        "cac_lakh": _round(cac),
        "acv_lakh": _round(acv),
    }

    if (
        cac is not None
        and acv is not None
        and acv > 0
    ):

        result[
            "cac_to_acv_ratio"
        ] = _round(
            cac / acv,
            3,
        )

    return result


# ================================================================
# MASTER ANALYSIS
# ================================================================

def analyze_financials(
    evidence_store: List[Dict[str, Any]],
) -> Dict[str, Any]:

    return {
        "revenue": calculate_revenue_metrics(
            evidence_store
        ),
        "customers": calculate_customer_metrics(
            evidence_store
        ),
        "margins": calculate_margin_metrics(
            evidence_store
        ),
        "cash": calculate_cash_metrics(
            evidence_store
        ),
        "operating": calculate_operating_metrics(
            evidence_store
        ),
    }


# ================================================================
# SUMMARY
# ================================================================

def summarize_financials(
    financials: Dict[str, Any],
) -> Dict[str, Any]:

    summary = {}

    revenue = financials.get(
        "revenue",
        {},
    )

    customers = financials.get(
        "customers",
        {},
    )

    margins = financials.get(
        "margins",
        {},
    )

    cash = financials.get(
        "cash",
        {},
    )

    operating = financials.get(
        "operating",
        {},
    )

    if revenue.get(
        "current_revenue_cr"
    ) is not None:

        summary[
            "Revenue"
        ] = (
            f"₹{revenue['current_revenue_cr']:.2f} Cr"
        )

    if customers.get(
        "active_customers"
    ) is not None:

        summary[
            "Active Customers"
        ] = (
            f"{customers['active_customers']:,.0f}"
        )

    if margins.get(
        "calculated_ebitda_margin_pct"
    ) is not None:

        summary[
            "EBITDA Margin"
        ] = (
            f"{margins['calculated_ebitda_margin_pct']:.1f}%"
        )

    if operating.get(
        "nrr_pct"
    ) is not None:

        summary[
            "NRR"
        ] = (
            f"{operating['nrr_pct']:.1f}%"
        )

    if cash.get(
        "estimated_runway_months"
    ) is not None:

        summary[
            "Estimated Runway"
        ] = (
            f"{cash['estimated_runway_months']:.1f} months"
        )

    return summary