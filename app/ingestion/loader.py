"""
ingestion/loader.py
===================
Load raw documents from data/raw/ into a list of {text, metadata} dicts.
Supports: .pdf, .md, .txt, .csv

Each returned dict:
    {
        "text": str,           # cleaned full text
        "metadata": {
            "source": str,     # filename
            "doc_type": str,   # policy|sop|incident_report|technical_manual|faq|csv|general
            "dept": str,
            "date": str,
            "author": str,
            "file_path": str,  # absolute path
        }
    }
"""
from __future__ import annotations

import csv
import io
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

RAW_DIR = ROOT / "data" / "raw"

# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

_DOC_TYPE_MAP = {
    "POL-": "policy",
    "SOP-": "sop",
    "INC-": "incident_report",
    "manual_": "technical_manual",
    "FAQ": "faq",
}


def _infer_doc_type(name: str) -> str:
    for prefix, dtype in _DOC_TYPE_MAP.items():
        if name.startswith(prefix):
            return dtype
    return "general"


def _clean_text(text: str) -> str:
    """Remove excess whitespace while preserving paragraph breaks."""
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Per-format loaders
# ---------------------------------------------------------------------------

def _load_pdf(path: Path) -> str:
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(path))
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n\n".join(pages)
    except ImportError:
        pass

    # Fallback: reportlab/pypdf
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        return "\n\n".join(p.extract_text() or "" for p in reader.pages)
    except ImportError:
        pass

    raise RuntimeError(
        f"Cannot read PDF '{path.name}'. Install PyMuPDF: pip install pymupdf"
    )


def _load_md(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_csv(path: Path) -> str:
    """Convert CSV to a readable text block."""
    rows = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(", ".join(f"{k}: {v}" for k, v in row.items()))
    header = f"=== CSV: {path.name} ===\n"
    return header + "\n".join(rows)


def _load_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_document(path: Path, meta_override: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load a single file and return {text, metadata}."""
    suffix = path.suffix.lower()
    name = path.stem

    if suffix == ".pdf":
        raw = _load_pdf(path)
    elif suffix in (".md", ".txt"):
        raw = _load_md(path)
    elif suffix == ".csv":
        raw = _load_csv(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    text = _clean_text(raw)
    doc_type = _infer_doc_type(path.name)

    metadata: dict[str, Any] = {
        "source": path.name,
        "doc_type": doc_type,
        "dept": "General",
        "date": "",
        "author": "",
        "file_path": str(path),
    }
    if meta_override:
        metadata.update(meta_override)

    return {"text": text, "metadata": metadata}


def load_all(raw_dir: Path | None = None) -> list[dict[str, Any]]:
    """
    Load every supported file in raw_dir (default: data/raw/).
    Skips manifest.json and doc_metadata.csv (metadata-only files).
    Returns list of {text, metadata}.
    """
    directory = raw_dir or RAW_DIR
    if not directory.exists():
        raise FileNotFoundError(
            f"data/raw/ not found at {directory}. "
            "Run: python -m app.ingestion.generate_fake_data"
        )

    # Load metadata CSV for enrichment
    meta_lookup: dict[str, dict[str, Any]] = {}
    meta_csv = directory / "doc_metadata.csv"
    if meta_csv.exists():
        with meta_csv.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                meta_lookup[row["filename"]] = row

    docs: list[dict[str, Any]] = []
    SKIP = {"manifest.json", "doc_metadata.csv"}

    for ext in ("*.pdf", "*.md", "*.txt", "*.csv"):
        for path in sorted(directory.glob(ext)):
            if path.name in SKIP:
                continue
            try:
                override = meta_lookup.get(path.name)
                doc = load_document(path, meta_override=override)
                if doc["text"]:
                    docs.append(doc)
            except Exception as exc:
                print(f"[WARN] Skipping {path.name}: {exc}")

    print(f"[loader] Loaded {len(docs)} documents from {directory}")
    return docs


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    docs = load_all()
    for d in docs:
        print(f"  {d['metadata']['source']:30s}  {d['metadata']['doc_type']:20s}  "
              f"{len(d['text'])} chars")
