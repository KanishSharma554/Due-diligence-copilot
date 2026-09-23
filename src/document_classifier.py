from __future__ import annotations

from typing import Any, Dict, List, Tuple
import re


# ================================================================
# DOCUMENT TYPES
# ================================================================

DOCUMENT_TYPES = [
    "Bank Statement",
    "Cap Table",
    "Customer / Operating Metrics",
    "Financial Model",
    "Investor Presentation",
    "Legal / Corporate Diligence",
    "Other",
]


# ================================================================
# CLASSIFICATION RULES
# ================================================================
#
# Each document type has:
#
#   strong      -> highly distinctive phrases
#   medium      -> useful supporting phrases
#   weak        -> generic supporting phrases
#
# The classifier uses document CONTENT, not filename.
# ================================================================

CLASSIFICATION_RULES = {

    "Bank Statement": {
        "strong": [
            "bank statement",
            "account number",
            "statement period",
            "account summary",
            "total credits",
            "total debits",
            "closing balance",
            "opening balance",
            "transaction date",
            "transaction details",
        ],
        "medium": [
            "debit",
            "credit",
            "withdrawal",
            "deposit",
            "bank",
            "account",
            "balance",
            "transaction",
        ],
        "weak": [
            "date",
            "amount",
            "description",
        ],
    },

    "Cap Table": {
        "strong": [
            "cap table",
            "capitalization table",
            "shareholding",
            "fully diluted",
            "founder ownership",
            "share capital",
            "shareholder",
            "number of shares",
            "ownership percentage",
        ],
        "medium": [
            "founder",
            "esop",
            "seed",
            "angel",
            "investor",
            "equity",
            "shares",
            "ownership",
            "dilution",
        ],
        "weak": [
            "percentage",
            "total",
        ],
    },

    "Customer / Operating Metrics": {
        "strong": [
            "customer metrics",
            "customer overview",
            "active customers",
            "customer concentration",
            "customer segmentation",
            "monthly metrics",
            "net revenue retention",
            "nrr",
            "churn",
            "customer count",
        ],
        "medium": [
            "customers",
            "arr",
            "acv",
            "cac",
            "retention",
            "segment",
            "automotive",
            "industrial",
            "customer",
        ],
        "weak": [
            "monthly",
            "revenue",
            "growth",
        ],
    },

    "Financial Model": {
        "strong": [
            "financial model",
            "profit and loss",
            "p&l",
            "gross profit",
            "gross margin",
            "ebitda",
            "ebitda margin",
            "net profit",
            "cash flow",
            "operating cash flow",
            "investing cash flow",
            "financing cash flow",
            "closing cash",
            "monthly burn",
            "revenue",
        ],
        "medium": [
            "financials",
            "income statement",
            "balance sheet",
            "cash flow",
            "revenue",
            "cogs",
            "profit",
            "loss",
            "expenses",
            "margin",
            "burn",
            "arr",
        ],
        "weak": [
            "fy23",
            "fy24",
            "fy25",
            "year",
            "amount",
        ],
    },

    "Investor Presentation": {
        "strong": [
            "investor presentation",
            "investor deck",
            "investment highlights",
            "fundraise",
            "fundraising",
            "target raise",
            "use of funds",
            "traction",
            "enterprise customers",
            "market opportunity",
            "problem",
            "solution",
            "product",
            "team",
        ],
        "medium": [
            "arr",
            "nrr",
            "gross margin",
            "cac",
            "acv",
            "customers",
            "growth",
            "founders",
            "funding",
            "capital raised",
            "market",
        ],
        "weak": [
            "company",
            "business",
            "technology",
        ],
    },

    "Legal / Corporate Diligence": {
        "strong": [
            "legal diligence",
            "corporate diligence",
            "litigation",
            "intellectual property",
            "ip assignment",
            "data processing",
            "regulatory",
            "compliance",
            "legal proceedings",
            "contracts",
            "corporate records",
            "material contracts",
        ],
        "medium": [
            "legal",
            "lawsuit",
            "dispute",
            "privacy",
            "license",
            "agreement",
            "contract",
            "regulation",
            "corporate",
            "compliance",
        ],
        "weak": [
            "company",
            "management",
            "review",
            "status",
        ],
    },
}


