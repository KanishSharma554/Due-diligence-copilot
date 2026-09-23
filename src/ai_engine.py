from __future__ import annotations

import json
import os
import time
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

import urllib.error
import urllib.request


# ================================================================
# ENVIRONMENT
# ================================================================

# Resolve paths from this module, not from the directory Streamlit was
# launched in.  This makes the app reliable on Windows and from VS Code.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
_CACHE_FILE = _PROJECT_ROOT / ".ai_analysis_cache.json"

load_dotenv(dotenv_path=_ENV_FILE, override=True)


# ================================================================
# CONFIGURATION
# ================================================================

DEFAULT_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.7-flash",
)

# Bump this whenever a prompt (system or user) changes materially, so a
# stale cached AI response from an older prompt version is never reused
# silently. This is combined into the cache key below.
_PROMPT_VERSION = "2026-09-01.1"

# Cache successful AI analysis for identical evidence so repeated
# Streamlit reruns do not consume free-tier API quota unnecessarily.
_AI_ANALYSIS_CACHE: Dict[str, Dict[str, Any]] = {}
_LAST_AI_ERROR: Optional[str] = None


def _load_persistent_cache() -> Dict[str, Dict[str, Any]]:
    """Load successful AI analyses from disk so Streamlit restarts do not
    force another Gemini request for the same diligence dataset."""
    try:
        if not _CACHE_FILE.exists():
            return {}
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"AI CACHE LOAD WARNING: {type(exc).__name__}: {exc}")
        return {}


def _save_persistent_cache(cache: Dict[str, Dict[str, Any]]) -> None:
    """Persist only generated analysis; never persist the API key."""
    try:
        tmp = _CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_CACHE_FILE)
    except Exception as exc:
        print(f"AI CACHE SAVE WARNING: {type(exc).__name__}: {exc}")


def _analysis_cache_key(
    evidence_store: List[Dict[str, Any]],
    reconciliations: List[Dict[str, Any]],
    financials: Dict[str, Any],
    risks: List[Dict[str, Any]],
) -> str:
    payload = _json_string({
        "evidence": evidence_store,
        "reconciliations": reconciliations,
        "financials": financials,
        "risks": risks,
        # Including the model + prompt version means switching models or
        # editing a prompt automatically invalidates old cached AI output
        # instead of silently reusing a response generated under different
        # instructions.
        "model": DEFAULT_MODEL,
        "prompt_version": _PROMPT_VERSION,
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ================================================================
# GEMINI REST CLIENT
# ================================================================

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)


def get_last_ai_error() -> Optional[str]:
    """Return the last Gemini error for diagnostics instead of hiding it."""
    return _LAST_AI_ERROR


def classify_ai_error(error_text: Optional[str]) -> Optional[str]:
    """Map a raw Gemini error string into a short, stable category label.

    This never changes control flow or retry behaviour — it only turns the
    raw message already captured in `_LAST_AI_ERROR` / result["ai_error"]
    into a label the UI can show at a glance, with the full technical
    detail still available underneath. The API key itself is never part
    of this string, so it is always safe to display.
    """
    if not error_text:
        return None

    text = error_text.lower()

    if "gemini_api_key was not found" in text:
        return "No API key configured"
    if "no candidates" in text or "empty text response" in text:
        return "Gemini responded but returned no usable text"
    if any(m in text for m in ("401", "unauthenticated", "api key not valid", "api_key_invalid")):
        return "Authentication failed — API key rejected"
    if any(m in text for m in ("403", "permission_denied", "permission denied")):
        return "Permission denied — key lacks access to this model/API"
    if any(m in text for m in ("404", "not_found", "not found")):
        return "Model or endpoint not found"
    if any(m in text for m in ("429", "resource_exhausted", "rate limit", "quota")):
        return "Rate limited or quota exceeded"
    if any(m in text for m in ("500", "503", "internal", "unavailable", "deadline exceeded")):
        return "Gemini server error (temporary)"
    if "network error" in text:
        return "Network error — could not reach Gemini"
    return "AI request failed"


def _gemini_request(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
) -> Optional[str]:
    """Call Gemini directly over the documented REST API.

    This deliberately uses the x-goog-api-key header instead of relying on
    the installed google-genai SDK. That makes the demo independent of local
    SDK versions and supports the current AI Studio auth-key format.
    """
    global _LAST_AI_ERROR

    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        _LAST_AI_ERROR = f"GEMINI_API_KEY was not found. Expected .env at: {_ENV_FILE}"
        return None

    url = GEMINI_ENDPOINT.format(model=DEFAULT_MODEL)
    payload = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}],
        },
        "contents": [{
            "role": "user",
            "parts": [{"text": user_prompt}],
        }],
        "generationConfig": {
            "temperature": temperature,
            "candidateCount": 1,
        },
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8")
            body = json.loads(raw)

        candidates = body.get("candidates") or []
        if not candidates:
            _LAST_AI_ERROR = "Gemini returned no candidates."
            return None

        parts = ((candidates[0].get("content") or {}).get("parts") or [])
        text = "\n".join(
            str(part.get("text", ""))
            for part in parts
            if part.get("text")
        ).strip()

        if not text:
            _LAST_AI_ERROR = "Gemini returned an empty text response."
            return None

        _LAST_AI_ERROR = None
        return text

    except urllib.error.HTTPError as exc:
        try:
            raw_error = exc.read().decode("utf-8", errors="replace")
        except Exception:
            raw_error = str(exc)
        try:
            parsed = json.loads(raw_error)
            message = parsed.get("error", {}).get("message") or raw_error
            status = parsed.get("error", {}).get("status")
            details = parsed.get("error", {}).get("details")
            detail_text = ""
            if details:
                detail_text = f" | details={json.dumps(details, ensure_ascii=False)}"
            _LAST_AI_ERROR = (
                f"Gemini HTTP {exc.code}"
                f" ({status or 'HTTP error'}): {message}{detail_text}"
            )
        except Exception:
            _LAST_AI_ERROR = f"Gemini HTTP {exc.code}: {raw_error}"
        print(f"GEMINI REST ERROR: {_LAST_AI_ERROR}")
        return None
    except urllib.error.URLError as exc:
        _LAST_AI_ERROR = f"Gemini network error: {exc.reason}"
        print(f"GEMINI REST ERROR: {_LAST_AI_ERROR}")
        return None
    except Exception as exc:
        _LAST_AI_ERROR = f"Gemini request failed: {type(exc).__name__}: {exc}"
        print(f"GEMINI REST ERROR: {_LAST_AI_ERROR}")
        return None


