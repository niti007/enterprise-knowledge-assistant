# Chapter 4 — Making Up a Company: `generate_fake_data.py` and `loader.py`

## Why this / what's the need

Before you can build a "knowledge assistant" that answers questions about a company,
you need... a company. A real one would mean handling messy, private, inconsistent
documents — bad for a learning project. So this app invents a small, fake company
called **ACME Corp**, complete with employees, systems, policies, and past outages, and
writes it all to disk as realistic files (PDFs, Markdown reports, CSVs).

Think of it like a movie set: the buildings look real from the front, the "employees"
have consistent names and job titles across every scene, and the "history" (past
incidents) is written so that it all connects — because a good test of a knowledge
assistant is asking multi-step questions like *"if Payment-Service goes down, who do I
call and what's the fix?"* — and that only works if the fake data is internally
consistent. `generate_fake_data.py` builds that fake world; `loader.py` is the first
step of *reading* it back in.

> 🔑 **New word — corpus:** a collected body of documents used for search or training —
> here, the full set of ACME Corp's fake policies, reports, and manuals.

## The entity universe: keeping the story consistent

```python
from faker import Faker

fake = Faker()
random.seed(42)
Faker.seed(42)

TEAMS = ["Billing", "Infrastructure", "Security", "Data Engineering", "Customer Success", "Product"]

PEOPLE = {
    "Billing": "Priya Sharma",
    "Infrastructure": "Marcus Lee",
    ...
}
PERSON_TEAM = {v: k for k, v in PEOPLE.items()}
```

- `from faker import Faker` — **Faker** is a library that generates realistic-looking
  fake data (names, emails, dates) on demand, without an LLM. Trivial imports (`csv`,
  `json`, `os`, `random`, `sys`, `textwrap`, `date`/`timedelta`, `Path`, `Any`) are just
  standard setup and don't need individual explanations.
- `random.seed(42)` / `Faker.seed(42)` — "seeding" the random number generator means
  every time you run this script, you get the *exact same* "random" names and dates.
  Without this, re-running the generator would create a different fake company each
  time, which would break reproducibility.
- `TEAMS = [...]` and `PEOPLE = {...}` — these are hand-picked, fixed dictionaries (not
  random) that define one team lead per team. Because every document generator below
  pulls from this *same* dictionary, "Priya Sharma" always leads "Billing" in every file
  — that consistency is what lets the assistant later connect facts across documents.
- `PERSON_TEAM = {v: k for k, v in PEOPLE.items()}` — flips the dictionary around
  (person → team instead of team → person) so the code can look someone up either way.
- `SYSTEMS`, `SOPS`, `POLICIES`, `INCIDENTS` — more fixed "facts about the world": eight
  software systems, seven Standard Operating Procedures, four policies, and five
  specific past incidents (each with a system, cause, responsible team, and the SOP used
  to fix it). These are the building blocks every generated document will reference.

> 🔑 **New word — seed (random seed):** a starting number for a random number generator
> that makes its "randomness" repeatable — same seed, same sequence, every run.

## Writing one document: the incident report generator

```python
def gen_incident_md(inc: dict[str, Any]) -> None:
    content = f"""# Incident Report — {inc["id"]}
...
On {inc["date"]}, a {inc["severity"]} incident was raised against **{inc["system"]}** due to
{inc["cause"]}. The outage caused cascading failures in **{inc["linked_system"]}** which depends
on {inc["system"]} for critical operations.
...
"""
    _write_text(RAW_DIR / f"{inc['id']}.md", content)
```

- `def gen_incident_md(inc: dict) -> None:` — takes one incident dictionary (like
  `INC-204`, with fields `system`, `cause`, `team`, `lead`, `sop`, `linked_system`) and
  turns it into a full Markdown report.
- The f-string body — builds the whole document as one big formatted string, filling in
  the entity names (`{inc["system"]}`, `{inc["lead"]}`, etc.) so the report reads like a
  real incident write-up, complete with Summary, Impact, Root Cause, Resolution, and
  Action Items sections and even a fake monitoring-dashboard URL.
- `_write_text(RAW_DIR / f"{inc['id']}.md", content)` — saves the finished text to
  `data/raw/INC-204.md` (for example) using the shared helper `_write_text`, which also
  prints a confirmation line so you can watch progress as the script runs.
- The same pattern repeats for `gen_sop_md` (writes an SOP as numbered steps),
  `gen_manual_md` (writes a technical manual with a fake architecture diagram and config
  table for one system), and `gen_faq_md` (writes one big FAQ.md with Q&A pairs) — all
  pulling from the same shared `PEOPLE`/`SYSTEMS`/`SOPS` dictionaries so names stay
  consistent everywhere.

## Writing a PDF instead of Markdown

```python
def _write_pdf(path: Path, title: str, body_paragraphs: list[str]) -> None:
    try:
        from reportlab.lib.pagesizes import A4
        ...
    except ImportError:
        print("[WARN] reportlab not installed — writing PDF as text placeholder")
        _write_text(path.with_suffix(".md"), f"# {title}\n\n" + "\n\n".join(body_paragraphs))
        return

    doc = SimpleDocTemplate(str(path), pagesize=A4, ...)
    ...
    doc.build(story)
```

