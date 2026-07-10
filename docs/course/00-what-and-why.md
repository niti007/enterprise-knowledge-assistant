# Chapter 00 — What We're Building and Why

Welcome! Before we install anything, let's understand **what** we're building and **why**
each piece exists. If you understand the "why," the code later will make sense instead of
feeling like magic.

---

## The problem we're solving

Imagine a big company with **thousands of documents**: policy PDFs, technical manuals,
step-by-step guides, incident reports, FAQs, and spreadsheets. An employee has a question:

> "If the Payment system goes down, what else breaks, and who do I call?"

Today they'd search a wiki, get 50 results, open ten of them, and still not be sure. Normal
search is bad at questions that need **connecting facts across documents**.

We're building an **AI assistant** that:
1. Reads all those documents and answers in plain language.
2. **Shows its sources** (so you can trust it).
3. Can **connect the dots** across documents (multi-step questions).
4. **Refuses unsafe requests** and **hides private data**.
5. **Records everything** so we can measure and improve it.

> 🔑 **New word — AI assistant:** a program that understands your question in normal
> language and answers it, here using a Large Language Model (the technology behind ChatGPT).

**A simple picture to hold in your head:** think of a **very well-read librarian** who has
also memorized an **org chart** of how every system and team connects — and who always
tells you the exact document each fact came from.

---

## The big picture (how a question flows)

Your question travels through an **assembly line**. Each station does one job:

```
Your question
   ↓
1. Safety check (in)   → is this safe? hide private info like emails/SSNs
   ↓
2. Memory (cache)      → did we already answer something almost identical? reuse it (instant)
   ↓
3. Router              → is this easy or hard? pick a cheap or a smarter AI model
   ↓
4. Agent + tools       → search the documents + the relationship map, keep the best bits
   ↓
5. AI writes answer    → using ONLY what it found, with [Source: ...] tags
   ↓
6. Safety check (out)  → is the answer backed by the sources? any private data? anything toxic?
   ↓
7. Recording           → save how long it took, how much it cost, every step
   ↓
Answer + sources → you
```

We build these stations one chapter at a time, then wire them together in
**Chapter 12 (the pipeline)**.

---

## Why each technology? (what's the need)

This project uses several tools. Here's **what each is, why we need it, and what would
break without it** — in plain words.

### 🧠 The AI model — via **OpenRouter**
- **What:** the "brain" that understands questions and writes answers (a Large Language
  Model). **OpenRouter** is a service that gives us access to many AI models (from OpenAI,
  Google, Meta, etc.) through **one** key and one address.
  > 🔑 **New word — LLM (Large Language Model):** an AI trained on huge amounts of text
  > that can read and write human language.
- **Why:** we need a brain to turn found documents into a clear answer. OpenRouter lets us
  switch or mix models without rewriting code, and it's cheaper/flexible.
- **Without it:** no answers — just search results you'd have to read yourself.

### 🔎 The "meaning" search — **ChromaDB** (a vector database) + **local embeddings**
- **What:** we turn every piece of text into a list of numbers that captures its **meaning**
  ("embeddings"), and store them in **ChromaDB**. Similar meaning → similar numbers.
  > 🔑 **New word — embedding:** a list of numbers that represents the meaning of a piece
  > of text. > 🔑 **New word — vector database:** a store that finds text by *meaning*
  > instead of exact keywords.
- **Why:** so "what's the refund rule?" finds the refund policy even if it never uses the
  word "rule." We compute the numbers **locally** (on your machine) because it's free and
  OpenRouter doesn't offer this.
- **Without it:** the AI would guess from memory and make things up ("hallucinate").

### 🕸️ The "connections" search — **Neo4j** (a graph database)
- **What:** stores **things** (people, teams, systems) as dots and **relationships**
  (depends-on, owns, manages) as arrows.
  > 🔑 **New word — graph database:** a store built for *connections* between things — like
  > a family tree or an org chart.
- **Why:** meaning-search is weak at chains like "A depends on B, B is owned by team C."
  The graph stores those links directly, so multi-step questions actually work.
- **Without it:** "what depends on Auth-DB and who owns it?" would get a vague answer.