# ================================================================
# DATA PREPARATION
# ================================================================

def _compact_evidence(
    evidence_store: List[Dict[str, Any]],
    max_items: int = 80,
) -> List[Dict[str, Any]]:
    """
    Reduce evidence into a compact representation suitable
    for an LLM prompt.
    """

    compact = []

    for item in evidence_store[:max_items]:

        compact.append(
            {
                "file": item.get(
                    "file_name"
                ),
                "document_type": item.get(
                    "document_type"
                ),
                "field": item.get(
                    "field"
                ),
                "value": item.get(
                    "value"
                ),
                "confidence": item.get(
                    "confidence"
                ),
                "source": item.get(
                    "source_location"
                ),
                "context": item.get(
                    "context"
                ),
            }
        )

    return compact


def _compact_reconciliations(
    reconciliations: List[
        Dict[str, Any]
    ],
) -> List[Dict[str, Any]]:
    """
    Keep only information the model needs to explain
    cross-document discrepancies.
    """

    compact = []

    for item in reconciliations:

        compact.append(
            {
                "field": item.get(
                    "field_label"
                ),
                "severity": item.get(
                    "severity"
                ),
                "value_a": item.get(
                    "display_value_a"
                ),
                "value_b": item.get(
                    "display_value_b"
                ),
                "relative_difference_pct": item.get(
                    "relative_difference_pct"
                ),
                "source_a": item.get(
                    "source_a",
                    {},
                ).get(
                    "file_name"
                ),
                "source_b": item.get(
                    "source_b",
                    {},
                ).get(
                    "file_name"
                ),
            }
        )

    return compact


def _compact_risks(
    risks: List[
        Dict[str, Any]
    ],
) -> List[Dict[str, Any]]:
    """
    Keep risk register concise for the LLM.
    """

    compact = []

    for risk in risks:

        compact.append(
            {
                "risk_id": risk.get(
                    "risk_id"
                ),
                "title": risk.get(
                    "title"
                ),
                "category": risk.get(
                    "category"
                ),
                "severity": risk.get(
                    "severity"
                ),
                "description": risk.get(
                    "description"
                ),
                "implication": risk.get(
                    "implication"
                ),
                "recommendation": risk.get(
                    "recommendation"
                ),
            }
        )

    return compact


