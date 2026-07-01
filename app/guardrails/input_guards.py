"""
guardrails/input_guards.py
============================
Input-side guardrails:
    1. Length/format validation
    2. Prompt-injection detection (heuristics/regex)
    3. PII detection + masking (Presidio, with regex fallback if Presidio's
       spaCy model isn't available for some reason)

Usage:
    from app.guardrails.input_guards import check_input
    result = check_input(user_message)
    # result = {
    #   "allowed": bool,
    #   "text": str,            # possibly PII-masked text to use downstream
    #   "flags": [str, ...],    # e.g. ["prompt_injection", "pii_masked"]
    #   "reasons": [str, ...],
    #   "block_reason": str | None,
    # }
"""
from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# 1. Length / format validation
# ---------------------------------------------------------------------------

def _validate_format(text: str) -> list[str]:
    reasons: list[str] = []
    if not text or not text.strip():
        reasons.append("empty_input")
    if len(text) > settings.max_input_chars:
        reasons.append("input_too_long")
    return reasons


# ---------------------------------------------------------------------------
# 2. Prompt-injection heuristics
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = [
    r"ignore (all )?(the )?(previous|prior|above) instructions",
    r"disregard (all )?(the )?(previous|prior|above) instructions",
    r"forget (all )?(the )?(previous|prior|above) instructions",
    r"(ignore|disregard|forget) (all )?(the |your |these )?(context|guardrails|rules|restrictions|safety)",
    r"bypass (the |your )?(login|authentication|auth|security|access|sign[- ]?in)",
    r"output (the )?(raw )?(contents of your |your )?(configuration|config|system)",
    r"you are now (a|an) ",
    r"act as (a|an) ",
    r"\bsystem prompt\b",
    r"reveal (your|the) (system )?prompt",
    r"print (your|the) (system )?prompt",
    r"what (are|is) your (instructions|system prompt)",
    r"new instructions[:\s]",
    r"override (your|the) (instructions|rules|guardrails)",
    r"jailbreak",
    r"\bDAN\b",
    r"do anything now",
    r"\bsudo\b",
    r"developer mode",
    r"bypass (your|the) (restrictions|filters|guardrails|safety)",
    r"pretend (you|to) (are|be)",
    r"roleplay as",
    r"exfiltrat(e|ion)",
    r"leak (the|your) (api key|secret|password|credentials)",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def _detect_injection(text: str) -> bool:
    return bool(_INJECTION_RE.search(text))


# ---------------------------------------------------------------------------
# 3. PII detection + masking (Presidio, with regex fallback)
# ---------------------------------------------------------------------------

_PII_ENTITIES = [
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN",
    "US_BANK_NUMBER", "IBAN_CODE", "IP_ADDRESS", "LOCATION",
]

# Regex fallback patterns (used if Presidio fails to init, e.g. spaCy model missing)
_REGEX_PII = {
    "EMAIL_ADDRESS": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "US_SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "PHONE_NUMBER": re.compile(r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
}


@lru_cache(maxsize=1)
def _get_presidio_analyzer():
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        # Pin to the small spaCy model that's already installed in this env
        # (en_core_web_sm) — Presidio's default config wants en_core_web_lg
        # which would trigger a slow ~400MB auto-download on first use.
        nlp_config = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
        provider = NlpEngineProvider(nlp_configuration=nlp_config)
        nlp_engine = provider.create_engine()
        return AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
    except Exception as exc:
        log.warning("presidio_analyzer_init_failed_using_regex_fallback", error=str(exc))
        return None


@lru_cache(maxsize=1)
def _get_presidio_anonymizer():
    try:
        from presidio_anonymizer import AnonymizerEngine

        return AnonymizerEngine()
    except Exception as exc:
        log.warning("presidio_anonymizer_init_failed_using_regex_fallback", error=str(exc))
        return None


def _mask_with_regex(text: str, entities: list[str] | None = None) -> tuple[str, list[str]]:
    found: list[str] = []
    masked = text
    allowed = set(entities) if entities is not None else set(_REGEX_PII.keys())
    for entity, pattern in _REGEX_PII.items():
        if entity not in allowed:
            continue
        if pattern.search(masked):
            found.append(entity)
            masked = pattern.sub(f"<{entity}>", masked)
    return masked, found


def detect_and_mask_pii(text: str, entities: list[str] | None = None) -> tuple[str, list[str]]:
    """Return (masked_text, entity_types_found).

    `entities` optionally restricts which PII types to detect/mask (defaults
    to `_PII_ENTITIES`, the full set). Output-side guardrails pass a
    restricted set that excludes PERSON/LOCATION, since employee/team names
    are legitimate, expected content in this internal knowledge base —
    masking them there causes false "hallucination" flags and destroys
    useful answers. Input-side guardrails still mask PERSON for safety.
    """
    target_entities = entities if entities is not None else _PII_ENTITIES
    analyzer = _get_presidio_analyzer()
    anonymizer = _get_presidio_anonymizer()

    if analyzer is None or anonymizer is None:
        return _mask_with_regex(text, target_entities)

    try:
        results = analyzer.analyze(text=text, entities=target_entities, language="en")
        if not results:
            return text, []
        anonymized = anonymizer.anonymize(text=text, analyzer_results=results)
        entity_types = sorted({r.entity_type for r in results})
        return anonymized.text, entity_types
    except Exception as exc:
        log.warning("presidio_run_failed_using_regex_fallback", error=str(exc))
        return _mask_with_regex(text, target_entities)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_input(text: str) -> dict[str, Any]:
    """
    Run all input guardrails on `text`.

    Returns
    -------
    {
        "allowed": bool,
        "text": str,             # text to use downstream (PII-masked if applicable)
        "flags": [str, ...],
        "reasons": [str, ...],
        "block_reason": str | None,
    }
    """
    flags: list[str] = []
    reasons: list[str] = []

    format_issues = _validate_format(text)
    if format_issues:
        reasons.extend(format_issues)
        return {
            "allowed": False,
            "text": text,
            "flags": ["invalid_format"],
            "reasons": reasons,
            "block_reason": "Input failed format validation: " + ", ".join(format_issues),
        }

    injection_detected = _detect_injection(text)
    if injection_detected:
        flags.append("prompt_injection")
        reasons.append("Detected likely prompt-injection pattern in input.")
        log.warning("prompt_injection_detected", text_preview=text[:120])
        return {
            "allowed": False,
            "text": text,
            "flags": flags,
            "reasons": reasons,
            "block_reason": "Your message looks like it is attempting to override system instructions, "
                             "so it was blocked.",
        }

    masked_text, pii_entities = detect_and_mask_pii(text)
    if pii_entities:
        flags.append("pii_masked")
        reasons.append(f"Masked PII entities: {', '.join(pii_entities)}")
        log.info("pii_masked", entities=pii_entities)

    return {
        "allowed": True,
        "text": masked_text,
        "flags": flags,
        "reasons": reasons,
        "block_reason": None,
    }
