"""
eval/ragas_eval.py — Phase 2 (T10)
===================================
RAGAS evaluation of the running assistant: faithfulness, answer relevancy,
context precision, context recall.

Design:
- Questions + ground-truth answers are grounded in the generated corpus.
- For each question we call the live API (http://localhost:8001/chat) and pull
  the answer + the retrieved contexts (from the agent's `retrieve` tool output,
  falling back to citation snippets).
- RAGAS metrics are computed with an OpenRouter chat model as the judge LLM and
  a LOCAL HuggingFace embedding model (OpenRouter has no embeddings endpoint).

Run in the ISOLATED eval venv (protects the app's langchain), with the API up:
    .venv-eval\\Scripts\\python.exe -m eval.ragas_eval
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
API = "http://localhost:8001/chat"

# Load .env so the OpenRouter key/base_url are available.
def _load_env() -> dict:
    env = {}
    envfile = ROOT / ".env"
    if envfile.exists():
        for line in envfile.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


# Eval set — questions with reference (ground-truth) answers grounded in the corpus.
EVAL_SET = [
    {"q": "Who owns the Payment-Service?",
     "gt": "The Payment-Service is owned by the Billing team, led by Priya Sharma."},
    {"q": "What does the Payment-Service depend on?",
     "gt": "The Payment-Service depends on Auth-DB for authentication and session validation."},
    {"q": "Which SOP is used to restore the Payment-Service?",
     "gt": "SOP-17, the Payment Service Restoration procedure, is used to restore it."},
    {"q": "Which team manages the Data Warehouse?",
     "gt": "The Data Warehouse is managed by the Data Engineering team, led by Chen Wei."},
    {"q": "Who is the incident lead for INC-204?",
     "gt": "Priya Sharma is the incident lead for INC-204."},
    {"q": "What caused the Payment-Service outage in INC-204?",
     "gt": "The outage was caused by Auth-DB hitting its connection limits."},
    {"q": "What was the severity of incident INC-204?",
     "gt": "INC-204 was a P1 severity incident."},
    {"q": "Who manages the Billing team?",
     "gt": "The Billing team is managed by Priya Sharma."},
]


def _contexts_from_response(body: dict) -> list[str]:
    """Prefer full retrieve-tool passages; fall back to citation snippets."""
    ctxs: list[str] = []
    for call in body.get("tool_calls", []) or []:
        if call.get("tool") == "retrieve":
            out = call.get("output", "") or ""
            for passage in out.split("\n\n"):
                p = passage.strip()
                if p:
                    ctxs.append(p)
    if not ctxs:
        for c in body.get("citations", []) or []:
            snip = c.get("snippet")
            if snip:
                ctxs.append(f"[{c.get('source','?')}] {snip}")
    return ctxs[:8] or ["(no context retrieved)"]


def collect_samples() -> list[dict]:
    samples = []
    for i, item in enumerate(EVAL_SET, 1):
        r = requests.post(API, json={"message": item["q"], "session_id": f"ragas-{i}"}, timeout=180)
        r.raise_for_status()
        body = r.json()
        samples.append({
            "user_input": item["q"],
            "response": body.get("answer", ""),
            "retrieved_contexts": _contexts_from_response(body),
            "reference": item["gt"],
        })
        print(f"  [{i}/{len(EVAL_SET)}] collected: {item['q'][:50]}")
    return samples


def main() -> None:
    env = _load_env()
    api_key = env.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base_url = env.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    judge_model = env.get("LLM_DEFAULT_MODEL", "openai/gpt-4o-mini")

    # Preflight API
    try:
        requests.get("http://localhost:8001/health", timeout=10).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"API not reachable — start uvicorn on :8001 first. ({exc})")
        sys.exit(1)

    print(f"Collecting {len(EVAL_SET)} samples from the live pipeline...")
    samples = collect_samples()

    print("Loading RAGAS + judge model (OpenRouter) + local embeddings...")
    from langchain_openai import ChatOpenAI
    from langchain_huggingface import HuggingFaceEmbeddings
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )

    judge = LangchainLLMWrapper(ChatOpenAI(
        model=judge_model, api_key=api_key, base_url=base_url, temperature=0.0,
    ))
    embeddings = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    )

    dataset = EvaluationDataset.from_list(samples)
    metrics = [faithfulness, answer_relevancy, context_precision, context_recall]

    print("Running RAGAS evaluation (LLM-judged; this calls OpenRouter)...")
    result = evaluate(dataset=dataset, metrics=metrics, llm=judge, embeddings=embeddings)

    scores = result._repr_dict if hasattr(result, "_repr_dict") else dict(result)
    print("\nRAGAS scores:", scores)

    # Write report
    df = result.to_pandas()
    lines = ["# RAGAS Evaluation Report — Enterprise Knowledge Assistant\n"]
    lines.append(f"_Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}_\n")
    lines.append(f"- Samples: {len(samples)}  |  Judge LLM: `{judge_model}` (OpenRouter)")
    lines.append("- Embeddings: `all-MiniLM-L6-v2` (local)\n")
    lines.append("## Aggregate metrics\n")
    lines.append("| Metric | Score |")
    lines.append("|---|---|")
    for metric in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
        if metric in df.columns:
            val = df[metric].dropna().mean()
            lines.append(f"| {metric} | {val:.3f} |")
    lines.append("\n## Per-question scores\n")
    cols = [c for c in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"] if c in df.columns]
    header = "| Question | " + " | ".join(cols) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(cols) + 1))
    for _, row in df.iterrows():
        q = str(row.get("user_input", ""))[:50].replace("|", "\\|")
        vals = " | ".join(f"{row[c]:.2f}" if row[c] == row[c] else "n/a" for c in cols)
        lines.append(f"| {q} | {vals} |")
    lines.append("\n## Metric definitions\n")
    lines.append("- **Faithfulness**: is the answer grounded in the retrieved context (no hallucination)?")
    lines.append("- **Answer relevancy**: does the answer address the question?")
    lines.append("- **Context precision**: are the retrieved passages relevant (signal vs noise)?")
    lines.append("- **Context recall**: did retrieval surface the info needed to match the ground truth?\n")

    out = ROOT / "docs" / "RAGAS_REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {out}")


if __name__ == "__main__":
    main()
