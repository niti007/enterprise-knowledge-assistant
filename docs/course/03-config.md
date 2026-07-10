# Chapter 3 — `app/config.py`: The Settings Control Panel

## Why this / what's the need

Imagine your app needs a bunch of secret keys, passwords, and dials — an API key, a
database password, how many search results to return, which AI model to use, and so on.
You could scatter these values across dozens of files with `os.environ["SOME_KEY"]`
sprinkled everywhere. That's a mess: hard to see what settings exist, easy to typo a
name, and impossible to tell "did I forget to set something important?" until the app
crashes deep inside some unrelated function.

`app/config.py` solves this the way a car's dashboard solves "where are all my gauges?"
— one place, one panel, everything labeled, and a warning light if something critical
is missing (like a low-fuel light that stops you before you're stranded). Every other
file in this project asks *this* file for settings, instead of reading environment
variables directly.

> 🔑 **New word — environment variable:** a named value stored outside your code
> (often in a `.env` file) that your program can read at startup — used for secrets and
> settings that change between machines (your laptop vs. a real server) without editing code.

## The imports and class setup

```python
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
```

- The top block (`from __future__ import annotations`, `os`, `sys`, `lru_cache`, `Path`,
  `Optional`) are just standard Python setup lines — nothing project-specific to explain.
- `class Settings(BaseSettings)` — defines one class that will hold *every* setting the
  app needs. It inherits from `BaseSettings`, a class from the **pydantic-settings**
  library whose whole job is "read values from `.env` / the environment and validate them."
- `env_file=".env"` — tells pydantic-settings to look for a file literally named `.env`
  in the project folder and read key=value pairs from it.
- `case_sensitive=False` — so `OPENAI_API_KEY` and `openai_api_key` are treated as the
  same setting (Python variable names here are lowercase, but env files are usually
  written in UPPERCASE).
- `extra="ignore"` — if the `.env` file has extra keys this class doesn't define, don't
  crash — just ignore them. Keeps the app tolerant of leftover or future settings.

> 🔑 **New word — class:** a blueprint for creating an object that bundles related data
> and behavior together — here, the blueprint for "all app settings."

## The settings themselves

```python
    openai_api_key: str = Field(..., description="OpenAI API key — required")
    openai_base_url: Optional[str] = Field(
        None, description="Override base URL for the OpenAI-compatible client (e.g. OpenRouter)."
    )

    embedding_provider: str = Field("openai", description="'local' (ChromaDB ONNX MiniLM) or 'openai'")
    ...
    llm_default_model: str = Field("gpt-4o-mini")
    llm_advanced_model: str = Field("gpt-4o")
    chroma_persist_dir: str = Field("./data/chroma_db")
    chunk_size: int = Field(500)
    chunk_overlap: int = Field(50)
    retrieval_top_k: int = Field(5)
```

- `openai_api_key: str = Field(...)` — the `...` (called "Ellipsis") means "this value
  is **required** — there is no default, the app must be told this or it should refuse
  to start." This is the app's LLM key. In this project it's actually an **OpenRouter**
  key (OpenRouter speaks the same "language" as OpenAI's API, so the same client code
  works for both — you just point `openai_base_url` at OpenRouter instead of OpenAI).
- `openai_base_url: Optional[str] = Field(None, ...)` — optional; if left unset the code
  defaults to talking to real OpenAI. Setting it to OpenRouter's URL is how this project
  redirects all chat calls to OpenRouter instead.
- `embedding_provider: str = Field("openai", ...)` — decides how text gets turned into
  numbers for search (more on this in Chapter 5). The comment says `"local"` uses
  ChromaDB's built-in model and needs no key; anything else assumes real OpenAI-style
  embeddings. In practice this project runs it as `"local"` because OpenRouter has no
  embeddings endpoint — see Chapter 5 for why.
- Every other `Field(...)` line (Langfuse, Neo4j, Redis, Tavily, Cohere, model names,
  chunk sizes, etc.) works the same way: a name, a type (`str`, `int`, `bool`, `float`),
  and a default value in parentheses. If you never set them in `.env`, the app quietly
  uses those sensible defaults — e.g. `chunk_size: int = Field(500)` means "chunks of
  about 500 tokens unless you say otherwise" (used in Chapter 5).

> 🔑 **New word — default value:** the value a setting takes automatically if you don't
> specify your own — like a thermostat's factory temperature before you adjust it.

## The safety check (validator)

```python
    @field_validator("openai_api_key")
    @classmethod
    def openai_key_must_be_set(cls, v: str) -> str:
        if not v or v.startswith("sk-..."):
            raise ValueError(
                "\n\n[CONFIG ERROR] OPENAI_API_KEY is not set.\n"
                "  1. Copy .env.example → .env\n"
                "  2. Set OPENAI_API_KEY=sk-<your key>\n"
                "  Get a key at https://platform.openai.com/api-keys\n"
            )
        return v
```

- `@field_validator("openai_api_key")` — this decorator says "run the function below
  automatically whenever `openai_api_key` is loaded," so the check happens instantly at
  startup, not later when some deep function tries to use a missing key.
- `if not v or v.startswith("sk-...")` — catches two bad cases: the key is empty, or
  it's still the obviously-fake placeholder text from an example file.
- `raise ValueError(...)` — stops the app immediately with a big, clear, human-readable
  error message telling you exactly what to do to fix it. This is the "fails loudly"
  behavior mentioned in the file's own docstring — much friendlier than a cryptic crash
  three files later.

> 🔑 **New word — validator:** a function that checks a value is sensible/safe before
> the rest of the program is allowed to use it.

## Two convenience properties

```python
    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def chroma_persist_path(self) -> Path:
        p = Path(self.chroma_persist_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p
```

- `langfuse_enabled` — a computed yes/no answer: "do we have both Langfuse keys?" Other
  code can just check `settings.langfuse_enabled` instead of re-checking two fields
  itself every time.
- `chroma_persist_path` — turns the plain text folder path (`chroma_persist_dir`) into a
  real filesystem `Path`, and creates the folder if it doesn't exist yet
  (`mkdir(parents=True, exist_ok=True)`) so nothing downstream has to remember to do that.

## The cached singleton

```python
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton. Import and call this everywhere."""
    return Settings()
```

- `@lru_cache(maxsize=1)` — makes this function remember its result. The very first time
  `get_settings()` is called, it builds a `Settings()` object (reading `.env`, running
  the validator, etc.). Every call after that returns the *same* already-built object
  instantly, instead of re-reading files and re-validating every time.
- This pattern is called a **singleton** — "there is exactly one of these in the whole
  app, and everyone shares it." Every other file (embeddings.py, chunker.py,
  vector_search.py, and more) calls `get_settings()` rather than building its own copy,
  so the whole app always agrees on one set of settings.

