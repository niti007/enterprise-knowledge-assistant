# RAGAS Evaluation Report — Enterprise Knowledge Assistant

_Generated: 2026-07-01T19:35:32+00:00_

- Samples: 8  |  Judge LLM: `openai/gpt-4o-mini` (OpenRouter)
- Embeddings: `all-MiniLM-L6-v2` (local)

## Aggregate metrics

| Metric | Score |
|---|---|
| faithfulness | 0.637 |
| answer_relevancy | 0.798 |
| context_precision | 0.441 |
| context_recall | 0.750 |

## Per-question scores

| Question | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|
| Who owns the Payment-Service? | 0.50 | 0.93 | 0.37 | 1.00 |
| What does the Payment-Service depend on? | 0.00 | 0.68 | 0.21 | 0.00 |
| Which SOP is used to restore the Payment-Service? | 0.50 | 0.68 | 0.75 | 1.00 |
| Which team manages the Data Warehouse? | 1.00 | 0.90 | 0.76 | 1.00 |
| Who is the incident lead for INC-204? | 1.00 | 0.51 | 0.00 | 0.00 |
| What caused the Payment-Service outage in INC-204? | 0.50 | 0.76 | 0.25 | 1.00 |
| What was the severity of incident INC-204? | 1.00 | 0.92 | 0.50 | 1.00 |
| Who manages the Billing team? | 0.60 | 1.00 | 0.70 | 1.00 |

## Metric definitions

- **Faithfulness**: is the answer grounded in the retrieved context (no hallucination)?
- **Answer relevancy**: does the answer address the question?
- **Context precision**: are the retrieved passages relevant (signal vs noise)?
- **Context recall**: did retrieval surface the info needed to match the ground truth?