# ================================================================
# TEXT NORMALIZATION
# ================================================================

def _normalize_text(
    text: str,
) -> str:
    """
    Normalize document text for classification.
    """

    if not text:
        return ""

    text = text.lower()

    text = text.replace(
        "\x00",
        " ",
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


# ================================================================
# PHRASE MATCHING
# ================================================================

def _count_matches(
    text: str,
    phrases: List[str],
) -> Tuple[int, List[str]]:
    """
    Count unique matching phrases.

    Returns:
        count
        matched phrases
    """

    matched = []

    for phrase in phrases:

        normalized_phrase = phrase.lower().strip()

        if not normalized_phrase:
            continue

        if normalized_phrase in text:
            matched.append(
                phrase
            )

    return (
        len(matched),
        matched,
    )


# ================================================================
# DOCUMENT SCORE
# ================================================================

def _score_document_type(
    text: str,
    rule: Dict[str, List[str]],
) -> Dict[str, Any]:
    """
    Score a document type using weighted content matches.

    Strong phrase = 5 points
    Medium phrase = 2 points
    Weak phrase = 1 point

    The score is then converted into a practical confidence
    value for a rule-based classifier.
    """

    strong_count, strong_matches = _count_matches(
        text,
        rule.get(
            "strong",
            [],
        ),
    )

    medium_count, medium_matches = _count_matches(
        text,
        rule.get(
            "medium",
            [],
        ),
    )

    weak_count, weak_matches = _count_matches(
        text,
        rule.get(
            "weak",
            [],
        ),
    )

    raw_score = (
        strong_count * 5
        + medium_count * 2
        + weak_count
    )

    return {
        "raw_score": raw_score,
        "strong_count": strong_count,
        "medium_count": medium_count,
        "weak_count": weak_count,
        "strong_matches": strong_matches,
        "medium_matches": medium_matches,
        "weak_matches": weak_matches,
    }


# ================================================================
# CONFIDENCE CALCULATION
# ================================================================

def _calculate_confidence(
    winning_score: float,
    second_score: float,
    strong_count: int,
) -> float:
    """
    Convert rule-based evidence into a human-readable confidence.

    This is NOT a statistical probability.

    We combine:

    1. Absolute evidence strength
    2. Margin over the second-best class
    3. Presence of distinctive strong matches
    """

    if winning_score <= 0:
        return 0.05

    # ------------------------------------------------------------
    # Absolute evidence component
    #
    # 0 points  -> ~0.20
    # 10 points -> strong
    # 20+       -> very strong
    # ------------------------------------------------------------

    absolute_component = min(
        winning_score / 20.0,
        1.0,
    )

    # ------------------------------------------------------------
    # Separation from second-best class.
    # ------------------------------------------------------------

    if winning_score > 0:

        separation = (
            winning_score
            - second_score
        ) / winning_score

        separation_component = max(
            0.0,
            min(
                separation,
                1.0,
            ),
        )

    else:
        separation_component = 0.0

    # ------------------------------------------------------------
    # Strong distinctive evidence.
    # ------------------------------------------------------------

    strong_component = min(
        strong_count / 3.0,
        1.0,
    )

    # ------------------------------------------------------------
    # Weighted combination.
    # ------------------------------------------------------------

    confidence = (
        0.45 * absolute_component
        + 0.35 * separation_component
        + 0.20 * strong_component
    )

    # ------------------------------------------------------------
    # Practical presentation floor.
    #
    # We don't want a document with 3-4 highly distinctive
    # matches to display something absurdly low like 35%.
    #
    # Still preserve low confidence when there is genuinely
    # little evidence.
    # ------------------------------------------------------------

    if (
        winning_score >= 15
        and strong_count >= 2
    ):
        confidence = max(
            confidence,
            0.90,
        )

    elif (
        winning_score >= 10
        and strong_count >= 1
    ):
        confidence = max(
            confidence,
            0.80,
        )

    elif winning_score >= 6:
        confidence = max(
            confidence,
            0.65,
        )

    return round(
        min(
            max(
                confidence,
                0.05,
            ),
            0.99,
        ),
        2,
    )


# ================================================================
# SINGLE DOCUMENT CLASSIFICATION
# ================================================================

def classify_document_rule_based(
    document: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Classify one document based on its content.

    The filename is deliberately ignored.
    """

    file_name = document.get(
        "file_name",
        "Unknown",
    )

    raw_text = document.get(
        "text",
        "",
    )

    text = _normalize_text(
        raw_text
    )

    if not text:

        return {
            "file_name": file_name,
            "file_type": document.get(
                "file_type",
                "unknown",
            ),
            "document_type": "Other",
            "classification_score": 0,
            "classification_confidence": 0.05,
            "all_scores": {
                document_type: 0
                for document_type in DOCUMENT_TYPES
            },
            "matched_keywords": [],
        }

    scores: Dict[
        str,
        Dict[str, Any]
    ] = {}

    for document_type, rule in (
        CLASSIFICATION_RULES.items()
    ):

        scores[
            document_type
        ] = _score_document_type(
            text,
            rule,
        )

    # ------------------------------------------------------------
    # Rank document classes.
    # ------------------------------------------------------------

    ranked = sorted(
        scores.items(),
        key=lambda x: (
            x[1]["raw_score"],
            x[1]["strong_count"],
            x[1]["medium_count"],
        ),
        reverse=True,
    )

    best_type = ranked[0][0]

    best_details = ranked[0][1]

    best_score = float(
        best_details["raw_score"]
    )

    second_score = (
        float(
            ranked[1][1]["raw_score"]
        )
        if len(ranked) > 1
        else 0.0
    )

    # ------------------------------------------------------------
    # If no meaningful evidence exists, return Other.
    # ------------------------------------------------------------

    if best_score <= 0:

        return {
            "file_name": file_name,
            "file_type": document.get(
                "file_type",
                "unknown",
            ),
            "document_type": "Other",
            "classification_score": 0,
            "classification_confidence": 0.05,
            "all_scores": {
                document_type: data["raw_score"]
                for document_type, data
                in scores.items()
            },
            "matched_keywords": [],
        }

    confidence = _calculate_confidence(
        winning_score=best_score,
        second_score=second_score,
        strong_count=best_details[
            "strong_count"
        ],
    )

    matched_keywords = (
        best_details[
            "strong_matches"
        ]
        + best_details[
            "medium_matches"
        ]
        + best_details[
            "weak_matches"
        ]
    )

    return {
        "file_name": file_name,
        "file_type": document.get(
            "file_type",
            "unknown",
        ),
        "document_type": best_type,
        "classification_score": best_score,
        "classification_confidence": confidence,
        "all_scores": {
            document_type: data["raw_score"]
            for document_type, data
            in scores.items()
        },
        "matched_keywords": matched_keywords,
    }


# ================================================================
# CLASSIFY ALL DOCUMENTS
# ================================================================

def classify_documents(
    documents: List[
        Dict[str, Any]
    ],
) -> List[
    Dict[str, Any]
]:
    """
    Classify every extracted document.
    """

    results = []

    for document in documents:

        try:

            result = classify_document_rule_based(
                document
            )

        except Exception as exc:

            result = {
                "file_name": document.get(
                    "file_name",
                    "Unknown",
                ),
                "file_type": document.get(
                    "file_type",
                    "unknown",
                ),
                "document_type": "Other",
                "classification_score": 0,
                "classification_confidence": 0.05,
                "all_scores": {
                    document_type: 0
                    for document_type
                    in DOCUMENT_TYPES
                },
                "matched_keywords": [],
                "classification_error": str(
                    exc
                ),
            }

        results.append(
            result
        )

    return results