> 🔑 **New word — singleton:** a design pattern where only one shared instance of
> something is ever created and reused everywhere it's needed.

> 🔑 **New word — cache:** a place that stores a result so it can be reused instantly
> next time, instead of redoing the work.

## ✅ You just learned

- Why centralizing settings in one file beats scattering `os.environ[...]` everywhere.
- How `pydantic-settings` reads a `.env` file into typed, validated Python fields.
- Why this project uses OpenRouter (`openai_base_url`) for chat but a local model for
  embeddings (`embedding_provider`).
- How a `field_validator` makes the app "fail loudly" with a helpful message instead of
  crashing mysteriously later.
- What a cached singleton (`get_settings()`) is and why every file in the app shares one.

## ▶️ Run this now

There's nothing to "run" in `config.py` itself — it has no `if __name__ == "__main__":`
block. Instead, verify your settings load correctly by importing and printing them:

```powershell
.venv\Scripts\python.exe -c "from app.config import get_settings; s = get_settings(); print(s.llm_default_model, s.chroma_persist_dir, s.embedding_provider)"
```

If your `.env` file is missing or `OPENAI_API_KEY` isn't set, you should see the
`[CONFIG ERROR]` message from the validator instead of a normal Python traceback — that's
the safety check working as intended.

## 🧠 Check yourself

1. Why does `openai_api_key` have no default value while `chunk_size` does?
2. What would happen if two different files each called `Settings()` directly instead
   of using `get_settings()`? Why does `@lru_cache` avoid that problem?
3. Which setting controls whether embeddings run locally or through an API, and where
   is it used?

Continue to the next chapter → 04-generate-data.md