- `try: from reportlab... except ImportError:` — if the optional **reportlab** PDF
  library isn't installed, the script doesn't crash; it falls back to writing a plain
  `.md` file with the same content, so the course still works even without that
  dependency installed.
- `SimpleDocTemplate(...)`, `Paragraph`, `Spacer` — reportlab's building blocks for
  laying out a real PDF page: a document container, blocks of text, and blank spacing
  between them.
- `doc.build(story)` — actually renders the PDF file to disk. This is how the four
  company policies (`POL-001.pdf` … `POL-004.pdf`) get created as genuine, readable PDF
  files — useful later to prove the assistant can also read PDFs, not just Markdown.

## The CSV generators and the "master map"

```python
def gen_doc_metadata_csv(doc_paths: list[str]) -> None:
    ...
    for dp in doc_paths:
        fname = Path(dp).name
        if fname.startswith("INC-"):
            inc = next((i for i in INCIDENTS if i["id"] == fname.replace(".md", "")), None)
            if inc:
                writer.writerow({
                    "filename": fname, "doc_type": "incident_report", "dept": inc["team"],
                    "system_refs": f"{inc['system']},{inc['linked_system']}", "sop_refs": inc["sop"],
                })
```

- `gen_users_csv`, `gen_products_csv`, `gen_transactions_csv` — write ordinary CSV files
  (people, products, sales records) using Python's built-in `csv.DictWriter`, mixing
  fixed team leads with randomly-generated extra rows (via Faker) for realistic volume
  (46 users, 200 transactions).
- `gen_doc_metadata_csv(doc_paths)` — the important one. It looks at every document this
  script just generated and writes one row per file recording which systems (`system_refs`)
  and which SOPs (`sop_refs`) that document mentions. This CSV is the "master map" —
  see `data/raw/raw_data_explanation.md` for the full picture of how it ties everything
  together.
- The `if fname.startswith("INC-")` / `"SOP-"` / `"POL-"` / `"manual_"` branches —
  pattern-match the filename prefix to decide what kind of metadata row to write for
  each file type.

## `main()`: the assembly line

```python
def main() -> None:
    print(f"\nGenerating fake enterprise corpus into {RAW_DIR}\n")
    generated: list[str] = []

    gen_policy_pdf("POL-001", "Acceptable Use Policy", "All", [...])
    generated.append(str(RAW_DIR / "POL-001.pdf"))
    ...
    gen_doc_metadata_csv(generated)
```

- `main()` calls every generator function in order — policies, then incidents, then
  SOPs, then manuals, then the FAQ, then the three data CSVs — appending each written
  file's path to the `generated` list as it goes.
- `gen_doc_metadata_csv(generated)` is called **last**, deliberately, because it needs
  the full list of every other file that was written in order to build the "master map."
- At the end, a `manifest.json` file is written listing every generated filename — a
  simple record of "what's in `data/raw/` right now."

## A quick note on `loader.py`

`app/ingestion/loader.py` is the file that reads this generated data *back* into Python,
ready for the next step (chunking, in Chapter 5). Its two key jobs:

- `load_document(path, meta_override=None)` — reads one file (PDF via PyMuPDF/`fitz`,
  Markdown/text directly, CSV converted to a readable text block), cleans up extra
  whitespace with `_clean_text`, guesses a `doc_type` from the filename prefix (e.g.
  `INC-` → `"incident_report"`), and returns a `{"text": ..., "metadata": {...}}` dict.
- `load_all(raw_dir=None)` — loops over every `.pdf`, `.md`, `.txt`, `.csv` file in
  `data/raw/`, enriches each one's metadata using `doc_metadata.csv` (the master map from
  above) if available, and returns the full list of loaded documents — skipping
  `manifest.json` and `doc_metadata.csv` themselves since those are metadata, not content.

For a complete plain-English breakdown of what every generated file actually contains
and how the entities connect (people, teams, systems, SOPs), read
`data/raw/raw_data_explanation.md` — it walks through real excerpts of each file type.

## ✅ You just learned

- Why this project invents a fake, internally-consistent company instead of using real
  documents.
- How `random.seed()` / `Faker.seed()` makes "random" fake data reproducible.
- How one Python dictionary (`PEOPLE`, `SYSTEMS`, etc.) keeps names consistent across
  every generated document, which is what makes multi-hop questions answerable later.
- How the script gracefully falls back from PDF to Markdown if `reportlab` isn't installed.
- What `doc_metadata.csv` is for, and how `loader.py` reads all this data back into
  Python `{text, metadata}` dicts.

## ▶️ Run this now

```powershell
.venv\Scripts\python.exe -m app.ingestion.generate_fake_data
```

This writes ~26 files into `data/raw/` (policies, incident reports, SOPs, manuals, FAQ,
and CSVs). To see them loaded back into memory as text, run:

```powershell
.venv\Scripts\python.exe -m app.ingestion.loader
```

That prints one line per document showing its source filename, detected type, and
character count.

## 🧠 Check yourself

1. Why does the script seed `random` and `Faker` with the same number (42) every time?
2. Which file acts as the "master map" connecting documents to systems and SOPs, and
   why must it be generated last?
3. What happens to a PDF-generation call if the `reportlab` library isn't installed?

Continue to the next chapter → 05-embeddings-vector.md
