# Chapter 16 — Testing & Evaluation (proving it works)

Anyone can say "my AI app works." Real engineers **measure** it. This chapter shows the four
kinds of tests this project uses, what each one proves, and how to read the numbers.

> 🔑 **New word — evaluation:** measuring how good an AI system's answers are, with numbers
> instead of opinions.

All test files live in the `eval/` folder; the reports they produce land in `docs/`.

---

## 1. Promptfoo — a big Q&A + safety test

> 🔑 **New word — regression test:** a saved set of questions with expected answers you can
> re-run any time to check nothing broke.

`eval/promptfooconfig.yaml` lists **31 test cases** — real questions plus attack prompts —
and what a good answer should contain. It sends each to the running app and checks the result.

Run it (the app must be running on port 8001):
```powershell
cd eval
npx -y promptfoo@latest eval -c promptfooconfig.yaml
cd ..
```
- **What it proves:** the assistant answers correctly *and* blocks unsafe prompts, across many
  cases at once.
- **Our result:** **29 / 31 passed (93.5%)**.
- **How to read it:** each row is PASS/FAIL. Failures show exactly which check didn't match —
  that's your to-do list for improvements.

---

## 2. RAGAS — answer-quality scores

> 🔑 **New word — RAGAS:** a tool that scores RAG answers on four qualities using an AI judge.

`eval/ragas_eval.py` asks the app several questions, then scores the answers:

| Score | Plain meaning | Our result |
|---|---|---|
| **Faithfulness** | Does the answer stick to the sources (no making things up)? | 0.64 |
| **Answer relevancy** | Does the answer actually address the question? | 0.80 |
| **Context precision** | Were the retrieved passages on-topic (little noise)? | 0.44 |
| **Context recall** | Did search find the info needed for the right answer? | 0.75 |

Run it (in its own separate environment so it can't disturb the app's libraries):
```powershell
py -3.12 -m venv .venv-eval
.venv-eval\Scripts\python.exe -m pip install ragas==0.2.15 langchain-openai langchain-huggingface sentence-transformers datasets requests
.venv-eval\Scripts\python.exe -m eval.ragas_eval
```
- **How to read it:** all scores are 0–1, higher is better. Our **context precision (0.44)** is
  the weakest — it means retrieval also pulls in some off-topic pieces. That's an honest,
  known weak spot and a great thing to discuss when presenting ("here's what I'd improve").

---

## 3. Safety scorecard — attack prompts

`eval/safety_eval.py` throws 16 nasty prompts at the app (injection attempts, requests for
private data, harmful requests, and made-up-fact bait) and checks each was handled safely.

Run it:
```powershell
.venv\Scripts\python.exe -m eval.safety_eval
```
- **What it proves:** the guardrails actually work under attack.
- **Our result:** **15 / 16 handled safely (93.8%)** → written to `docs/SAFETY_SCORECARD.md`.

---

## 4. Load test — speed under pressure

`eval/load_test.py` fires many requests at once and measures speed.

Run it (app must be running):
```powershell
.venv\Scripts\python.exe -m eval.load_test
```
- **What it proves:** the app stays responsive, and the cache really helps.
- **Our result:** typical answer ~2.8s (p50), and **cache hits are ~6× faster** than misses.
  > 🔑 **New word — p50 (median):** half of requests were faster than this number, half slower.

---

## Why bother with all this?
- It turns "trust me, it works" into **evidence** (great for a portfolio or a grade).
- It catches problems early — re-run the tests after any change.
- It shows the honest weak spots, which is exactly what real teams want to see.

---

## ✅ You just learned
- Four kinds of evaluation: Promptfoo (broad Q&A + safety), RAGAS (answer quality), safety
  scorecard (attacks), load test (speed).
- What each score means and how to read it.
- Why measuring beats claiming.

## ▶️ Run this now
```powershell
.venv\Scripts\python.exe -m eval.safety_eval
```

## 🧠 Check yourself
1. Which test would catch the assistant **making things up**?
2. What does a **cache hit** do to response time, roughly?
3. Why do we run RAGAS in a **separate** virtual environment?

---

Next: put the app on the internet so anyone can use it →
[17-deployment.md](17-deployment.md)
