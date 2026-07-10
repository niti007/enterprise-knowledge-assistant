# Chapter 01 — Install the Tools & Get Your Keys

This chapter has **no coding**. We just install the software and create the free accounts
you'll need. Do every step in order. Take your time — a clean setup saves hours later.

> 🔑 **New word — terminal:** a text window where you type commands to your computer instead
> of clicking. On Windows we'll use **PowerShell** (search "PowerShell" in the Start menu).

---

## Part A — Install the software

You need four programs. Install each, then reopen PowerShell so it "sees" them.

### 1. Python 3.12 (the programming language)
- Download: **https://www.python.org/downloads/**  (get **3.12.x**)
- ⚠️ On the first install screen, **tick the box "Add Python to PATH"**, then click Install.
  > 🔑 **New word — PATH:** a list your computer checks to find programs. Adding Python to
  > PATH lets you type `python` in any terminal.
- **Check it worked:** open a NEW PowerShell and type:
  ```powershell
  python --version
  ```
  You should see `Python 3.12.x`. (If not, restart your computer and try again.)

### 2. Visual Studio Code (the code editor)
- Download: **https://code.visualstudio.com/**
- This is where you'll read and write code. After installing, open it once.
- Recommended: inside VS Code, click the Extensions icon (left bar) and install the
  **"Python"** extension by Microsoft.

### 3. Git (to download the project and save versions)
- Download: **https://git-scm.com/downloads**
- Accept the default options during install.
  > 🔑 **New word — Git:** a tool that downloads code projects and tracks changes over time.
- **Check:** in a new PowerShell: `git --version` → shows a version number.

### 4. Node.js (only needed for one testing tool later)
- Download: **https://nodejs.org/en/download**  (get the **LTS** version)
- **Check:** `node --version` → shows a version number.

> ✅ After Part A, in a fresh PowerShell all four should work:
> `python --version`, `git --version`, `node --version`, and `code --version`.

---

## Part B — Create accounts and get your keys

Our app talks to a few online services. Each gives you a **key** — a secret password that
proves the requests are yours.

> 🔑 **New word — API key:** a secret string (like a password) that a service gives you so
> your program can use it. **Never** share it or put it in your code publicly.

You'll collect these into a text note for now; in Chapter 02 we paste them into a file.

### Key 1 — OpenRouter (the AI brain) — **required**
1. Go to **https://openrouter.ai/** and **Sign up** (Google/GitHub/email).
2. Add a little credit: click your avatar → **Credits** → add ~$5 (the app is cheap to run,
   but a paid balance is needed for the AI to answer).
3. Go to **https://openrouter.ai/keys** → **Create Key** → copy it.
   It looks like `sk-or-v1-xxxxxxxx...`
4. Save it as `OPENAI_API_KEY`.
   > Note: it's named "OPENAI_API_KEY" because OpenRouter copies OpenAI's format — our code
   > talks to it the same way. The web address (base URL) is `https://openrouter.ai/api/v1`.

### Key 2 — Neo4j Aura (the graph database) — **required**
1. Go to **https://console.neo4j.io/** and sign up.
2. Click **Create instance** → choose **AuraDB Free**.
3. ⚠️ When it's created, it shows the **password ONCE**. Click **Download** (or copy it now).
   You cannot see it again later — only reset it.
4. From the instance card, copy these three values:
   - `NEO4J_URI` — looks like `neo4j+s://xxxxxxxx.databases.neo4j.io`
   - `NEO4J_USER` — usually `neo4j`
   - `NEO4J_PASSWORD` — the one you just downloaded
   > 🔑 **New word — database instance:** your own private copy of a database running in the
   > cloud.

### Key 3 — Langfuse (monitoring) — **recommended (free)**
1. Go to **https://cloud.langfuse.com/** and sign up.
2. Create an **Organization**, then a **Project** (name it `knowledge-assistant`).
3. Go to **Settings → API Keys → Create new API keys**.
4. Copy both:
   - `LANGFUSE_PUBLIC_KEY` — starts with `pk-lf-...`
   - `LANGFUSE_SECRET_KEY` — starts with `sk-lf-...`
   - `LANGFUSE_HOST` = `https://cloud.langfuse.com`
   > If you skip this, the app still works — it just won't record traces.

### Key 4 — Tavily (web search tool) — **optional**
1. Go to **https://tavily.com/** and sign up → copy the key from the dashboard.
2. Save it as `TAVILY_API_KEY`.
   > If you skip this, the assistant's "web search" tool simply turns itself off. Everything
   > else works.

---

## Your key checklist

By the end of this chapter you should have written down:

```
OPENAI_API_KEY       = sk-or-v1-...              (OpenRouter)   [required]
OPENAI_BASE_URL      = https://openrouter.ai/api/v1            [fixed value]
NEO4J_URI            = neo4j+s://....databases.neo4j.io        [required]
NEO4J_USER           = neo4j                                    [required]
NEO4J_PASSWORD       = ....                                     [required]
LANGFUSE_PUBLIC_KEY  = pk-lf-...                                [recommended]
LANGFUSE_SECRET_KEY  = sk-lf-...                                [recommended]
LANGFUSE_HOST        = https://cloud.langfuse.com              [fixed value]
TAVILY_API_KEY       = ....                                     [optional]
```

> 🔒 **Keep these private.** Treat them like passwords. We'll store them in a special file
> (`.env`) that is never uploaded to the internet.

---

## ✅ You just did
- Installed Python, VS Code, Git, and Node.js.
- Created free accounts and collected the keys the app needs.

## ▶️ Run this now
In a fresh PowerShell, confirm the tools are installed:
```powershell
python --version
git --version
node --version
```

## 🧠 Check yourself
1. What is an **API key**, and why must you keep it secret?
2. Which single key is absolutely **required** for the AI to answer at all?
3. Why did we tick "Add Python to PATH" during install?

---

Next: create the project, a virtual environment, and paste your keys →
[02-project-setup.md](02-project-setup.md)
