# Project Plans — Every Version, Start to End

This folder preserves **all the plans** that guided this project. They were originally written
to Claude Code's single per-conversation plan file, which gets **overwritten** each time plan
mode is re-entered — so only the latest survived on disk. These are the recovered, permanent
copies.

> 🔑 Why there was only one file: Claude Code keeps **one plan file per conversation**
> (`i-want-o-design-velvet-muffin.md`). Every time we re-planned, the new plan replaced the old
> one in that same file. We re-planned three times, so two earlier plans were overwritten.

---

## The plans

| Version | File | What it planned |
|---|---|---|
| **V1** | [v1-build-and-orchestration-plan.md](v1-build-and-orchestration-plan.md) | Building the whole app — including the **Opus-as-orchestrator + Sonnet Builder/Validator/Repair** subagent model, Phase 1/Phase 2 split, env keys, and final validation. |
| **V2** | [v2-teaching-course-plan.md](v2-teaching-course-plan.md) | The **19-chapter beginner teaching course** in `docs/course/`. |

*(A third planning session — this recovery task — is what produced this folder.)*

---

## Timeline: how the plan evolved

1. **Initial draft (V1 being written).** First version of the build plan: Chainlit frontend,
   full-as-spec scope, **OpenAI** as the LLM, Docker for Neo4j + Redis.
2. **V1 grew through edits** (before approval), adding, in order:
   - Plan Storage (copy plan into the repo),
   - the **Environment Variables** table + how to generate each key,
   - the **Phase 1 / Phase 2** split with a validation gate,
   - the **final `validate.py`** system health-check section,
   - the **Data (vector vs graph)** section + the fake-data generator + the INC-204 worked example,
   - the **Execution Model — orchestrated subagents** section (Builder → Validator → Repair).
3. **V1 approved** → we built the app with that orchestration model.
4. **Mid-build changes** (decisions made while building, not in the written plan — captured in V1's
   "evolution note"):
   - **OpenAI → OpenRouter** for chat (one key, many models) and **embeddings moved local**
     (OpenRouter has no embeddings endpoint; local is free).
   - **Docker Neo4j → Neo4j Aura** free cloud (no Docker installed on the machine).
   - **fakeredis** instead of a real Redis server for the semantic cache.
   - **gpt-4.1 → gpt-4o** family (gpt-4.1's Responses-API format broke LangGraph tool calls).
5. **V2 approved** → we wrote the teaching course (this overwrote V1 in the plan file).
6. **This recovery** → both plans reproduced here permanently.

---

## Why some intermediate drafts aren't separate files

Between the initial draft and the approved V1, the plan changed via **incremental edits** to the
same file. Those in-between states weren't captured as separate full-text snapshots (only the
final **approved** V1 was echoed verbatim in the conversation). The list above (step 2) is the
faithful record of what was added and in what order — that's the "every version" evolution, even
though we only keep the two complete approved plans as standalone files.

---

## Related docs
- [../PROJECT_GUIDE.md](../PROJECT_GUIDE.md) — plain-English walkthrough of the finished system.
- [../ARCHITECTURE.md](../ARCHITECTURE.md) — final architecture (reflects the mid-build changes).
- [../course/README.md](../course/README.md) — the full teaching course (V2's output).
