# Chapter 02 — Set Up the Project

Now we get the project code onto your computer, create a clean workspace for it, install the
libraries it needs, and paste in your keys. After this chapter you'll be ready to build.

---

## Step 1 — Get the project code

Open **PowerShell** and go to where you keep projects (e.g. Documents), then download the
project with Git:

```powershell
cd $HOME\Documents
git clone https://github.com/niti007/enterprise-knowledge-assistant.git
cd enterprise-knowledge-assistant
```

> 🔑 **New word — clone:** make a copy of an online code project onto your computer.
> `cd` means "change directory" (move into a folder).

Now open the folder in VS Code:
```powershell
code .
```
(The `.` means "this folder.")

---

## Step 2 — Create a virtual environment

> 🔑 **New word — virtual environment (venv):** a private box of Python libraries **just for
> this project**. It keeps this project's libraries separate from other projects and from
> your system, so nothing conflicts. Think of it as a clean toolbox for one job.

Create it and turn it on:
```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
```

- The first line makes a folder named `.venv` containing a private copy of Python.
- The second line **activates** it. You'll see `(.venv)` appear at the start of your prompt —
  that means you're now working inside the box.

> ⚠️ If activation is blocked with a red "running scripts is disabled" error, run this once,
> then try activating again:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```
> This allows local scripts (like the activate script) to run. It's safe for development.

**You must activate the venv every time you open a new terminal for this project.** You know
it's on when you see `(.venv)` at the start of the line.

---

## Step 3 — Install the libraries

> 🔑 **New word — library / package:** ready-made code someone else wrote that we reuse
> (e.g. FastAPI, ChromaDB). > 🔑 **New word — pip:** Python's tool for installing libraries.

The project lists everything it needs in a file called `requirements.txt`. Install it all:
```powershell
pip install -r requirements.txt
```
This takes a few minutes (some AI libraries are large). What you're installing, in plain words:

| Library | What it's for |
|---|---|
| `fastapi`, `uvicorn` | The web API (front door) and the server that runs it |
| `chainlit` | The chat website (the face) |
| `chromadb` | The vector (meaning) database |
| `neo4j` | Talks to the Neo4j graph database |
| `openai` | The client we use to call OpenRouter |
| `langchain`, `langgraph` | Building the agent and its tools |
| `sentence-transformers` | The local re-ranker model |
| `presidio-analyzer`, `presidio-anonymizer`, `spacy` | Finding and hiding private data (PII) |
| `langfuse` | Recording traces (monitoring) |
| `fakeredis` | The in-memory cache backend |
| `reportlab`, `faker`, `pymupdf`, `pandas` | Making and reading the sample documents |
| `tiktoken`, `structlog`, `tenacity` | Counting tokens, logging, and retrying |

Then install one small language model that the PII detector needs:
```powershell
python -m spacy download en_core_web_sm
```
> 🔑 **New word — model (small NLP model):** here, a compact language model spaCy uses to
> spot names, emails, etc. in text.

---

## Step 4 — Create your `.env` file (paste your keys)

> 🔑 **New word — environment variable:** a setting your program reads from *outside* the
> code (from the environment), so secrets and settings aren't hard-coded. We keep ours in a
> file named `.env`.

**Why a `.env` file?** So your secret keys live in **one private place**, never inside the
code, and never uploaded to the internet. (The project's `.gitignore` already blocks `.env`
from being shared — that's why it's safe.)

The project ships an example file. Copy it to make your real one:
```powershell
Copy-Item .env.example .env
```

Now open `.env` in VS Code and fill in the keys you collected in Chapter 01. It should look
like this (use YOUR values):

```
# --- AI brain (OpenRouter) ---
OPENAI_API_KEY=sk-or-v1-your-key-here
OPENAI_BASE_URL=https://openrouter.ai/api/v1
EMBEDDING_PROVIDER=local
LLM_DEFAULT_MODEL=openai/gpt-4o-mini
LLM_ADVANCED_MODEL=openai/gpt-4o

# --- Graph database (Neo4j Aura) ---
NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-neo4j-password
NEO4J_DATABASE=neo4j

# --- Monitoring (Langfuse) — optional ---
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

# --- Web search tool — optional ---
TAVILY_API_KEY=
```

Key things to notice:
- `EMBEDDING_PROVIDER=local` — tells the app to compute embeddings on your machine (free).
- `LLM_DEFAULT_MODEL` / `LLM_ADVANCED_MODEL` — the cheap and smart models (we'll see the
  router choose between them in Chapter 10).
- Leave `TAVILY_API_KEY` blank if you skipped it — the app handles that gracefully.

> 🔒 Save the file. Double-check you did **not** accidentally paste a key into any `.py`
> file. Keys live only in `.env`.

---

## Step 5 — Confirm the setup loads

Let's make sure Python can read your settings without errors:
```powershell
.venv\Scripts\python.exe -c "from app.config import get_settings; s=get_settings(); print('OK — model:', s.llm_default_model)"
```
If you see `OK — model: openai/gpt-4o-mini`, your environment and keys are wired correctly.
If you get a "CONFIG ERROR" about `OPENAI_API_KEY`, your key isn't set in `.env` — fix it and
re-run.

---

## ✅ You just did
- Downloaded the project with Git and opened it in VS Code.
- Created and activated a **virtual environment** (a clean toolbox for this project).
- Installed all libraries and the spaCy model.
- Created your private `.env` file with your keys — never inside the code.

## ▶️ Run this now
```powershell
.venv\Scripts\python.exe -c "from app.config import get_settings; print('settings load OK')"
```

## 🧠 Check yourself
1. What does a **virtual environment** protect you from?
2. Why do we keep API keys in a `.env` file instead of in the code?
3. What does `EMBEDDING_PROVIDER=local` tell the app to do?

---

Now we start reading the code, beginning with the settings file →
[03-config.md](03-config.md)
