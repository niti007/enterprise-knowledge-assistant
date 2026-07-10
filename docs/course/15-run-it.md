# Chapter 15 — Build It and Run It (the exact order)

You've now seen every part. This chapter is the **checklist** to build the data, start the
app, and ask your first question. Do the steps **in this order** — later steps depend on
earlier ones.

> Reminder: every new terminal needs the venv turned on first:
> ```powershell
> .venv\Scripts\Activate.ps1
> ```

---

## The build order (one-time setup)

### Step 1 — Make the sample documents
```powershell
python -m app.ingestion.generate_fake_data
```
Creates ~25 cross-linked documents + spreadsheets in `data/raw/`. Uses no API key (it's just
made-up data). *(Skip this if you cloned the repo — the files are already in `data/raw/`.)*

### Step 2 — Build the meaning index (ChromaDB)
```powershell
python -m app.ingestion.chunker
```
Splits the documents into chunks and stores them in the vector database. You should see
something like `46 vectors in 'enterprise_kb'`.

### Step 3 — Build the connections graph (Neo4j)
```powershell
python -m app.ingestion.graph_builder
```
The AI reads each document and writes the entities + relationships into your Neo4j Aura
database. You should see `Neo4j now has ~120 nodes, ~280 edges`.
> This step calls the AI, so it uses a little OpenRouter credit and takes a minute or two.

---

## Run the app

You need the app running to chat with it. You have two ways:

### Option A (simplest) — Chainlit only
The chat website runs the whole pipeline itself. Just start it:
```powershell
chainlit run app/chainlit_app.py --port 8000
```
Wait for `Your app is available at http://localhost:8000`, then open that address.

### Option B — API + UI (two terminals)
Use this if you also want the REST API available (for tests or other programs).
```powershell
# Terminal 1 — the API
uvicorn app.main:app --host 127.0.0.1 --port 8001
# Terminal 2 (activate venv again) — the UI
chainlit run app/chainlit_app.py --port 8000
```

---

## Your first questions

Open **http://localhost:8000** and try:
- "Who owns the Payment-Service?"  *(simple lookup)*
- "If Payment-Service goes down, what does it depend on and who do I contact?"  *(multi-step —
  uses the graph)*
- "Which team manages the Data Warehouse?"

> ⏳ **The first question is slow (about 1–2 minutes).** This is the **cold start** — the app
> is loading the AI helper models into memory for the first time. After that, answers take
> about 6–10 seconds, and repeated questions (cache hits) come back in under a second. This is
> normal; don't refresh the page.
> 🔑 **New word — cold start:** the one-time slowness when a program first loads everything
> it needs.

Watch the little steps appear (🧠 pipeline → 🔍 retrieve → sources) — that's the agent
working, exactly as you built it.

---

## One command to check everything

The project includes a health-check script that verifies your keys, services, index, and API:
```powershell
.venv\Scripts\python.exe validate.py
```
Green ticks across the board = everything is wired correctly.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ERR_CONNECTION_REFUSED` in the browser | The server isn't running | Start Chainlit (Option A); keep the terminal open |
| "CONFIG ERROR: OPENAI_API_KEY not set" | `.env` missing the key | Open `.env`, paste your OpenRouter key, save |
| 401 / "Incorrect API key" | Wrong or out-of-credit key | Re-copy the key from openrouter.ai/keys; add credit |
| First answer never comes | Still cold-starting | Wait up to ~2 min on the first message; don't refresh |
| Graph answers are empty | Step 3 not run, or Neo4j creds wrong | Re-run `graph_builder`; check `NEO4J_*` in `.env` |
| "running scripts is disabled" | PowerShell policy | `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` |
| `chunker` says 0 vectors | `data/raw` empty | Run Step 1 first, then Step 2 |
| Port already in use | Something else on 8000/8001 | Use a different port, e.g. `--port 8500` |

---

## ✅ You just did
- Built the two indexes (meaning + connections) in the right order.
- Started the app and asked real questions.
- Learned why the first answer is slow, and how to check everything with `validate.py`.

## ▶️ Run this now
```powershell
chainlit run app/chainlit_app.py --port 8000
```

## 🧠 Check yourself
1. Why must `chunker` run **before** you start the app?
2. Why is the very first question slow, and what is that called?
3. What does `validate.py` check?

---

Next: how we proved the app actually works (testing & evaluation) →
[16-testing-evaluation.md](16-testing-evaluation.md)