# ================================================================
# SAFE JSON
# ================================================================

def _json_string(
    value: Any,
) -> str:
    """
    Convert Python data to readable JSON.
    """

    return json.dumps(
        value,
        indent=2,
        ensure_ascii=False,
        default=str,
    )


# ================================================================
# FALLBACK SUMMARY
# ================================================================

def _fallback_executive_summary(
    financials: Dict[str, Any],
    reconciliations: List[
        Dict[str, Any]
    ],
    risks: List[
        Dict[str, Any]
    ],
) -> str:
    """
    Deterministic fallback when no AI API is available.
    """

    high_risks = [
        r
        for r in risks
        if r.get("severity") == "High"
    ]

    medium_risks = [
        r
        for r in risks
        if r.get("severity") == "Medium"
    ]

    revenue = (
        financials
        .get("revenue", {})
        .get("current_revenue_cr")
    )

    customers = (
        financials
        .get("customers", {})
        .get("active_customers")
    )

    nrr = (
        financials
        .get("operating", {})
        .get("nrr_pct")
    )

    runway = (
        financials
        .get("cash", {})
        .get("estimated_runway_months")
    )

    parts = []

    if revenue is not None:
        parts.append(
            f"Current revenue evidence indicates approximately "
            f"₹{revenue:.2f} Cr."
        )

    if customers is not None:
        parts.append(
            f"The operating data supports approximately "
            f"{customers:,.0f} active customers."
        )

    if nrr is not None:
        parts.append(
            f"Reported NRR is {nrr:.1f}%."
        )

    if runway is not None:
        parts.append(
            f"Based on current bank cash and burn, estimated "
            f"runway is approximately {runway:.1f} months."
        )

    if reconciliations:
        parts.append(
            f"The review identified {len(reconciliations)} "
            f"cross-document discrepancy{'ies' if len(reconciliations) != 1 else ''}."
        )

    if high_risks:
        titles = ", ".join(
            r.get("title", "")
            for r in high_risks[:3]
        )

        parts.append(
            f"Highest-priority areas include: {titles}."
        )

    elif medium_risks:
        titles = ", ".join(
            r.get("title", "")
            for r in medium_risks[:3]
        )

        parts.append(
            f"Key areas requiring follow-up include: {titles}."
        )

    return " ".join(parts)


# ================================================================
# GEMINI CALL
# ================================================================

def _ask_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
) -> Optional[str]:
    """Call Gemini with bounded retry handling for transient failures."""
    global _LAST_AI_ERROR

    retry_delays = (1.0, 2.0, 4.0)

    for attempt, delay in enumerate(retry_delays, start=1):
        response = _gemini_request(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
        )
        if response:
            return response

        error_text = _LAST_AI_ERROR or "Unknown Gemini error"
        transient = any(
            marker.lower() in error_text.lower()
            for marker in (
                "429",
                "resource_exhausted",
                "rate limit",
                "rate_limit",
                "408",
                "503",
                "service unavailable",
                "temporarily unavailable",
                "deadline exceeded",
                "timeout",
            )
        )

        if not transient:
            return None

        if attempt < len(retry_delays):
            time.sleep(delay)

    return None


# ================================================================
# EXECUTIVE SUMMARY
# ================================================================

