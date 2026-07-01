"""
guardrails/output_guards.py
=============================
Output-side guardrails:
    1. Hallucination check — LLM judge: is the answer grounded in the
       retrieved context (citations/chunks)?
    2. PII re-scan on the generated answer (reuses input_guards' detector)
    3. Toxicity / unsafe-content filter (lightweight keyword heuristic — no
       extra model dependency required)

Usage:
    from app.guardrails.output_guards import check_output
    result = check_output(answer, context_chunks=chunks)
    # result = {
    #   "allowed": bool,
    #   "text": str,             # possibly redacted answer
    #   "flags": [...],
    #   "reasons": [...],
    #   "grounded": bool | None, # None if judge couldn't run
    #   "block_reason": str | None,
    # }
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# 1. Hallucination check via LLM judge
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM_PROMPT = """\
You are a strict fact-checking judge. You will be given CONTEXT passages and an ANSWER.
Determine whether the ANSWER is grounded in (supported by) the CONTEXT.

Respond with STRICT JSON only:
{"grounded": true|false, "confidence": 0.0-1.0, "reason": "short explanation"}

Guidelines:
- "grounded": true if the answer's claims are supported by the context, OR if the answer
  correctly states it doesn't have enough information.
- "grounded": false if the answer asserts specific facts (names, numbers, causes) that are
  NOT present in the context.
- Minor rephrasing/summarizing is fine and still grounded.
"""


def _get_llm_client():
    from openai import OpenAI

    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)


def check_hallucination(answer: str, context_text: str) -> dict[str, Any]:
    """LLM-judge check: is `answer` grounded in `context_text`?
    Degrades to {"grounded": None, ...} if the judge call fails."""
    if not context_text.strip():
        # Nothing retrieved — can't judge groundedness either way.
        return {"grounded": None, "confidence": 0.0, "reason": "No context available to judge against."}

    try:
        client = _get_llm_client()
        completion = client.chat.completions.create(
            model=settings.llm_default_model,
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"CONTEXT:\n{context_text[:4000]}\n\nANSWER:\n{answer[:2000]}",
                },
            ],
            temperature=0.0,
            max_tokens=200,
        )
        raw = completion.choices[0].message.content or "{}"
        import json

        text = raw.strip()
        text = re.sub(r"^```(json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(match.group(0)) if match else json.loads(text)
        return {
            "grounded": bool(data.get("grounded", True)),
            "confidence": float(data.get("confidence", 0.5)),
            "reason": str(data.get("reason", "")),
        }
    except Exception as exc:
        log.warning("hallucination_judge_failed", error=str(exc))
        return {"grounded": None, "confidence": 0.0, "reason": f"Judge unavailable: {exc}"}


# ---------------------------------------------------------------------------
# 2. PII re-scan (reuse input_guards detector)
# ---------------------------------------------------------------------------

# Restricted to genuinely sensitive PII. PERSON / LOCATION are deliberately
# excluded here: this is an internal enterprise knowledge base where staff
# and team names (e.g. "Priya Sharma", "Billing") are expected, legitimate
# content — masking them would mangle correct answers and falsely trip the
# hallucination judge (masked names no longer match the source context).
_OUTPUT_PII_ENTITIES = [
    "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN",
    "US_BANK_NUMBER", "IBAN_CODE", "IP_ADDRESS",
]


def rescan_pii(text: str) -> tuple[str, list[str]]:
    from app.guardrails.input_guards import detect_and_mask_pii

    return detect_and_mask_pii(text, entities=_OUTPUT_PII_ENTITIES)


# ---------------------------------------------------------------------------
# 3. Toxicity / unsafe-content filter (lightweight heuristic)
# ---------------------------------------------------------------------------

_TOXIC_PATTERNS = [
    r"\bkill yourself\b", r"\bhate speech\b", r"\bslur\b",
    r"\bhow to (make|build) a (bomb|weapon|explosive)\b",
    r"\b(racist|sexist) (joke|comment)\b",
]
_TOXIC_RE = re.compile("|".join(_TOXIC_PATTERNS), re.IGNORECASE)


def detect_toxicity(text: str) -> bool:
    return bool(_TOXIC_RE.search(text))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_output(
    answer: str,
    context_text: str = "",
    run_hallucination_check: bool = True,
) -> dict[str, Any]:
    """
    Run all output guardrails on the generated `answer`.

    Parameters
    ----------
    answer  : The LLM-generated answer text.
    context_text : Concatenated retrieved context (for the hallucination judge).
    run_hallucination_check : Set False to skip the (extra LLM-call) judge,
        e.g. for latency-sensitive paths or cache hits.

    Returns
    -------
    See module docstring.
    """
    flags: list[str] = []
    reasons: list[str] = []

    # PII re-scan
    masked_text, pii_entities = rescan_pii(answer)
    if pii_entities:
        flags.append("pii_masked_output")
        reasons.append(f"Masked PII in output: {', '.join(pii_entities)}")
        answer = masked_text

    # Toxicity filter
    if detect_toxicity(answer):
        flags.append("toxic_content")
        reasons.append("Output flagged for toxic/unsafe content.")
        return {
            "allowed": False,
            "text": "I can't provide that response.",
            "flags": flags,
            "reasons": reasons,
            "grounded": None,
            "block_reason": "Output blocked by toxicity filter.",
        }

    # Hallucination / groundedness check
    grounded: bool | None = None
    if run_hallucination_check:
        judge = check_hallucination(answer, context_text)
        grounded = judge["grounded"]
        if grounded is False:
            flags.append("possible_hallucination")
            reasons.append(f"Hallucination judge: {judge['reason']}")
            log.warning("possible_hallucination_detected", reason=judge["reason"])
            # Don't hard-block (judge can be wrong) — flag it and prepend a caveat instead.
            answer = (
                "_Note: parts of this answer may not be fully grounded in retrieved sources._\n\n"
                + answer
            )

    return {
        "allowed": True,
        "text": answer,
        "flags": flags,
        "reasons": reasons,
        "grounded": grounded,
        "block_reason": None,
    }