### 🔗 Combining both + a **re-ranker**
- **What:** we search **both** stores, combine the results, and use a small "re-ranker"
  model to put the most relevant pieces first.
  > 🔑 **New word — re-ranker:** a picky second reviewer that reorders search results by how
  > well they actually answer *this* question.
- **Why:** first-pass search is fast but rough; the re-ranker is precise. Best of both.

### 🤖 The **agent** with **tools** — using **LangGraph**
- **What:** instead of one fixed step, the AI can **decide** to use tools: search documents,
  search the web, query a spreadsheet, or do a calculation. **LangGraph** is the small
  framework that runs this decide-act-repeat loop.
  > 🔑 **New word — agent:** an AI that can choose actions (tools) to reach an answer, not
  > just reply in one shot.
- **Why:** real questions sometimes need a lookup, a count, or a calculation — not just text.
- **Without it:** the assistant could only ever do one plain document search.

### 🛡️ **Guardrails** — safety in and out
- **What:** checks *before* answering (block hijacking attempts, hide private data) and
  *after* (make sure the answer is backed by sources, not toxic).
  > 🔑 **New word — guardrail:** an automatic safety check that stops bad input or bad output.
- **Why:** a company assistant must be safe and must not leak private data or make things up.
- **Without it:** it could be tricked, leak data, or confidently lie.

### ⚡ **FastAPI** — the front door (an API)
- **What:** a clean, documented way for other programs (like our chat website) to send a
  question and get a structured answer back.
  > 🔑 **New word — API:** a doorway that lets one program call another in a predictable way.
- **Why:** we want the "brains" (the pipeline) separate from the "face" (the UI), so any app
  could use it. FastAPI also checks inputs for us and auto-generates documentation.
- **Without it:** everything would be tangled together and hard to reuse or test.

### 💬 **Chainlit** — the chat website (the face)
- **What:** a ready-made chat interface for AI apps that shows the answer, the **steps** the
  agent took, and the **sources** — with very little code.
- **Why:** building a chat UI from scratch (React, etc.) is a lot of work and out of scope.
- **Without it:** you'd only be able to talk to the app through the command line.

### 🔭 **Langfuse** — observability (the flight recorder)
- **What:** records every request: how long each step took, how many tokens (cost) were
  used, which model, cache hit or miss.
  > 🔑 **New word — observability:** being able to see what happened inside your app so you
  > can debug and improve it.
- **Why:** you can't fix or improve what you can't see.
- **Without it:** you'd be flying blind in production.

### 🗄️ **Semantic cache** (using **fakeredis**)
- **What:** remembers past answers and reuses them when a new question **means** the same
  thing — returning in ~0.6 seconds instead of ~8.
- **Why:** speed and cost. Many people ask the same things.
- **Without it:** every repeat question would pay full time and money again.

---

## The tech stack in one table

| Layer | Tool | One-line why |
|---|---|---|
| AI brain | OpenRouter (LLM) | Many models, one key, flexible + cheap |
| Meaning search | ChromaDB + local embeddings | Find text by meaning, free, no extra API |
| Connections | Neo4j Aura (graph) | Answer multi-step "how are these linked" questions |
| Combine results | sentence-transformers re-ranker | Put the most relevant pieces first |
| Decisions | LangGraph agent + tools | Let the AI search, query, and calculate |
| Safety | Presidio + custom guardrails | Block attacks, hide PII, catch made-up answers |
| Front door | FastAPI | Clean API for the UI and other programs |
| Face | Chainlit | Instant chat UI with steps + sources |
| Monitoring | Langfuse | See timing, cost, and steps of every request |
| Speed/cost | fakeredis semantic cache | Reuse answers for same-meaning questions |

---

## ✅ You just learned
- The real-world problem: scattered company knowledge and weak search.
- The "assembly line" a question flows through.
- **What each technology is, why we need it, and what breaks without it.**

## 🧠 Check yourself
1. Why do we use a **graph** database in addition to a **vector** database?
2. In one sentence, what is an **embedding**?
3. What's the job of the **guardrails**, and why does a company assistant need them?

---

Next we install the tools and create the accounts/keys →
[01-tools-and-accounts.md](01-tools-and-accounts.md)