def generate_executive_summary(
    evidence_store: List[
        Dict[str, Any]
    ],
    reconciliations: List[
        Dict[str, Any]
    ],
    financials: Dict[str, Any],
    risks: List[
        Dict[str, Any]
    ],
) -> Dict[str, Any]:
    """
    Generate an analyst-style executive diligence summary.
    """

    fallback = _fallback_executive_summary(
        financials=financials,
        reconciliations=reconciliations,
        risks=risks,
    )

    system_prompt = """
You are an experienced transaction due-diligence analyst.

Your task is to interpret structured diligence evidence.

Important rules:

1. Never invent facts.
2. Never change numerical values.
3. Treat deterministic calculations as authoritative.
4. Distinguish clearly between evidence, interpretation,
   and areas requiring management confirmation.
5. Do not claim that a discrepancy proves fraud or wrongdoing.
6. Use concise professional transaction-advisory language.
7. Prioritize material issues.
8. Mention source documents when useful.
9. If evidence is insufficient, explicitly say so.
10. Do not repeat the entire dataset.
"""

    user_prompt = f"""
Prepare a concise executive diligence summary based only on
the structured information below.

STRUCTURED FINANCIAL OUTPUT:
{_json_string(financials)}

CROSS-DOCUMENT RECONCILIATIONS:
{_json_string(
    _compact_reconciliations(
        reconciliations
    )
)}

RISK REGISTER:
{_json_string(
    _compact_risks(
        risks
    )
)}

EVIDENCE:
{_json_string(
    _compact_evidence(
        evidence_store
    )
)}

Return:

1. Overall assessment — 2 to 4 sentences.
2. Key positives — 3 concise points.
3. Key concerns — 3 to 5 concise points.
4. Immediate diligence priorities — 3 concise actions.

Keep the answer factual and analytical.
"""

    llm_response = _ask_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.2,
    )

    if llm_response:

        return {
            "available": True,
            "source": "AI",
            "text": llm_response,
        }

    return {
        "available": False,
        "source": "Deterministic fallback",
        "text": fallback,
        "error": get_last_ai_error(),
    }


# ================================================================
# MANAGEMENT QUESTIONS
# ================================================================

def generate_management_questions(
    evidence_store: List[
        Dict[str, Any]
    ],
    reconciliations: List[
        Dict[str, Any]
    ],
    risks: List[
        Dict[str, Any]
    ],
) -> List[str]:
    """
    Generate focused questions for management.

    Questions are grounded in identified issues.
    """

    fallback_questions = []

    for item in reconciliations:

        field = item.get(
            "field_label",
            "Metric",
        )

        value_a = item.get(
            "display_value_a",
            "",
        )

        value_b = item.get(
            "display_value_b",
            "",
        )

        fallback_questions.append(
            (
                f"Please reconcile the {field} difference "
                f"between {value_a} and {value_b}, including "
                f"the applicable reporting date and source system."
            )
        )

    for risk in risks:

        if len(
            fallback_questions
        ) >= 8:
            break

        title = risk.get(
            "title",
            "identified issue",
        )

        recommendation = risk.get(
            "recommendation",
            "",
        )

        fallback_questions.append(
            (
                f"Please provide an update on {title.lower()} "
                f"and confirm the remediation or supporting "
                f"documentation available. {recommendation}"
            )
        )

    # Deduplicate while preserving order.
    fallback_questions = list(
        dict.fromkeys(
            fallback_questions
        )
    )

    fallback_questions = (
        fallback_questions[:8]
    )

    system_prompt = """
You are a transaction due-diligence analyst preparing management
questions.

Rules:

- Every question must be grounded in the supplied evidence.
- Prioritize material discrepancies and risks.
- Ask clear, specific questions that management can answer.
- Do not accuse the company of wrongdoing.
- Do not invent missing facts.
- Avoid generic questions such as "Tell us about the company."
- Where useful, request the specific document, date, reconciliation,
  definition, or supporting schedule needed.
"""

    user_prompt = f"""
Generate 6 to 8 high-value management diligence questions.

RECONCILIATIONS:
{_json_string(
    _compact_reconciliations(
        reconciliations
    )
)}

RISKS:
{_json_string(
    _compact_risks(
        risks
    )
)}

EVIDENCE:
{_json_string(
    _compact_evidence(
        evidence_store
    )
)}

Return only a numbered list of questions.
"""

    llm_response = _ask_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.3,
    )

    if not llm_response:
        return fallback_questions

    lines = []

    for line in llm_response.splitlines():

        cleaned = line.strip()

        if not cleaned:
            continue

        # Remove common numbering styles.
        cleaned = cleaned.lstrip(
            "0123456789.-) "
        )

        if cleaned:
            lines.append(
                cleaned
            )

    return lines[:10] or fallback_questions


# ================================================================
# RISK EXPLANATION
# ================================================================

def explain_risk(
    risk: Dict[str, Any],
) -> str:
    """
    Generate a short analyst explanation for one risk.
    """

    fallback = (
        risk.get(
            "description",
            "",
        )
        + " "
        + risk.get(
            "implication",
            "",
        )
    ).strip()

    system_prompt = """
You are a transaction advisory analyst.

Explain the supplied diligence risk in 2 concise paragraphs.

Use only the supplied information.
Do not invent facts.
Do not exaggerate.
Explain:
1. What the evidence says.
2. Why it matters in diligence.
"""

    user_prompt = f"""
RISK:
{_json_string(risk)}

Write a concise analyst explanation.
"""

    response = _ask_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.2,
    )

    return response or fallback


