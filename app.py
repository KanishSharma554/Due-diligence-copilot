from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import plotly.graph_objects as go
import streamlit as st

# ----------------------------------------------------------------------------
# Make sure `src/` resolves regardless of the working directory Streamlit was
# launched from.
# ----------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

BACKEND_IMPORT_ERROR: Optional[str] = None
try:
    from src.document_extractor import extract_all_documents
    from src.document_classifier import classify_documents
    from src.evidence_engine import build_evidence_store, summarize_evidence_store
    from src.reconciliation_engine import reconcile_evidence, summarize_reconciliations
    from src.financial_engine import analyze_financials
    from src.risk_engine import build_risk_register, summarize_risk_register
    from src.ai_engine import (
        run_ai_analysis,
        explain_risk,
        ask_diligence_room,
        classify_ai_error,
    )
except Exception as exc:  # noqa: BLE001 - we want to surface any import problem
    BACKEND_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


# ============================================================================
# PAGE CONFIGURATION
# ============================================================================

st.set_page_config(
    page_title="Due Diligence Copilot",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

NAV_ITEMS = [
    "Overview",
    "Financials",
    "Risk Flags",
    "Questions",
    "Ask Diligence Room",
    "Documents",
    "Settings",
]

CATEGORY_ACCENT = {
    "Financial": "indigo",
    "Commercial": "violet",
    "Liquidity": "teal",
    "Legal / IP": "slate",
    "Legal / Compliance": "slate",
    "Ownership": "violet",
    "Profitability": "warning",
    "Reconciliation": "indigo",
}
DEFAULT_CATEGORY_ACCENT = "slate"

EXTENSION_LABELS = {
    ".pdf": "PDF Document",
    ".xlsx": "Excel Workbook",
    ".xls": "Excel Workbook",
    ".pptx": "PowerPoint Presentation",
    ".ppt": "PowerPoint Presentation",
}

DASH = "—"


# ============================================================================
# SESSION STATE
# ============================================================================

def init_session_state() -> None:
    defaults = {
        "page": "Overview",
        "work_dir": None,
        "documents": None,
        "classifications": None,
        "evidence_store": None,
        "reconciliations": None,
        "financials": None,
        "risks": None,
        "ai_analysis": None,
        "analysis_complete": False,
        "analysis_error": None,
        "analysis_traceback": None,
        "risk_explanations": {},
        "ask_query": "",
        "ask_result": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _rerun() -> None:
    """Trigger a rerun in a way that is compatible across Streamlit versions."""
    if hasattr(st, "rerun"):
        st.rerun()
    else:  # pragma: no cover - fallback for older Streamlit releases
        st.experimental_rerun()


def reset_analysis(delete_files: bool = True) -> None:
    """Clear all analysis state and, optionally, the temporary work directory."""
    if delete_files:
        work_dir = st.session_state.get("work_dir")
        if work_dir and Path(work_dir).exists():
            shutil.rmtree(work_dir, ignore_errors=True)
        st.session_state.work_dir = None

    for key in (
        "documents",
        "classifications",
        "evidence_store",
        "reconciliations",
        "financials",
        "risks",
        "ai_analysis",
    ):
        st.session_state[key] = None

    st.session_state.analysis_complete = False
    st.session_state.analysis_error = None
    st.session_state.analysis_traceback = None
    st.session_state.risk_explanations = {}
    st.session_state.ask_query = ""
    st.session_state.ask_result = None
    st.session_state.page = "Overview"


init_session_state()


# ============================================================================
# FORMATTING HELPERS
# ============================================================================

def safe_get(d: Optional[Dict[str, Any]], *keys: str, default: Any = None) -> Any:
    """Safely walk a chain of nested dict lookups, returning `default` on any miss."""
    current: Any = d
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def fmt_cr(value: Optional[float]) -> str:
    if value is None:
        return DASH
    try:
        return f"₹{float(value):.2f} Cr"
    except (TypeError, ValueError):
        return DASH


def fmt_lakh(value: Optional[float]) -> str:
    if value is None:
        return DASH
    try:
        return f"₹{float(value):.1f} L"
    except (TypeError, ValueError):
        return DASH


def fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return DASH
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return DASH


def fmt_num(value: Optional[float]) -> str:
    if value is None:
        return DASH
    try:
        value = float(value)
        if value == int(value):
            return f"{int(value):,}"
        return f"{value:,.1f}"
    except (TypeError, ValueError):
        return DASH


def fmt_months(value: Optional[float]) -> str:
    if value is None:
        return DASH
    try:
        return f"{float(value):.1f} months"
    except (TypeError, ValueError):
        return DASH


def fmt_bytes(n: Optional[int]) -> str:
    if not n:
        return "0 KB"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def fmt_generic(value: Any) -> str:
    if value is None or value == "":
        return DASH
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def format_ai_narrative_html(text: str) -> str:
    """Turn the model's semi-Markdown narrative into clean, controlled HTML.

    The AI is asked for a numbered-section structure (e.g. "1. Overall
    assessment", "2. Key positives", ...) and typically wraps emphasis in
    **bold** and source filenames in `backticks`. Handing that raw text to
    st.markdown(unsafe_allow_html=True) inside a <div> produces inconsistent
    results (stray "#" characters, ad-hoc <code> blocks) because Streamlit's
    Markdown engine and our own HTML wrapper can each partially interpret it.

    This function does the conversion itself, deterministically, so the
    executive summary always renders as tidy section headings, paragraphs,
    and bullet lists regardless of exactly how the model formatted its
    response.
    """
    import html as _html

    if not text:
        return ""

    # Drop a redundant document-level title such as "### Executive
    # Diligence Summary" — the card already carries its own label.
    lines = text.replace("\r\n", "\n").split("\n")
    lines = [
        line
        for line in lines
        if not re.match(r"^\s*#{0,6}\s*executive.*summary\s*$", line.strip(), flags=re.IGNORECASE)
    ]

    def _inline(segment: str) -> str:
        segment = _html.escape(segment)
        segment = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", segment)
        segment = re.sub(r"`([^`]+)`", r'<span class="cite-chip">\1</span>', segment)
        return segment

    section_re = re.compile(r"^#{0,6}\s*\d+[.)]\s+(.+?)\s*$")
    bullet_re = re.compile(r"^[-*•]\s+(.+)$")

    html_parts: List[str] = []
    bullet_buffer: List[str] = []

    def _flush_bullets() -> None:
        if bullet_buffer:
            items = "".join(f"<li>{_inline(item)}</li>" for item in bullet_buffer)
            html_parts.append(f'<ul class="exec-bullet-list">{items}</ul>')
            bullet_buffer.clear()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        section_match = section_re.match(line)
        bullet_match = bullet_re.match(line)

        if section_match:
            _flush_bullets()
            title = section_match.group(1).strip().rstrip(":")
            title = title[:1].upper() + title[1:] if title else title
            html_parts.append(f'<div class="exec-section-title">{_html.escape(title)}</div>')
        elif bullet_match:
            bullet_buffer.append(bullet_match.group(1))
        else:
            _flush_bullets()
            # Strip any stray leading "#" the model added to a plain line.
            line = re.sub(r"^#{1,6}\s*", "", line)
            html_parts.append(f'<p class="exec-para">{_inline(line)}</p>')

    _flush_bullets()
    return "".join(html_parts)


def severity_class(severity: Optional[str]) -> str:
    if not severity:
        return "low"
    s = severity.strip().lower()
    return s if s in ("high", "medium", "low") else "low"


def category_accent(category: Optional[str]) -> str:
    return CATEGORY_ACCENT.get(category or "", DEFAULT_CATEGORY_ACCENT)


# ============================================================================
# GLOBAL CSS
# ============================================================================

CUSTOM_CSS = """
<style>
:root {
    --bg: #F7F7F4;
    --surface: #FFFFFF;
    --border: #E6E5E1;
    --border-strong: #D8D7D2;
    --text-primary: #1B2233;
    --text-secondary: #6B7280;
    --text-muted: #9AA0AC;
    --accent: #3B4FA0;
    --accent-soft: #EEF0FA;
    --accent-strong: #2C3C82;
    --teal: #0F7A82;
    --teal-soft: #E8F4F4;
    --violet: #6E4FA0;
    --violet-soft: #F1EDF9;
    --slate: #47607A;
    --slate-soft: #EBF0F4;
    --success: #1E8E5A;
    --success-soft: #E7F5EC;
    --warning: #B26A00;
    --warning-soft: #FDF3E2;
    --danger: #B3261E;
    --danger-soft: #FBEAE8;
    --radius-sm: 8px;
    --radius-md: 12px;
    --radius-lg: 16px;
}

html, body, [class*="css"] {
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.stApp, [data-testid="stAppViewContainer"] {
    background: var(--bg) !important;
}
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header[data-testid="stHeader"] {background: transparent;}

h1, h2, h3, h4, h5, h6,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {
    color: var(--text-primary) !important;
}

.block-container {
    padding-top: 1.6rem;
    padding-bottom: 3rem;
    max-width: 1180px;
}

/* ---------- Sidebar ---------- */
section[data-testid="stSidebar"] {
    background: var(--surface);
    border-right: 1px solid var(--border);
}
section[data-testid="stSidebar"] > div { padding-top: 1.4rem; }
.sidebar-brand {
    padding: 0 0.9rem 1.1rem 0.9rem;
    border-bottom: 1px solid var(--border);
    margin-bottom: 0.9rem;
}
.sidebar-brand-title {
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.01em;
    margin: 0;
    line-height: 1.3;
}
.sidebar-brand-sub {
    font-size: 0.64rem;
    font-weight: 600;
    color: var(--accent);
    letter-spacing: 0.1em;
    margin-top: 0.2rem;
}
.nav-section-label {
    font-size: 0.64rem;
    font-weight: 700;
    color: var(--text-muted);
    letter-spacing: 0.1em;
    padding: 0 0.9rem;
    margin: 0.4rem 0 0.4rem 0;
}
.nav-item {
    display: flex;
    align-items: center;
    gap: 0.55rem;
    padding: 0.55rem 0.9rem;
    margin: 0.08rem 0.55rem;
    border-radius: var(--radius-sm);
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--accent-strong);
    background: var(--accent-soft);
    border-left: 3px solid var(--accent);
}
.nav-item .nav-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--accent); flex-shrink: 0; }
section[data-testid="stSidebar"] div[data-testid="stButton"] { margin: 0.02rem 0.55rem; }
section[data-testid="stSidebar"] div[data-testid="stButton"] > button {
    width: 100%;
    display: flex;
    justify-content: flex-start;
    text-align: left;
    background: transparent;
    border: 1px solid transparent;
    border-left: 3px solid transparent;
    color: var(--text-secondary);
    font-size: 0.88rem;
    font-weight: 500;
    padding: 0.55rem 0.9rem;
    border-radius: var(--radius-sm);
    box-shadow: none;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {
    background: var(--accent-soft);
    color: var(--accent-strong);
    border-left: 3px solid var(--accent);
}
section[data-testid="stSidebar"] div[data-testid="stButton"] > button p {
    text-align: left; font-size: 0.88rem; font-weight: 500;
}
.workspace-card {
    margin: 1.1rem 0.55rem 0 0.55rem;
    padding: 0.85rem 0.9rem;
    background: var(--bg);
    border: 1px solid var(--border);
    border-top: 3px solid var(--accent);
    border-radius: var(--radius-md);
}
.workspace-label {
    font-size: 0.62rem; font-weight: 700; letter-spacing: 0.1em;
    color: var(--text-muted); margin-bottom: 0.25rem;
}
.workspace-value {
    font-size: 0.84rem; font-weight: 600; color: var(--text-primary);
    margin-bottom: 0.7rem; line-height: 1.3;
}
.status-row {
    display: flex; justify-content: space-between; align-items: center;
    padding-top: 0.5rem; border-top: 1px solid var(--border);
}
.status-row:first-of-type { border-top: none; padding-top: 0; }
.status-key { font-size: 0.62rem; font-weight: 700; letter-spacing: 0.08em; color: var(--text-muted); }
.status-val { font-size: 0.76rem; font-weight: 600; color: var(--text-primary); }
.status-val.ok { color: var(--success); }
.status-val.warn { color: var(--warning); }
.status-val.bad { color: var(--danger); }
.sidebar-note {
    margin: 0.9rem 0.55rem 0 0.55rem;
    font-size: 0.76rem;
    color: var(--text-muted);
    line-height: 1.5;
}

/* ---------- Top header ---------- */
.top-header {
    display: flex; justify-content: space-between; align-items: center;
    padding-bottom: 1.1rem; margin-bottom: 1.6rem; border-bottom: 1px solid var(--border);
    flex-wrap: wrap; gap: 0.6rem;
}
.top-header-left { display: flex; align-items: center; gap: 0.7rem; flex-wrap: wrap; }
.top-header-brand { font-size: 0.98rem; font-weight: 700; color: var(--text-primary); }
.top-header-divider { width: 1px; height: 16px; background: var(--border-strong); }
.top-header-section { font-size: 0.85rem; color: var(--text-secondary); font-weight: 500; }
.top-header-right { display: flex; align-items: center; gap: 0.6rem; }
.env-pill {
    display: inline-flex; align-items: center; gap: 0.4rem;
    font-size: 0.66rem; font-weight: 700; letter-spacing: 0.07em; color: var(--text-secondary);
    background: var(--surface); border: 1px solid var(--border-strong);
    padding: 0.3rem 0.65rem; border-radius: 999px; white-space: nowrap;
}
.env-pill .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--success); }
.env-pill.warn .dot { background: var(--warning); }

/* ---------- Page heading ---------- */
.eyebrow { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.12em; color: var(--accent); margin-bottom: 0.5rem; }
.page-title-row { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 0.8rem; margin-bottom: 0.35rem; }
.page-title { font-size: 1.85rem; font-weight: 700; color: var(--text-primary) !important; letter-spacing: -0.02em; margin: 0; }
.page-subtitle { font-size: 0.95rem; color: var(--text-secondary); margin-top: 0.35rem; margin-bottom: 1.5rem; max-width: 680px; }

.status-pill {
    display: inline-flex; align-items: center; gap: 0.45rem; font-size: 0.72rem; font-weight: 700;
    letter-spacing: 0.05em; padding: 0.4rem 0.85rem; border-radius: 999px; white-space: nowrap; margin-top: 0.3rem;
}
.status-pill .dot { width: 6px; height: 6px; border-radius: 50%; }
.status-pill.required { background: var(--warning-soft); color: var(--warning); }
.status-pill.required .dot { background: var(--warning); }
.status-pill.ready { background: var(--success-soft); color: var(--success); }
.status-pill.ready .dot { background: var(--success); }

.section-label { font-size: 0.78rem; font-weight: 700; letter-spacing: 0.08em; color: var(--text-primary); text-transform: uppercase; margin-bottom: 0.15rem; }
.section-sub { font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 1rem; }

.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 1.3rem 1.4rem; }
.empty-state {
    background: var(--success-soft); color: var(--success); border-radius: var(--radius-md);
    padding: 0.9rem 1.1rem; font-size: 0.88rem; font-weight: 500;
}
.empty-state.neutral { background: var(--bg); color: var(--text-secondary); border: 1px dashed var(--border-strong); }

/* ---------- Metric cards ---------- */
.metric-card {
    background: var(--surface); border: 1px solid var(--border); border-top: 3px solid var(--border-strong);
    border-radius: var(--radius-lg); padding: 1.1rem 1.2rem; height: 100%;
}
.metric-card.accent-indigo { border-top-color: var(--accent); }
.metric-card.accent-teal { border-top-color: var(--teal); }
.metric-card.accent-violet { border-top-color: var(--violet); }
.metric-card.accent-warning { border-top-color: var(--warning); }
.metric-card.accent-danger { border-top-color: var(--danger); }
.metric-label { font-size: 0.66rem; font-weight: 700; letter-spacing: 0.09em; color: var(--text-muted); margin-bottom: 0.5rem; }
.metric-value { font-size: 1.55rem; font-weight: 700; color: var(--text-primary); letter-spacing: -0.02em; line-height: 1.15; }
.metric-sub { font-size: 0.76rem; margin-top: 0.4rem; font-weight: 500; }
.metric-sub.positive { color: var(--success); }
.metric-sub.negative { color: var(--danger); }
.metric-sub.neutral { color: var(--text-secondary); }

/* ---------- Snapshot rows ---------- */
.snapshot-row { display: flex; justify-content: space-between; align-items: center; padding: 0.62rem 0; border-bottom: 1px solid var(--border); gap: 1rem; }
.snapshot-row:last-child { border-bottom: none; }
.snapshot-key { font-size: 0.82rem; color: var(--text-secondary); font-weight: 500; }
.snapshot-val { font-size: 0.86rem; color: var(--text-primary); font-weight: 600; text-align: right; }

/* ---------- Executive summary ---------- */
.exec-summary-card {
    background: var(--surface); border: 1px solid var(--border); border-left: 3px solid var(--accent);
    border-radius: var(--radius-lg); padding: 1.2rem 1.35rem; margin-bottom: 1.6rem;
}
.exec-summary-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.6rem; }
.exec-summary-label { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.09em; color: var(--text-muted); }
.exec-summary-text { font-size: 0.92rem; color: var(--text-primary); line-height: 1.65; }
.exec-section-title { font-size: 0.86rem; font-weight: 700; color: var(--accent-strong); margin: 1rem 0 0.4rem; }
.exec-section-title:first-child { margin-top: 0; }
.exec-para { font-size: 0.92rem; color: var(--text-primary); line-height: 1.65; margin: 0 0 0.55rem; }
.exec-bullet-list { margin: 0 0 0.6rem; padding-left: 1.2rem; }
.exec-bullet-list li { font-size: 0.92rem; color: var(--text-primary); line-height: 1.6; margin-bottom: 0.4rem; }
.cite-chip { display: inline-block; background: var(--bg); border: 1px solid var(--border); color: var(--text-secondary); font-size: 0.74rem; font-weight: 600; padding: 0.04rem 0.45rem; border-radius: 6px; margin: 0 0.1rem; white-space: nowrap; }
.source-badge { font-size: 0.66rem; font-weight: 700; letter-spacing: 0.06em; padding: 0.22rem 0.6rem; border-radius: 999px; }
.source-badge.ai { background: var(--accent-soft); color: var(--accent-strong); }
.source-badge.fallback { background: var(--slate-soft); color: var(--slate); }

/* ---------- Finding cards (reconciliation) ---------- */
.finding-card {
    background: var(--surface); border: 1px solid var(--border); border-left: 3px solid var(--border-strong);
    border-radius: var(--radius-md); padding: 1.05rem 1.2rem; margin-bottom: 0.7rem;
}
.finding-card.high { border-left-color: var(--danger); }
.finding-card.medium { border-left-color: var(--warning); }
.finding-card.low { border-left-color: var(--slate); }
.finding-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.8rem; margin-bottom: 0.5rem; }
.finding-title { font-size: 0.95rem; font-weight: 700; color: var(--text-primary); }
.finding-desc { font-size: 0.85rem; color: var(--text-secondary); line-height: 1.5; margin-bottom: 0.55rem; }
.finding-values { display: flex; align-items: center; gap: 0.7rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
.finding-value-box { font-size: 0.98rem; font-weight: 700; color: var(--text-primary); }
.finding-arrow { color: var(--text-muted); font-weight: 400; }
.finding-diff { font-size: 0.75rem; font-weight: 600; color: var(--danger); background: var(--danger-soft); padding: 0.2rem 0.55rem; border-radius: 999px; }
.finding-source-row { display: flex; align-items: center; gap: 0.5rem; font-size: 0.74rem; color: var(--text-muted); font-weight: 500; flex-wrap: wrap; }
.finding-source-chip { background: var(--bg); border: 1px solid var(--border); padding: 0.16rem 0.55rem; border-radius: 999px; }

.severity-badge {
    display: inline-flex; align-items: center; gap: 0.35rem; font-size: 0.66rem; font-weight: 700;
    letter-spacing: 0.07em; padding: 0.26rem 0.58rem; border-radius: 999px; white-space: nowrap;
}
.severity-badge.high { background: var(--danger-soft); color: var(--danger); }
.severity-badge.medium { background: var(--warning-soft); color: var(--warning); }
.severity-badge.low { background: var(--slate-soft); color: var(--slate); }

.category-chip {
    display: inline-flex; font-size: 0.64rem; font-weight: 700; letter-spacing: 0.06em;
    padding: 0.2rem 0.55rem; border-radius: 999px; white-space: nowrap;
}
.category-chip.indigo { background: var(--accent-soft); color: var(--accent-strong); }
.category-chip.teal { background: var(--teal-soft); color: var(--teal); }
.category-chip.violet { background: var(--violet-soft); color: var(--violet); }
.category-chip.slate { background: var(--slate-soft); color: var(--slate); }
.category-chip.warning { background: var(--warning-soft); color: var(--warning); }

/* ---------- Risk cards ---------- */
.risk-card {
    background: var(--surface); border: 1px solid var(--border); border-left: 3px solid var(--border-strong);
    border-radius: var(--radius-md); padding: 1.05rem 1.2rem; margin-bottom: 0.5rem;
}
.risk-card.high { border-left-color: var(--danger); }
.risk-card.medium { border-left-color: var(--warning); }
.risk-card.low { border-left-color: var(--slate); }
.risk-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.8rem; margin-bottom: 0.5rem; }
.risk-tags { display: flex; gap: 0.4rem; align-items: center; margin-bottom: 0.4rem; flex-wrap: wrap; }
.risk-id { font-size: 0.68rem; color: var(--text-muted); font-weight: 600; }
.risk-title { font-size: 0.95rem; font-weight: 700; color: var(--text-primary); margin-bottom: 0.4rem; }
.risk-desc { font-size: 0.85rem; color: var(--text-secondary); line-height: 1.55; margin-bottom: 0.5rem; }
.risk-implication {
    font-size: 0.82rem; color: var(--text-primary); background: var(--bg); border-radius: var(--radius-sm);
    padding: 0.6rem 0.75rem; margin-bottom: 0.5rem; line-height: 1.5;
}
.risk-implication .lbl { font-weight: 700; color: var(--text-muted); font-size: 0.66rem; letter-spacing: 0.07em; display: block; margin-bottom: 0.2rem; }
.risk-recommendation {
    font-size: 0.82rem; color: var(--text-primary); background: var(--accent-soft); border-radius: var(--radius-sm);
    padding: 0.6rem 0.75rem; line-height: 1.5;
}
.risk-recommendation .lbl { font-weight: 700; color: var(--accent-strong); font-size: 0.66rem; letter-spacing: 0.07em; display: block; margin-bottom: 0.2rem; }

/* ---------- Question cards ---------- */
.question-card { display: flex; gap: 1rem; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 1.1rem 1.3rem; margin-bottom: 0.8rem; }
.question-number { font-size: 1.3rem; font-weight: 700; color: var(--accent); min-width: 38px; }
.question-text { font-size: 0.92rem; color: var(--text-primary); line-height: 1.55; }

/* ---------- Document cards ---------- */
.doc-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 0.9rem 1.05rem; margin-bottom: 0.6rem; }
.doc-card.error { border-left: 3px solid var(--danger); }
.doc-card-top { display: flex; justify-content: space-between; align-items: center; gap: 0.8rem; flex-wrap: wrap; }
.doc-name { font-size: 0.88rem; font-weight: 700; color: var(--text-primary); }
.doc-meta { font-size: 0.76rem; color: var(--text-muted); margin-top: 0.15rem; }
.doc-status { font-size: 0.64rem; font-weight: 700; letter-spacing: 0.07em; padding: 0.22rem 0.55rem; border-radius: 999px; white-space: nowrap; }
.doc-status.ready { background: var(--success-soft); color: var(--success); }
.doc-status.pending { background: var(--bg); color: var(--text-secondary); border: 1px solid var(--border-strong); }
.doc-status.failed { background: var(--danger-soft); color: var(--danger); }
.doc-type-row { display: flex; align-items: center; gap: 0.6rem; margin-top: 0.55rem; flex-wrap: wrap; }
.doc-type-chip { font-size: 0.72rem; font-weight: 700; color: var(--accent-strong); background: var(--accent-soft); padding: 0.2rem 0.6rem; border-radius: 999px; }
.doc-confidence { font-size: 0.72rem; color: var(--text-muted); }
.doc-stats { display: flex; gap: 1.2rem; margin-top: 0.5rem; }
.doc-stat { font-size: 0.76rem; color: var(--text-secondary); }
.doc-stat b { color: var(--text-primary); }

/* ---------- Ask room ---------- */
.answer-box { background: var(--surface); border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: var(--radius-lg); padding: 1.25rem 1.4rem; margin-top: 1rem; }
.answer-heading { font-size: 0.66rem; font-weight: 700; letter-spacing: 0.09em; color: var(--text-muted); margin-bottom: 0.5rem; }
.answer-text { font-size: 0.92rem; color: var(--text-primary); line-height: 1.65; white-space: pre-wrap; }
.answer-context { font-size: 0.74rem; color: var(--text-muted); margin-top: 0.9rem; padding-top: 0.7rem; border-top: 1px solid var(--border); }
.chip-row { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-top: 0.5rem; }
div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button {
    background: var(--accent-soft); color: var(--accent-strong); border: 1px solid transparent;
    border-radius: 999px; font-size: 0.78rem; font-weight: 600; padding: 0.5rem 1rem; box-shadow: none;
}
div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button:hover {
    background: var(--accent); color: #FFFFFF; border: 1px solid var(--accent);
}
button[kind="primary"] {
    background: var(--accent) !important; color: #FFFFFF !important; border: 1px solid var(--accent) !important;
    border-radius: var(--radius-sm) !important; font-weight: 600 !important; padding: 0.6rem 1.5rem !important;
}
button[kind="primary"]:hover { background: var(--accent-strong) !important; border-color: var(--accent-strong) !important; }
div[data-testid="stTextInput"] input { border-radius: var(--radius-sm); border: 1px solid var(--border-strong); padding: 0.65rem 0.9rem; font-size: 0.92rem; }

/* ---------- Landing / upload ---------- */
.hero-wrap { text-align: center; padding: 2.6rem 1rem 1.6rem 1rem; }
.hero-eyebrow { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.14em; color: var(--accent); margin-bottom: 0.9rem; }
.hero-title { font-size: 2.4rem; font-weight: 700; color: var(--text-primary) !important; letter-spacing: -0.03em; line-height: 1.15; margin-bottom: 0.9rem; }
.hero-subtitle { font-size: 1.02rem; color: var(--text-secondary); max-width: 620px; margin: 0 auto; line-height: 1.6; }
.trust-note { font-size: 0.78rem; color: var(--text-muted); text-align: center; max-width: 560px; margin: 1.1rem auto 0 auto; line-height: 1.55; }
.supported-row { display: flex; justify-content: center; gap: 0.5rem; flex-wrap: wrap; margin: 1.4rem 0 0.4rem 0; }
.supported-chip { font-size: 0.74rem; font-weight: 600; color: var(--text-secondary); background: var(--surface); border: 1px solid var(--border-strong); padding: 0.35rem 0.8rem; border-radius: 999px; }
div[data-testid="stFileUploaderDropzone"] {
    background: var(--surface) !important; border: 1.5px dashed var(--border-strong) !important; border-radius: var(--radius-lg) !important;
}
div[data-testid="stFileUploaderDropzone"]:hover { border-color: var(--accent) !important; }

.app-footer { margin-top: 3rem; padding-top: 1.2rem; border-top: 1px solid var(--border); font-size: 0.76rem; color: var(--text-muted); text-align: center; }

div[data-testid="stExpander"] { border: 1px solid var(--border) !important; border-radius: var(--radius-md) !important; background: var(--surface); margin-bottom: 0.6rem; }
div[data-testid="stExpander"] summary { font-size: 0.82rem; font-weight: 600; color: var(--accent-strong); }

@media (max-width: 768px) {
    .page-title, .hero-title { font-size: 1.5rem; }
    .metric-value { font-size: 1.3rem; }
    .top-header { flex-direction: column; align-items: flex-start; }
}
</style>
"""


def load_css() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ============================================================================
# REUSABLE UI COMPONENTS
# ============================================================================

def section_header(eyebrow: str, title: str, subtitle: str, status: Optional[str] = None) -> None:
    status_html = ""
    if status == "required":
        status_html = '<span class="status-pill required"><span class="dot"></span>REVIEW REQUIRED</span>'
    elif status == "ready":
        status_html = '<span class="status-pill ready"><span class="dot"></span>NO ISSUES FOUND</span>'
    st.markdown(
        f"""
        <div class="eyebrow">{eyebrow}</div>
        <div class="page-title-row">
            <h1 class="page-title">{title}</h1>
            {status_html}
        </div>
        <div class="page-subtitle">{subtitle}</div>
        """,
        unsafe_allow_html=True,
    )


def render_section_label(label: str, sub: Optional[str] = None) -> None:
    st.markdown(f'<div class="section-label">{label}</div>', unsafe_allow_html=True)
    if sub:
        st.markdown(f'<div class="section-sub">{sub}</div>', unsafe_allow_html=True)


def metric_card(label: str, value: str, sub: str = "", tone: str = "neutral", accent: str = "indigo") -> str:
    return f"""<div class="metric-card accent-{accent}">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
        <div class="metric-sub {tone}">{sub}</div>
    </div>""".strip()


def render_metric_row(cards: List[Dict[str, str]]) -> None:
    cols = st.columns(len(cards))
    for col, card in zip(cols, cards):
        with col:
            st.markdown(
                metric_card(
                    card["label"], card["value"], card.get("sub", ""),
                    card.get("tone", "neutral"), card.get("accent", "indigo"),
                ),
                unsafe_allow_html=True,
            )


def render_snapshot_rows(rows: List[tuple]) -> None:
    """Render a bordered card of label/value rows. Each item is (label, value)."""
    fragments = "".join(
        f"""<div class="snapshot-row">
            <span class="snapshot-key">{label}</span>
            <span class="snapshot-val">{value}</span>
        </div>""".strip()
        for label, value in rows
    )
    st.markdown(f'<div class="card">{fragments}</div>', unsafe_allow_html=True)


def render_empty_state(message: str, neutral: bool = False) -> None:
    cls = "empty-state neutral" if neutral else "empty-state"
    st.markdown(f'<div class="{cls}">{message}</div>', unsafe_allow_html=True)


def render_finding_card(rec: Dict[str, Any]) -> None:
    """Render one reconciliation discrepancy as a source A vs source B finding card."""
    sev = severity_class(rec.get("severity"))
    label = rec.get("field_label") or rec.get("field") or "Reconciliation Finding"
    val_a = rec.get("display_value_a", fmt_generic(rec.get("value_a")))
    val_b = rec.get("display_value_b", fmt_generic(rec.get("value_b")))
    source_a = safe_get(rec, "source_a", "file_name", default="Source A")
    source_b = safe_get(rec, "source_b", "file_name", default="Source B")
    doc_type_a = safe_get(rec, "source_a", "document_type", default="")
    doc_type_b = safe_get(rec, "source_b", "document_type", default="")
    explanation = rec.get("explanation", "")
    diff_label = ""
    if rec.get("absolute_difference") is not None:
        diff_label = fmt_generic(rec.get("absolute_difference"))
        if rec.get("relative_difference_pct") is not None:
            diff_label += f" ({fmt_pct(rec.get('relative_difference_pct'))})"

    diff_html = f'<span class="finding-diff">{diff_label}</span>' if diff_label else ""

    st.markdown(
        f"""
        <div class="finding-card {sev}">
            <div class="finding-top">
                <div class="finding-title">{label}</div>
                {severity_badge(rec.get('severity'))}
            </div>
            <div class="finding-desc">{explanation}</div>
            <div class="finding-values">
                <span class="finding-value-box">{val_a}</span>
                <span class="finding-arrow">→</span>
                <span class="finding-value-box">{val_b}</span>
                {diff_html}
            </div>
            <div class="finding-source-row">
                <span class="finding-source-chip">{source_a}{f" · {doc_type_a}" if doc_type_a else ""}</span>
                <span>↔</span>
                <span class="finding-source-chip">{source_b}{f" · {doc_type_b}" if doc_type_b else ""}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Source details"):
        col_a, col_b = st.columns(2)
        for col, side_key in ((col_a, "source_a"), (col_b, "source_b")):
            with col:
                side = rec.get(side_key) or {}
                st.markdown(f"**{side.get('file_name', DASH)}**")
                st.caption(f"Document type: {side.get('document_type', DASH)}")
                st.caption(f"Field: `{side.get('field', DASH)}`")
                if side.get("source_location"):
                    st.caption(f"Location: {side.get('source_location')}")
                if side.get("confidence") is not None:
                    st.caption(f"Confidence: {fmt_pct(float(side.get('confidence')) * 100) if side.get('confidence') <= 1 else fmt_generic(side.get('confidence'))}")
                if side.get("context"):
                    st.caption(f"“{side.get('context')}”")


def severity_badge(severity: Optional[str]) -> str:
    sev = severity_class(severity)
    label = (severity or "Low").upper()
    return f'<span class="severity-badge {sev}">{label}</span>'


def render_risk_card(risk: Dict[str, Any]) -> None:
    sev = severity_class(risk.get("severity"))
    category = risk.get("category", "General")
    accent = category_accent(category)
    risk_id = risk.get("risk_id", "")

    st.markdown(
        f"""
        <div class="risk-card {sev}">
            <div class="risk-tags">
                {severity_badge(risk.get('severity'))}
                <span class="category-chip {accent}">{category.upper()}</span>
                {f'<span class="risk-id">{risk_id}</span>' if risk_id else ''}
            </div>
            <div class="risk-title">{risk.get('title', 'Untitled Risk')}</div>
            <div class="risk-desc">{risk.get('description', '')}</div>
            {f'<div class="risk-implication"><span class="lbl">WHY IT MATTERS</span>{risk.get("implication")}</div>' if risk.get('implication') else ''}
            {f'<div class="risk-recommendation"><span class="lbl">RECOMMENDATION</span>{risk.get("recommendation")}</div>' if risk.get('recommendation') else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )

    evidence = risk.get("evidence") or []
    has_explanation = risk_id in st.session_state.risk_explanations

    with st.expander("Evidence & explanation"):
        if evidence:
            for item in evidence:
                if isinstance(item, dict):
                    file_name = item.get("file_name", "Unknown source")
                    doc_type = item.get("document_type", "")
                    field = item.get("field", "")
                    value = item.get("value", "")
                    location = item.get("source_location", "")
                    context = item.get("context", "")
                    header = f"**{file_name}**"
                    if doc_type:
                        header += f" · {doc_type}"
                    st.markdown(header)
                    details = []
                    if field:
                        details.append(f"Field: `{field}`")
                    if value not in (None, ""):
                        details.append(f"Value: {value}")
                    if location:
                        details.append(f"Location: {location}")
                    if details:
                        st.caption(" · ".join(details))
                    if context:
                        st.caption(f"“{context}”")
                else:
                    st.markdown(f"- {item}")
        else:
            st.caption("No linked evidence provided for this risk.")

        st.markdown("---")
        if has_explanation:
            st.markdown(f"**AI explanation:** {st.session_state.risk_explanations[risk_id]}")
        else:
            if st.button("Explain this risk", key=f"explain_{risk_id or risk.get('title')}"):
                try:
                    explanation_text = explain_risk(risk)
                except Exception as exc:  # noqa: BLE001
                    explanation_text = f"Could not generate an explanation ({exc})."
                st.session_state.risk_explanations[risk_id] = explanation_text
                _rerun()


def render_document_card(
    file_name: str,
    size_bytes: Optional[int] = None,
    doc_type: Optional[str] = None,
    confidence: Optional[float] = None,
    evidence_count: Optional[int] = None,
    finding_count: Optional[int] = None,
    status: str = "pending",
    status_label: Optional[str] = None,
) -> None:
    ext = Path(file_name).suffix.lower()
    type_label = EXTENSION_LABELS.get(ext, ext.upper().lstrip(".") or "File")
    size_label = fmt_bytes(size_bytes) if size_bytes is not None else ""
    meta_parts = [type_label]
    if size_label:
        meta_parts.append(size_label)

    status_label = status_label or {"ready": "Ready", "pending": "Pending", "failed": "Could not process"}.get(status, "Pending")

    type_row = ""
    if doc_type:
        conf_label = f"{confidence * 100:.0f}% confidence" if isinstance(confidence, (int, float)) and confidence <= 1 else (fmt_generic(confidence) if confidence is not None else "")
        conf_span = f'<span class="doc-confidence">{conf_label}</span>' if conf_label else ""
        type_row = f'<div class="doc-type-row"><span class="doc-type-chip">{doc_type}</span>{conf_span}</div>'

    stats_row = ""
    if evidence_count is not None or finding_count is not None:
        stats = []
        if evidence_count is not None:
            stats.append(f'<span class="doc-stat"><b>{evidence_count}</b> evidence items</span>')
        if finding_count is not None:
            stats.append(f'<span class="doc-stat"><b>{finding_count}</b> related findings</span>')
        stats_row = f'<div class="doc-stats">{"".join(stats)}</div>'

    card_cls = "doc-card error" if status == "failed" else "doc-card"

    st.markdown(
        f"""
        <div class="{card_cls}">
            <div class="doc-card-top">
                <div>
                    <div class="doc-name">{file_name}</div>
                    <div class="doc-meta">{" · ".join(meta_parts)}</div>
                </div>
                <span class="doc-status {status}">{status_label}</span>
            </div>
            {type_row}
            {stats_row}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_footer() -> None:
    st.markdown(
        '<div class="app-footer">Due Diligence Copilot · Document-driven diligence workspace · Synthetic/demo data only</div>',
        unsafe_allow_html=True,
    )


# ============================================================================
# BACKEND PIPELINE EXECUTION
# ============================================================================

def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = Path(filename).stem, Path(filename).suffix
    i = 1
    while True:
        candidate = directory / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def _save_uploaded_files(uploaded_files: List[Any]) -> Path:
    old_dir = st.session_state.get("work_dir")
    if old_dir and Path(old_dir).exists():
        shutil.rmtree(old_dir, ignore_errors=True)

    work_dir = Path(tempfile.mkdtemp(prefix="ddcopilot_"))
    for uploaded_file in uploaded_files:
        destination = _unique_path(work_dir, uploaded_file.name)
        destination.write_bytes(uploaded_file.getbuffer())

    st.session_state.work_dir = str(work_dir)
    return work_dir


def run_pipeline(work_dir: Path) -> bool:
    """Execute the full backend pipeline with a live progress display.

    Returns True on success. On failure, stores the error in session state
    and returns False without raising, so the app never crashes outright.
    """
    try:
        with st.status("Running diligence analysis…", expanded=True) as status:
            st.write("Reading documents…")
            documents = extract_all_documents(work_dir)
            st.write(f"Read {len(documents)} document(s).")

            failed_docs = [
                d.get("file_name", "Unknown file")
                for d in documents
                if isinstance(d, dict) and d.get("error")
            ]
            if failed_docs:
                st.write(f"⚠ {len(failed_docs)} file(s) could not be fully processed: {', '.join(failed_docs)}")

            st.write("Classifying documents…")
            classifications = classify_documents(documents)
            st.write("Classification complete.")

            st.write("Extracting evidence…")
            evidence_store = build_evidence_store(documents, classifications)
            st.write(f"Extracted {len(evidence_store)} evidence item(s).")

            st.write("Reconciling figures across documents…")
            reconciliations = reconcile_evidence(evidence_store)
            st.write(f"Found {len(reconciliations)} discrepancy candidate(s).")

            st.write("Calculating financial metrics…")
            financials = analyze_financials(evidence_store)
            st.write("Financial metrics calculated.")

            st.write("Assessing risks…")
            risks = build_risk_register(evidence_store, reconciliations, financials)
            st.write(f"Identified {len(risks)} risk item(s).")

            st.write("Preparing diligence questions and executive summary…")
            ai_analysis = run_ai_analysis(evidence_store, reconciliations, financials, risks)
            st.write("Analysis ready.")

            status.update(label="Diligence analysis complete", state="complete")

        st.session_state.documents = documents
        st.session_state.classifications = classifications
        st.session_state.evidence_store = evidence_store
        st.session_state.reconciliations = reconciliations
        st.session_state.financials = financials
        st.session_state.risks = risks
        st.session_state.ai_analysis = ai_analysis
        st.session_state.analysis_complete = True
        st.session_state.analysis_error = None
        st.session_state.analysis_traceback = None
        st.session_state.risk_explanations = {}
        return True

    except Exception as exc:  # noqa: BLE001
        st.session_state.analysis_complete = False
        st.session_state.analysis_error = str(exc)
        st.session_state.analysis_traceback = traceback.format_exc()
        return False


# ============================================================================
# SIDEBAR
# ============================================================================

def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            """
            <div class="sidebar-brand">
                <p class="sidebar-brand-title">Due Diligence Copilot</p>
                <div class="sidebar-brand-sub">DOCUMENT-DRIVEN DILIGENCE</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        doc_count = len(st.session_state.documents) if st.session_state.documents else 0
        discrepancy_count = len(st.session_state.reconciliations) if st.session_state.reconciliations else 0
        risk_count = len(st.session_state.risks) if st.session_state.risks else 0

        if st.session_state.analysis_complete:
            st.markdown('<div class="nav-section-label">WORKSPACE</div>', unsafe_allow_html=True)
            for item in NAV_ITEMS:
                is_active = st.session_state.page == item
                if is_active:
                    st.markdown(
                        f'<div class="nav-item"><span class="nav-dot"></span>{item}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    if st.button(item, key=f"nav_{item}", use_container_width=True):
                        st.session_state.page = item
                        _rerun()

            status_val = "ok" if not st.session_state.analysis_error else "bad"
            st.markdown(
                f"""
                <div class="workspace-card">
                    <div class="workspace-label">DATA ROOM</div>
                    <div class="workspace-value">{doc_count} document{'s' if doc_count != 1 else ''} reviewed</div>
                    <div class="status-row">
                        <span class="status-key">DISCREPANCIES</span>
                        <span class="status-val">{discrepancy_count}</span>
                    </div>
                    <div class="status-row">
                        <span class="status-key">RISK FLAGS</span>
                        <span class="status-val">{risk_count}</span>
                    </div>
                    <div class="status-row">
                        <span class="status-key">ANALYSIS</span>
                        <span class="status-val {status_val}">Complete</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.markdown("<div style='height: 0.6rem'></div>", unsafe_allow_html=True)
            if st.button("↻  Rerun Analysis", key="rerun_analysis", use_container_width=True):
                work_dir = st.session_state.get("work_dir")
                if work_dir and Path(work_dir).exists():
                    run_pipeline(Path(work_dir))
                    _rerun()
                else:
                    st.warning("Original files are no longer available. Please start a new analysis.")

            if st.button("＋  New Analysis", key="new_analysis", use_container_width=True):
                reset_analysis(delete_files=True)
                _rerun()

        else:
            st.markdown('<div class="nav-section-label">WORKSPACE</div>', unsafe_allow_html=True)
            st.markdown(
                f"""
                <div class="workspace-card">
                    <div class="workspace-label">DATA ROOM</div>
                    <div class="workspace-value">Awaiting upload</div>
                    <div class="status-row">
                        <span class="status-key">STATUS</span>
                        <span class="status-val">No analysis yet</span>
                    </div>
                </div>
                <div class="sidebar-note">Navigation unlocks once your first set of documents has been analyzed.</div>
                """,
                unsafe_allow_html=True,
            )


def render_top_header(section: str) -> None:
    ai_key_present = bool(os.getenv("GEMINI_API_KEY"))
    exec_source = safe_get(st.session_state.get("ai_analysis") or {}, "executive_summary", "source")

    if exec_source == "AI":
        # A real Gemini call has actually succeeded this session.
        pill_class = "env-pill"
        pill_text = "AI ENGINE: CONNECTED"
    elif exec_source:
        # An analysis ran but the AI call fell back — do not claim
        # "connected" just because a key exists in the environment.
        pill_class = "env-pill warn"
        pill_text = "AI ENGINE: FALLBACK MODE"
    else:
        # No analysis has run yet in this session — this can only reflect
        # whether a key is configured, not whether it actually works.
        pill_class = "env-pill" if ai_key_present else "env-pill warn"
        pill_text = "AI ENGINE: KEY DETECTED" if ai_key_present else "AI ENGINE: NO KEY"

    st.markdown(
        f"""
        <div class="top-header">
            <div class="top-header-left">
                <span class="top-header-brand">Diligence Workspace</span>
                <span class="top-header-divider"></span>
                <span class="top-header-section">{section}</span>
            </div>
            <div class="top-header-right">
                <span class="{pill_class}"><span class="dot"></span>{pill_text}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================================
# STATE 1 — LANDING / UPLOAD EXPERIENCE
# ============================================================================

def render_landing() -> None:
    st.markdown(
        """
        <div class="hero-wrap">
            <div class="hero-eyebrow">DUE DILIGENCE COPILOT</div>
            <div class="hero-title">Diligence at just a click</div>
            <div class="hero-subtitle">
                Upload company materials and let the workspace surface inconsistencies,
                financial signals, risks and questions worth investigating.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="supported-row">
            <span class="supported-chip">Financial Models</span>
            <span class="supported-chip">Investor Decks</span>
            <span class="supported-chip">Bank Statements</span>
            <span class="supported-chip">Cap Tables</span>
            <span class="supported-chip">Customer Metrics</span>
            <span class="supported-chip">Legal / Corporate Documents</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _, mid, _ = st.columns([1, 3, 1])
    with mid:
        uploaded_files = st.file_uploader(
            "Upload documents",
            type=["pdf", "xlsx", "pptx"],
            accept_multiple_files=True,
            label_visibility="collapsed",
            key="file_uploader",
        )

        st.markdown(
            """
            <div class="trust-note">
                Documents are analyzed within this session. The system uses document
                evidence rather than filename assumptions to identify what each file is.
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.session_state.analysis_error:
            st.markdown("<div style='height: 1rem'></div>", unsafe_allow_html=True)
            st.error(f"The last analysis attempt failed: {st.session_state.analysis_error}")
            with st.expander("Technical details"):
                st.code(st.session_state.analysis_traceback or "No traceback available.")

        if uploaded_files:
            st.markdown("<div style='height: 1.8rem'></div>", unsafe_allow_html=True)
            render_section_label(
                "DOCUMENTS READY FOR REVIEW",
                f"{len(uploaded_files)} file(s) selected. Confirm and run the analysis when ready.",
            )
            for f in uploaded_files:
                render_document_card(f.name, size_bytes=f.size, status="pending", status_label="Ready to analyze")

            st.markdown("<div style='height: 0.8rem'></div>", unsafe_allow_html=True)
            run_clicked = st.button("Run Diligence", type="primary", use_container_width=True)
            if run_clicked:
                work_dir = _save_uploaded_files(uploaded_files)
                success = run_pipeline(work_dir)
                if success:
                    st.session_state.page = "Overview"
                    _rerun()
                else:
                    _rerun()


# ============================================================================
# STATE 2 — OVERVIEW
# ============================================================================

def render_overview() -> None:
    financials = st.session_state.financials or {}
    reconciliations = st.session_state.reconciliations or []
    risks = st.session_state.risks or []
    ai_analysis = st.session_state.ai_analysis or {}
    documents = st.session_state.documents or []

    recon_summary = summarize_reconciliations(reconciliations) if reconciliations else {"total_discrepancies": 0, "high": 0, "medium": 0, "low": 0}
    risk_summary = summarize_risk_register(risks) if risks else {"total_risks": 0, "high": 0, "medium": 0, "low": 0}

    status = "required" if (recon_summary.get("total_discrepancies", 0) or risk_summary.get("high", 0)) else "ready"

    section_header(
        eyebrow="DUE DILIGENCE OVERVIEW",
        title="Diligence Snapshot",
        subtitle="AI-assisted review of the uploaded financial, commercial, ownership and legal evidence.",
        status=status,
    )

    revenue = safe_get(financials, "revenue", "current_revenue_cr")
    active_customers = safe_get(financials, "customers", "active_customers")
    arr = safe_get(financials, "customers", "arr_cr")

    render_metric_row(
        [
            {"label": "REVENUE", "value": fmt_cr(revenue), "sub": "Current period", "tone": "neutral", "accent": "indigo"},
            {"label": "ACTIVE CUSTOMERS", "value": fmt_num(active_customers), "sub": f"ARR {fmt_cr(arr)}", "tone": "neutral", "accent": "violet"},
            {
                "label": "RISK FLAGS",
                "value": str(risk_summary.get("total_risks", 0)),
                "sub": f"{risk_summary.get('high', 0)} high · {risk_summary.get('medium', 0)} medium",
                "tone": "negative" if risk_summary.get("high", 0) else "neutral",
                "accent": "danger" if risk_summary.get("high", 0) else "warning",
            },
            {
                "label": "DISCREPANCIES",
                "value": str(recon_summary.get("total_discrepancies", 0)),
                "sub": f"across {len(documents)} document(s)",
                "tone": "negative" if recon_summary.get("total_discrepancies", 0) else "positive",
                "accent": "teal",
            },
        ]
    )

    st.markdown("<div style='height: 1.6rem'></div>", unsafe_allow_html=True)

    exec_summary = ai_analysis.get("executive_summary") or {}
    if exec_summary.get("text"):
        summary_text = str(exec_summary.get("text", ""))
        formatted_summary_html = format_ai_narrative_html(summary_text)
        source = (exec_summary.get("source") or "").strip().lower()
        badge_cls = "ai" if source == "ai" else "fallback"
        badge_label = "AI-GENERATED" if source == "ai" else "DETERMINISTIC SUMMARY"
        st.markdown(
            f"""
            <div class="exec-summary-card">
                <div class="exec-summary-head">
                    <span class="exec-summary-label">EXECUTIVE SUMMARY</span>
                    <span class="source-badge {badge_cls}">{badge_label}</span>
                </div>
                <div class="exec-summary-text">{formatted_summary_html}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if source != "ai":
            reason = classify_ai_error(exec_summary.get("error"))
            if reason:
                st.caption(f"AI unavailable — {reason}. See Settings for technical detail.")

    left, right = st.columns([1.4, 1])

    with left:
        render_section_label("FINANCIAL SNAPSHOT", "Key figures extracted from the reviewed documents.")
        rows = [
            ("Revenue", fmt_cr(revenue)),
            ("Active Customers", fmt_num(active_customers)),
            ("ARR", fmt_cr(arr)),
            ("EBITDA Margin", fmt_pct(safe_get(financials, "margins", "calculated_ebitda_margin_pct") or safe_get(financials, "margins", "reported_ebitda_margin_pct"))),
            ("NRR", fmt_pct(safe_get(financials, "operating", "nrr_pct"))),
            ("Estimated Runway", fmt_months(safe_get(financials, "cash", "estimated_runway_months"))),
        ]
        render_snapshot_rows(rows)

    with right:
        render_section_label("DILIGENCE READOUT", "Status of the current evidence review.")
        st.markdown(
            f"""
            <div class="card">
                <div class="snapshot-row"><span class="snapshot-key">Documents reviewed</span><span class="snapshot-val">{len(documents)}</span></div>
                <div class="snapshot-row"><span class="snapshot-key">High-priority risks</span><span class="snapshot-val">{risk_summary.get('high', 0)}</span></div>
                <div class="snapshot-row"><span class="snapshot-key">Medium-priority risks</span><span class="snapshot-val">{risk_summary.get('medium', 0)}</span></div>
                <div class="snapshot-row"><span class="snapshot-key">Cross-document discrepancies</span><span class="snapshot-val">{recon_summary.get('total_discrepancies', 0)}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 1.8rem'></div>", unsafe_allow_html=True)

    render_section_label("PRIORITY FINDINGS", "Cross-document discrepancies requiring analyst attention.")
    if reconciliations:
        for rec in reconciliations:
            render_finding_card(rec)
    else:
        render_empty_state("No cross-document discrepancies were identified in the reviewed materials.")


# ============================================================================
# STATE 2 — FINANCIALS
# ============================================================================

def render_financials() -> None:
    financials = st.session_state.financials or {}

    section_header(
        eyebrow="FINANCIAL ANALYSIS",
        title="Financials",
        subtitle="Performance, profitability and liquidity derived from the reviewed documents.",
    )

    revenue = safe_get(financials, "revenue", "current_revenue_cr")
    arr = safe_get(financials, "customers", "arr_cr")
    ebitda_margin = safe_get(financials, "margins", "calculated_ebitda_margin_pct") or safe_get(financials, "margins", "reported_ebitda_margin_pct")
    runway = safe_get(financials, "cash", "estimated_runway_months")

    render_metric_row(
        [
            {"label": "REVENUE", "value": fmt_cr(revenue), "sub": "Current period", "accent": "indigo"},
            {"label": "ARR", "value": fmt_cr(arr), "sub": "Annual recurring revenue", "accent": "violet"},
            {"label": "EBITDA MARGIN", "value": fmt_pct(ebitda_margin), "sub": "Current period", "accent": "warning", "tone": "negative" if isinstance(ebitda_margin, (int, float)) and ebitda_margin < 0 else "neutral"},
            {"label": "RUNWAY", "value": fmt_months(runway), "sub": "Estimated", "accent": "teal"},
        ]
    )

    st.markdown("<div style='height: 1.8rem'></div>", unsafe_allow_html=True)
    left, right = st.columns([1.2, 1])

    # ---- Cash position chart ----
    with left:
        render_section_label("CASH POSITION", "Model-reported cash versus bank-confirmed balance.")
        model_cash = safe_get(financials, "cash", "model_closing_cash_cr")
        bank_cash = safe_get(financials, "cash", "bank_closing_cash_cr")
        variance = safe_get(financials, "cash", "cash_variance_cr")

        if model_cash is not None or bank_cash is not None:
            labels, values = [], []
            if model_cash is not None:
                labels.append("Financial Model")
                values.append(model_cash)
            if bank_cash is not None:
                labels.append("Bank Statement")
                values.append(bank_cash)

            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=labels, y=values, marker_color=["#3B4FA0", "#0F7A82"][: len(values)],
                    width=0.42, text=[f"₹{v:.2f} Cr" for v in values], textposition="outside",
                    textfont=dict(size=13, color="#1B2233", family="Inter"),
                    hovertemplate="%{x}: ₹%{y:.2f} Cr<extra></extra>",
                )
            )
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=10, r=10, t=30, b=10), height=290, showlegend=False,
                font=dict(family="Inter, sans-serif", color="#6B7280"),
                xaxis=dict(showgrid=False, zeroline=False, showline=True, linecolor="#D8D7D2", tickfont=dict(size=13)),
                yaxis=dict(
                    showgrid=True, gridcolor="#EEEDEA", zeroline=True, zerolinecolor="#D8D7D2",
                    showline=True, linecolor="#D8D7D2", showticklabels=True,
                    tickfont=dict(size=11, color="#9AA0AC"), ticksuffix=" Cr",
                    title=dict(text="₹ Cr", font=dict(size=11, color="#9AA0AC")),
                    range=[0, max(values) * 1.35 if values else 1],
                ),
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            if variance is not None:
                st.caption(f"Variance between reported balances: ₹{abs(variance):.2f} Cr")
        else:
            render_empty_state("No cash-position data was found in the reviewed documents.", neutral=True)

    # ---- Margins chart ----
    with right:
        render_section_label("MARGIN PROFILE", "Reported versus calculated margins.")
        margin_items = [
            ("Gross Margin (reported)", safe_get(financials, "margins", "reported_gross_margin_pct")),
            ("EBITDA Margin (reported)", safe_get(financials, "margins", "reported_ebitda_margin_pct")),
            ("EBITDA Margin (calculated)", safe_get(financials, "margins", "calculated_ebitda_margin_pct")),
        ]
        margin_items = [(label, val) for label, val in margin_items if val is not None]

        if margin_items:
            labels = [m[0] for m in margin_items]
            values = [m[1] for m in margin_items]
            colors = ["#6E4FA0", "#B26A00", "#3B4FA0"][: len(values)]
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=labels, y=values, marker_color=colors, width=0.5,
                    text=[f"{v:.1f}%" for v in values], textposition="outside",
                    textfont=dict(size=12, color="#1B2233", family="Inter"),
                    hovertemplate="%{x}: %{y:.1f}%<extra></extra>",
                )
            )
            value_span = (max(values) - min(values)) if values else 0
            padding = value_span * 0.3 if value_span else 5
            y_min = min(0, min(values)) - padding
            y_max = max(0, max(values)) + padding

            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=10, r=10, t=30, b=10), height=290, showlegend=False,
                font=dict(family="Inter, sans-serif", color="#6B7280", size=11),
                xaxis=dict(showgrid=False, zeroline=False, showline=True, linecolor="#D8D7D2", tickfont=dict(size=11)),
                yaxis=dict(
                    showgrid=True, gridcolor="#EEEDEA", zeroline=True, zerolinecolor="#D8D7D2",
                    showline=True, linecolor="#D8D7D2", showticklabels=True,
                    tickfont=dict(size=11, color="#9AA0AC"), ticksuffix="%",
                    title=dict(text="%", font=dict(size=11, color="#9AA0AC")),
                    range=[y_min, y_max],
                ),
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            render_empty_state("No margin data was found in the reviewed documents.", neutral=True)

    st.markdown("<div style='height: 1.8rem'></div>", unsafe_allow_html=True)

    render_section_label("DETAILED METRICS", "All figures currently produced by the financial engine.")
    detail_cols = st.columns(2)
    with detail_cols[0]:
        st.markdown("**Revenue & Customers**")
        render_snapshot_rows(
            [
                ("Revenue", fmt_cr(revenue)),
                ("Active Customers", fmt_num(safe_get(financials, "customers", "active_customers"))),
                ("ARR", fmt_cr(arr)),
                ("ACV", fmt_lakh(safe_get(financials, "customers", "acv_lakh"))),
                ("ARR per Customer", fmt_lakh(safe_get(financials, "customers", "calculated_arr_per_customer_lakh"))),
            ]
        )
        st.markdown("<div style='height: 1rem'></div>", unsafe_allow_html=True)
        st.markdown("**Cash & Liquidity**")
        render_snapshot_rows(
            [
                ("Model Closing Cash", fmt_cr(safe_get(financials, "cash", "model_closing_cash_cr"))),
                ("Bank Closing Cash", fmt_cr(safe_get(financials, "cash", "bank_closing_cash_cr"))),
                ("Cash Variance", fmt_cr(safe_get(financials, "cash", "cash_variance_cr"))),
                ("Monthly Burn", fmt_lakh(safe_get(financials, "cash", "monthly_burn_lakh"))),
                ("Estimated Runway", fmt_months(safe_get(financials, "cash", "estimated_runway_months"))),
            ]
        )
    with detail_cols[1]:
        st.markdown("**Margins & Profitability**")
        render_snapshot_rows(
            [
                ("Gross Margin (reported)", fmt_pct(safe_get(financials, "margins", "reported_gross_margin_pct"))),
                ("EBITDA", fmt_cr(safe_get(financials, "margins", "ebitda_cr"))),
                ("EBITDA Margin (reported)", fmt_pct(safe_get(financials, "margins", "reported_ebitda_margin_pct"))),
                ("EBITDA Margin (calculated)", fmt_pct(safe_get(financials, "margins", "calculated_ebitda_margin_pct"))),
            ]
        )
        st.markdown("<div style='height: 1rem'></div>", unsafe_allow_html=True)
        st.markdown("**Operating Metrics**")
        render_snapshot_rows(
            [
                ("NRR", fmt_pct(safe_get(financials, "operating", "nrr_pct"))),
                ("Churn", fmt_pct(safe_get(financials, "operating", "churn_pct"))),
                ("CAC", fmt_lakh(safe_get(financials, "operating", "cac_lakh"))),
                ("ACV", fmt_lakh(safe_get(financials, "operating", "acv_lakh"))),
                ("CAC : ACV Ratio", fmt_generic(safe_get(financials, "operating", "cac_to_acv_ratio"))),
            ]
        )


# ============================================================================
# STATE 2 — RISK FLAGS
# ============================================================================

def render_risk_flags() -> None:
    risks = st.session_state.risks or []
    risk_summary = summarize_risk_register(risks) if risks else {"total_risks": 0, "high": 0, "medium": 0, "low": 0, "by_category": {}}

    section_header(
        eyebrow="EXCEPTIONS & RISKS",
        title="Risk Flags",
        subtitle="Potential inconsistencies, missing evidence and follow-up items identified across the documents.",
    )

    render_metric_row(
        [
            {"label": "TOTAL FLAGS", "value": str(risk_summary.get("total_risks", 0)), "sub": "Across all categories", "accent": "indigo"},
            {"label": "HIGH PRIORITY", "value": str(risk_summary.get("high", 0)), "sub": "Requires immediate attention", "accent": "danger", "tone": "negative"},
            {"label": "MEDIUM PRIORITY", "value": str(risk_summary.get("medium", 0)), "sub": "Requires follow-up", "accent": "warning"},
            {"label": "LOW PRIORITY", "value": str(risk_summary.get("low", 0)), "sub": "For awareness", "accent": "teal"},
        ]
    )

    st.markdown("<div style='height: 1.8rem'></div>", unsafe_allow_html=True)

    if not risks:
        render_empty_state("No risks were identified in the reviewed materials.")
        return

    by_category = risk_summary.get("by_category") or {}
    if by_category:
        chip_html = "".join(
            f'<span class="category-chip {category_accent(cat)}" style="margin-right:0.4rem;">{cat.upper()} · {count}</span>'
            for cat, count in by_category.items()
        )
        st.markdown(f'<div style="margin-bottom:1.2rem;">{chip_html}</div>', unsafe_allow_html=True)

    render_section_label("ALL RISKS", "Severity, category, evidence and recommended action for each finding.")

    severity_order = {"high": 0, "medium": 1, "low": 2}
    sorted_risks = sorted(risks, key=lambda r: severity_order.get(severity_class(r.get("severity")), 3))
    for risk in sorted_risks:
        render_risk_card(risk)


# ============================================================================
# STATE 2 — QUESTIONS
# ============================================================================

def render_questions() -> None:
    ai_analysis = st.session_state.ai_analysis or {}
    questions: List[str] = ai_analysis.get("management_questions") or []

    section_header(
        eyebrow="MANAGEMENT FOLLOW-UP",
        title="Questions for Management",
        subtitle="Evidence-backed questions generated from identified discrepancies, risks and missing evidence.",
    )

    if not questions:
        render_empty_state("No management questions were generated for this review.", neutral=True)
        return

    for i, question in enumerate(questions, start=1):
        st.markdown(
            f"""
            <div class="question-card">
                <div class="question-number">{i:02d}</div>
                <div class="question-text">{question}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ============================================================================
# STATE 2 — ASK DILIGENCE ROOM
# ============================================================================

STARTER_QUESTIONS = [
    "What are the highest-priority risks?",
    "How much cash runway does the company have?",
    "Why is the reported customer count inconsistent?",
    "Is the ownership structure internally consistent?",
    "What should we ask management before proceeding?",
]


def render_ask_diligence_room() -> None:
    evidence_store = st.session_state.evidence_store or []
    reconciliations = st.session_state.reconciliations or []
    financials = st.session_state.financials or {}
    risks = st.session_state.risks or []

    section_header(
        eyebrow="DOCUMENT INTELLIGENCE",
        title="Ask the Diligence Room",
        subtitle="Ask questions about the reviewed materials. Responses are grounded in the extracted evidence and identified findings.",
    )

    left, right = st.columns([1.6, 1])

    with left:
        query = st.text_input(
            "Query",
            value=st.session_state.ask_query,
            placeholder="Ask about financials, ownership, customers, legal risks, cash, or funding...",
            label_visibility="collapsed",
            key="diligence_query_input",
        )
        search_clicked = st.button("Ask", type="primary")

        st.markdown('<div class="section-sub" style="margin-top:0.8rem;margin-bottom:0.3rem;">Try one of these:</div>', unsafe_allow_html=True)
        chip_cols = st.columns(len(STARTER_QUESTIONS[:3]))
        chip_clicked = None
        for col, chip_q in zip(chip_cols, STARTER_QUESTIONS[:3]):
            with col:
                if st.button(chip_q, key=f"chip_{chip_q}", use_container_width=True):
                    chip_clicked = chip_q

        with st.expander("More starter questions"):
            for q in STARTER_QUESTIONS[3:]:
                if st.button(q, key=f"chip_more_{q}", use_container_width=True):
                    chip_clicked = q

        active_query = chip_clicked if chip_clicked else (query if search_clicked else None)

        if active_query:
            st.session_state.ask_query = active_query
            try:
                answer = ask_diligence_room(active_query, evidence_store, reconciliations, financials, risks)
            except Exception as exc:  # noqa: BLE001
                answer = f"The diligence room could not process this question ({exc})."
            st.session_state.ask_result = answer
            _rerun()

        if st.session_state.ask_result:
            st.markdown(
                f"""
                <div class="answer-box">
                    <div class="answer-heading">ANSWER</div>
                    <div class="answer-text">{st.session_state.ask_result}</div>
                    <div class="answer-context">Grounded in {len(evidence_store)} evidence item(s), {len(reconciliations)} discrepancy finding(s) and {len(risks)} risk item(s).</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with right:
        render_section_label("DILIGENCE SOURCES", "Documents currently indexed in this session.")
        documents = st.session_state.documents or []
        classifications = {c.get("file_name"): c for c in (st.session_state.classifications or [])}
        if documents:
            for doc in documents:
                file_name = doc.get("file_name", "Unknown file")
                classification = classifications.get(file_name, {})
                render_document_card(
                    file_name,
                    doc_type=classification.get("document_type"),
                    confidence=classification.get("classification_confidence"),
                    status="failed" if doc.get("error") else "ready",
                    status_label="Could not process" if doc.get("error") else "Ready",
                )
        else:
            render_empty_state("No documents indexed yet.", neutral=True)


# ============================================================================
# STATE 2 — DOCUMENTS
# ============================================================================

def render_documents() -> None:
    documents = st.session_state.documents or []
    classifications = {c.get("file_name"): c for c in (st.session_state.classifications or [])}
    evidence_store = st.session_state.evidence_store or []
    reconciliations = st.session_state.reconciliations or []
    risks = st.session_state.risks or []
    evidence_summary = summarize_evidence_store(evidence_store) if evidence_store else {"total_evidence_items": 0}

    section_header(
        eyebrow="DATA ROOM",
        title="Documents",
        subtitle="What was actually uploaded, how it was classified, and what evidence it produced.",
    )

    render_metric_row(
        [
            {"label": "DOCUMENTS", "value": str(len(documents)), "sub": "Uploaded this session", "accent": "indigo"},
            {"label": "EVIDENCE ITEMS", "value": str(evidence_summary.get("total_evidence_items", 0)), "sub": "Extracted in total", "accent": "teal"},
            {"label": "DISCREPANCIES", "value": str(len(reconciliations)), "sub": "Cross-document", "accent": "violet"},
            {"label": "RISKS", "value": str(len(risks)), "sub": "Flagged for review", "accent": "warning"},
        ]
    )

    st.markdown("<div style='height: 1.8rem'></div>", unsafe_allow_html=True)
    render_section_label("DOCUMENT INVENTORY", "Filename, classification and how much each document contributed.")

    if not documents:
        render_empty_state("No documents have been analyzed in this session.", neutral=True)
        return

    for doc in documents:
        file_name = doc.get("file_name", "Unknown file")
        classification = classifications.get(file_name, {})
        doc_evidence_count = sum(1 for e in evidence_store if isinstance(e, dict) and e.get("file_name") == file_name)

        related_findings = 0
        for rec in reconciliations:
            if safe_get(rec, "source_a", "file_name") == file_name or safe_get(rec, "source_b", "file_name") == file_name:
                related_findings += 1
        for risk in risks:
            for item in risk.get("evidence") or []:
                if isinstance(item, dict) and item.get("file_name") == file_name:
                    related_findings += 1
                    break

        render_document_card(
            file_name,
            doc_type=classification.get("document_type"),
            confidence=classification.get("classification_confidence"),
            evidence_count=doc_evidence_count,
            finding_count=related_findings,
            status="failed" if doc.get("error") else "ready",
            status_label="Could not process" if doc.get("error") else "Classified",
        )


# ============================================================================
# STATE 2 — SETTINGS
# ============================================================================

def render_settings() -> None:
    section_header(
        eyebrow="WORKSPACE",
        title="Settings & Analysis Info",
        subtitle="Environment status and controls for the current diligence session.",
    )

    ai_key_present = bool(os.getenv("GEMINI_API_KEY"))
    ai_analysis = st.session_state.ai_analysis or {}
    exec_summary = ai_analysis.get("executive_summary") or {}
    exec_source = exec_summary.get("source") or "Unknown"
    ai_model = ai_analysis.get("ai_model") or DASH

    # The executive summary carries the error for the call that actually
    # decides the AI/fallback badge on Overview. Fall back to the
    # top-level ai_error (set at the end of run_ai_analysis) only if the
    # summary itself did not record one.
    last_ai_error = exec_summary.get("error") or ai_analysis.get("ai_error")
    error_category = classify_ai_error(last_ai_error)

    render_section_label("AI ENGINE STATUS")
    render_snapshot_rows(
        [
            ("GEMINI_API_KEY detected", "Yes" if ai_key_present else "No"),
            ("Last analysis source", exec_source),
            ("AI model", ai_model),
            ("Behavior without a key", "Deterministic fallback (no external calls)"),
        ]
    )

    if exec_source != "AI" and (error_category or last_ai_error):
        st.markdown("<div style='height: 1rem'></div>", unsafe_allow_html=True)
        st.warning(f"AI unavailable — {error_category or 'AI request failed'}")
        with st.expander("Show technical detail"):
            st.code(last_ai_error or "No detail captured.", language=None)

    st.markdown("<div style='height: 1.6rem'></div>", unsafe_allow_html=True)
    render_section_label("SESSION")
    work_dir = st.session_state.get("work_dir") or DASH
    render_snapshot_rows(
        [
            ("Documents in session", str(len(st.session_state.documents or []))),
            ("Working directory", work_dir),
            ("Analysis status", "Complete" if st.session_state.analysis_complete else "Not run"),
        ]
    )

    st.markdown("<div style='height: 1.6rem'></div>", unsafe_allow_html=True)
    render_section_label("ACTIONS")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("↻  Rerun Analysis", use_container_width=True):
            wd = st.session_state.get("work_dir")
            if wd and Path(wd).exists():
                run_pipeline(Path(wd))
                _rerun()
            else:
                st.warning("Original files are no longer available. Please start a new analysis.")
    with col2:
        if st.button("＋  Start New Analysis", use_container_width=True):
            reset_analysis(delete_files=True)
            _rerun()


# ============================================================================
# MAIN ROUTING
# ============================================================================

PAGES = {
    "Overview": render_overview,
    "Financials": render_financials,
    "Risk Flags": render_risk_flags,
    "Questions": render_questions,
    "Ask Diligence Room": render_ask_diligence_room,
    "Documents": render_documents,
    "Settings": render_settings,
}


def render_backend_error() -> None:
    st.markdown(
        """
        <div class="hero-wrap">
            <div class="hero-eyebrow">SETUP REQUIRED</div>
            <div class="hero-title">Backend modules not found</div>
            <div class="hero-subtitle">
                This app expects a <code>src/</code> package with document_extractor,
                document_classifier, evidence_engine, reconciliation_engine,
                financial_engine, risk_engine and ai_engine modules alongside app.py.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.error(f"Import error: {BACKEND_IMPORT_ERROR}")
    st.caption(f"Expected location: {APP_DIR / 'src'}")


def main() -> None:
    load_css()

    if BACKEND_IMPORT_ERROR:
        render_backend_error()
        return

    render_sidebar()

    if not st.session_state.analysis_complete:
        render_landing()
    else:
        render_top_header(st.session_state.page)
        PAGES[st.session_state.page]()

    render_footer()


if __name__ == "__main__":
    main()