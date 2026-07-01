"""
routing/model_router.py
==========================
Complexity-based model router: choose settings.llm_default_model (cheap,
fast) vs settings.llm_advanced_model (stronger, slower/costlier) based on
heuristics over the query text.

Usage:
    from app.routing.model_router import route_model
    model, reason = route_model(query)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

# Multi-hop / reasoning indicators
_MULTI_HOP_PATTERNS = [
    r"\band\b.*\bwho\b", r"\band\b.*\bwhat\b", r"\bif\b.*\bthen\b",
    r"\bdepends? on\b", r"\bwho (do i|should i) (contact|call|escalate)\b",
    r"\bwhy\b.*\bcaused?\b", r"\bcompare\b", r"\bdifference between\b",
    r"\bstep[s]? (to|for)\b", r"\bwhat.*and.*who\b", r"\bhow many\b.*\band\b",
]
_MULTI_HOP_RE = re.compile("|".join(_MULTI_HOP_PATTERNS), re.IGNORECASE)

# Indicators that the query likely needs tool use (sql/calc) beyond simple retrieval
_TOOL_NEED_PATTERNS = [
    r"\bsum\b", r"\btotal\b", r"\baverage\b", r"\bcount\b", r"\bcalculate\b",
    r"\bhow much\b", r"\bhow many\b", r"\btop \d+\b", r"\bquery\b",
]
_TOOL_NEED_RE = re.compile("|".join(_TOOL_NEED_PATTERNS), re.IGNORECASE)

_LONG_QUERY_CHAR_THRESHOLD = 220
_LONG_QUERY_WORD_THRESHOLD = 35


def _complexity_score(query: str) -> tuple[int, list[str]]:
    """Return (score, reasons). Higher score => more complex => advanced model."""
    score = 0
    reasons: list[str] = []

    n_chars = len(query)
    n_words = len(query.split())

    if n_chars > _LONG_QUERY_CHAR_THRESHOLD or n_words > _LONG_QUERY_WORD_THRESHOLD:
        score += 1
        reasons.append("long_query")

    if _MULTI_HOP_RE.search(query):
        score += 2
        reasons.append("multi_hop_indicator")

    if _TOOL_NEED_RE.search(query):
        score += 1
        reasons.append("tool_need_indicator")

    # Multiple question marks / conjunctions suggest compound questions
    if query.count("?") > 1:
        score += 1
        reasons.append("multiple_questions")
    if len(re.findall(r"\band\b", query, re.IGNORECASE)) >= 2:
        score += 1
        reasons.append("multiple_conjunctions")

    return score, reasons


def route_model(query: str, threshold: int = 2) -> tuple[str, dict]:
    """
    Choose the model to use for `query`.

    Returns
    -------
    (model_name, info) where info = {"score": int, "reasons": [str], "tier": "default"|"advanced"}
    """
    score, reasons = _complexity_score(query)
    if score >= threshold:
        model = settings.llm_advanced_model
        tier = "advanced"
    else:
        model = settings.llm_default_model
        tier = "default"

    info = {"score": score, "reasons": reasons, "tier": tier}
    log.info("model_routed", model=model, score=score, tier=tier, reasons=reasons)
    return model, info