# ================================================================
# ASK DILIGENCE ROOM
# ================================================================

def ask_diligence_room(
    question: str,
    evidence_store: List[
        Dict[str, Any]
    ],
    reconciliations: List[
        Dict[str, Any]
    ],
    financials: Dict[str, Any],
    risks: List[
        Dict[str, Any]
    ],
) -> str:
    """
    Answer a diligence-room question using the available
    structured evidence.
    """

    if not question.strip():
        return (
            "Please enter a diligence question."
        )

    # If the model is unavailable or declines to answer, return a
    # useful evidence-bound response instead of exposing an internal
    # generation failure to the analyst.
    fallback = (
        "Insufficient evidence: the reviewed diligence materials do not "
        "provide enough information to answer this question conclusively. "
        "I will not infer or invent a value that is not supported by the "
        "available evidence. Review the relevant source documents and, "
        "where needed, request clarification from management."
    )

    system_prompt = """
You are the AI analyst inside a transaction due-diligence room.

Answer questions strictly from the supplied evidence.

Rules:

1. Do not invent information.
2. Do not infer unsupported facts.
3. Use deterministic financial outputs as authoritative.
4. Mention source documents when possible.
5. For discrepancies, present both values and explain that "
   "they require reconciliation.
6. If the evidence does not answer the question, say:
   "The reviewed documents do not provide sufficient evidence
   to answer this conclusively."
7. Keep responses concise but useful.
8. Separate observed facts from analyst interpretation.
9. If a requested metric, fact, or conclusion is not explicitly supported
   by the evidence, do not substitute a related metric for it. State that
   the evidence is insufficient and, where useful, mention what related
   metrics are actually available.
10. Never describe an API/model failure as an evidence finding.
"""

    user_prompt = f"""
QUESTION:
{question}

FINANCIAL OUTPUT:
{_json_string(financials)}

RECONCILIATIONS:
{_json_string(
    _compact_reconciliations(
        reconciliations
    )
)}

RISKS:
{_json_string(
    _compact_risks(
        risks
    )
)}

EVIDENCE:
{_json_string(
    _compact_evidence(
        evidence_store,
        max_items=120,
    )
)}

Answer the question in an analyst-style response.

Where useful, use:

Observed:
Interpretation:
Sources:
"""

    response = _ask_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.2,
    )

    return response or fallback


# ================================================================
# MASTER AI ANALYSIS
# ================================================================

def run_ai_analysis(
    evidence_store: List[Dict[str, Any]],
    reconciliations: List[Dict[str, Any]],
    financials: Dict[str, Any],
    risks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Run AI-assisted analysis, with caching for identical evidence.

    Re-running the same diligence session should not repeatedly consume
    free-tier Gemini quota. A new API request is made only when the
    underlying evidence/findings/financials change or no successful AI
    result exists yet.
    """

    cache_key = _analysis_cache_key(
        evidence_store,
        reconciliations,
        financials,
        risks,
    )

    # Check memory first, then the persistent cache. This is what makes
    # the demo resilient to Streamlit restarts/reloads.
    cached = _AI_ANALYSIS_CACHE.get(cache_key)
    if cached is None:
        persistent_cache = _load_persistent_cache()
        cached = persistent_cache.get(cache_key)
        if cached is not None:
            _AI_ANALYSIS_CACHE[cache_key] = cached

    if cached is not None:
        return cached

    summary = generate_executive_summary(
        evidence_store=evidence_store,
        reconciliations=reconciliations,
        financials=financials,
        risks=risks,
    )

    questions = generate_management_questions(
        evidence_store=evidence_store,
        reconciliations=reconciliations,
        risks=risks,
    )

    result = {
        "executive_summary": summary,
        "management_questions": questions,
        "ai_error": get_last_ai_error(),
        "ai_model": DEFAULT_MODEL,
    }

    # Cache only when the primary AI summary succeeded. If Gemini was
    # temporarily unavailable on the first run, a later rerun should
    # still be allowed to attempt a real AI call.
    if summary.get("source") == "AI":
        _AI_ANALYSIS_CACHE[cache_key] = result
        persistent_cache = _load_persistent_cache()
        persistent_cache[cache_key] = result
        _save_persistent_cache(persistent_cache)

    return result