# Chapter 17 — Put It Online (Deployment)

Running on `localhost` only works on your computer. **Deploying** means putting the app on the
internet so anyone with the link can use it. We use **Hugging Face Spaces** because it's free
and has enough memory for our AI libraries.

> 🔑 **New word — deploy:** to run your app on a server on the internet instead of your own
> computer. > 🔑 **New word — Hugging Face Spaces:** a free hosting service made for AI apps.

---

## Why Hugging Face Spaces (what's the need)?
- **Free** with **16 GB of memory** — our libraries (torch, Presidio, the re-ranker) are heavy,
  and most free hosts (with 512 MB) can't even start them.
- It can run a **Docker** container and gives you a public web address.
- It stores your secret keys safely as **Space secrets** (never in the code).

> 🔑 **New word — Docker:** a way to package your app with everything it needs so it runs the
> same anywhere. The recipe lives in a file called `Dockerfile`.

**What runs where:** Neo4j (graph), OpenRouter (AI), and Langfuse (monitoring) are already in
the cloud. Only the **app + the meaning-index** need hosting. We deploy the **Chainlit UI**,
which runs the whole pipeline by itself (no separate API needed online).

---

## The pieces already in the repo
- `Dockerfile` — the recipe: install Python + libraries (CPU-only torch to stay small), copy
  the app and the sample data, pre-download the re-ranker model.
- `start.sh` — on startup: build the ChromaDB index from the bundled data, then launch Chainlit
  on port **7860** (the port Spaces expects).
- `README_HF.md` — the Space's front page, with a small settings block at the top telling
  Spaces "this is a Docker app on port 7860."

---

## Steps to deploy (high level)

1. **Create a free Hugging Face account** at https://huggingface.co/ and make an **access
   token** (Settings → Access Tokens → New token, "write" role).
   > 🔑 **New word — access token:** like an API key, but for your Hugging Face account, so a
   > program can create/update Spaces for you.
2. **Create a new Space** → choose **Docker** as the type.
3. **Upload the project files** (Dockerfile, start.sh, requirements, the `app/` folder, and
   `data/raw/`) to the Space.
4. **Add your secrets** in the Space's **Settings → Variables and secrets** — the same keys
   from your `.env` (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `NEO4J_*`, `LANGFUSE_*`, etc.).
   > These are stored privately by Hugging Face — never put them in the code.
5. **Wait for the build** (~10–20 minutes the first time). When it shows **RUNNING**, open your
   public URL: `https://<your-username>-<space-name>.hf.space`.

> This project's live example: `https://Nitishgalat-enterprise-knowledge-assistant.hf.space`

---

## Two things to expect
- **First message is slow (~1–2 min):** the same cold start as local — the server loads the AI
  helper models on the first question, then it's fast.
- **Free Spaces sleep after ~48 hours idle:** they wake up automatically on the next visit
  (one-time slow boot). That's fine for a demo or portfolio.

---

## Bonus: automatic testing (GitHub Actions)
The repo includes `.github/workflows/promptfoo.yml`. This is a **GitHub Action** — a script
GitHub runs for you (on a button click or on each change) that builds the app and runs the
Promptfoo tests automatically.
> 🔑 **New word — GitHub Actions:** free automation that runs your scripts on GitHub's servers
> (for testing, building, deploying).
To use it, add your keys as **repository secrets** in GitHub (Settings → Secrets → Actions).

---

## ✅ You just learned
- What deploying is and why we chose Hugging Face Spaces.
- The role of the `Dockerfile`, `start.sh`, and Space secrets.
- The deploy steps, the cold-start, and the free-tier sleep behavior.
- That GitHub Actions can run your tests automatically.

## ▶️ Try this now
Open the live demo (or your own Space) and ask a multi-step question:
`https://Nitishgalat-enterprise-knowledge-assistant.hf.space`

## 🧠 Check yourself
1. Why can't most free hosts run this app, but Hugging Face Spaces can?
2. Where do the secret keys go when deployed — and where do they **not** go?
3. Why is the first online request slow?

---

Next: notes for teaching this project to a class →
[18-teacher-notes.md](18-teacher-notes.md)
