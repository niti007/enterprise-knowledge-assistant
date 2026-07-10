# Chapter 8 — The Agent and Its Tools (`app/agent/graph.py` and `app/agent/tools.py`)

## Why this / what's the need

So far the app can search documents (vector), search relationships (graph), and combine
+ re-rank both (hybrid). But a plain search function only ever does one search and stops.
A real assistant needs to be more like a **helpful employee with a toolbelt**: given a
question, they decide *which tool to reach for* (look something up? run a calculation?
check the database? search the web?), use it, look at what came back, and decide if they
need another tool or are ready to answer. That decision-making loop — "look at the
situation, pick a tool, use it, look again, repeat until done" — is what an **AI agent**
is.

> 🔑 **New word — agent:** an LLM wrapped in a loop that lets it choose which tool to
> use (if any), look at the tool's result, and decide what to do next — instead of just
> answering in one shot.

> 🔑 **New word — tool:** a specific function the agent is allowed to call (like
> "search the knowledge base" or "run this SQL query"), each with a description telling
> the LLM what it's for and when to use it.

> 🔑 **New word — state machine:** a system that's always in exactly one "state" at a
> time (e.g. "thinking," "waiting for a tool," "done") and moves between states based on
> what happens. It's a formal, drawn-out way of describing a loop with decision points.

> 🔑 **New word — LangGraph:** a Python library for building exactly this kind of loop
> as a small state machine — you define "nodes" (steps) and "edges" (which step runs
> next), and it handles running the loop until the agent is finished.

This project's agent is built with LangGraph in `app/agent/graph.py`, and its 4 tools
live in `app/agent/tools.py`.

## Part 1: The tools — `app/agent/tools.py`

### Tool 1 — `retrieve`: the primary tool

```python
@tool("retrieve", return_direct=False)
def retrieve_tool(query: str) -> str:
    """Search the company knowledge base (policies, SOPs, manuals, incident
    reports) AND the knowledge graph (entity relationships like DEPENDS_ON,
    OWNS, MANAGES, RESOLVED_BY) for information relevant to `query`. ..."""
    from app.retrieval.hybrid import hybrid_search

    try:
        results = hybrid_search(query)
    except Exception as exc:
        return f"[retrieve error] {exc}"

    if not results:
        return "No relevant documents or graph facts found."

    lines = []
    for r in results:
        meta = r.get("metadata", {})
        src = meta.get("source", r.get("source", "unknown"))
        lines.append(f"[{src}] {r['text']}")
    return "\n\n".join(lines)
```

- `@tool("retrieve", return_direct=False)` — this decorator (from LangChain) turns a
  normal Python function into something the LLM can call. The **docstring right under
  the function** is not just documentation for humans — the LLM reads it too, to decide
  when this tool is the right one to use.
- It calls `hybrid_search()` from Chapter 7 — this is literally the same vector + graph
  + rerank pipeline, just exposed to the agent as a callable tool.
- `[{src}] {r['text']}` — each result line is prefixed with its source in brackets
  (e.g. `[INC-204.md]` or `[graph]`), which is exactly the citation format the agent's
  system prompt later tells it to reuse when answering (`[Source: <name>]`).
- Wrapped in `try/except` so a retrieval failure returns a plain error string instead of
  crashing the whole agent turn.

### Tool 2 — `web_search`: degrades gracefully with no key

```python
@tool("web_search", return_direct=False)
def web_search_tool(query: str) -> str:
    if not settings.tavily_api_key:
        return (
            "[web_search unavailable] No TAVILY_API_KEY configured — "
            "web search is disabled. Answer using internal knowledge base results only."
        )
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        resp = client.search(query=query, max_results=5)
        ...
    except Exception as exc:
        return f"[web_search error] {exc}"
```

- If there's no Tavily API key configured, the tool doesn't crash or silently do
  nothing — it returns a clear message explaining it's unavailable, which the LLM can
  read and factor into its answer (e.g. "I can't check the web, so here's what I found
  internally").
- Otherwise it calls the Tavily search API and formats each result as
  `[url] title\nsnippet`.

### Tool 3 — `sql_query`: read-only, SELECT-only

```python
_WRITE_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "pragma", "vacuum", "reindex",
)

@tool("sql_query", return_direct=False)
def sql_query_tool(query: str) -> str:
    q_stripped = query.strip().rstrip(";")
    q_lower = q_stripped.lower()

    if not q_lower.startswith("select"):
        return "[sql_query blocked] Only SELECT statements are allowed."
    if any(kw in q_lower for kw in _WRITE_KEYWORDS):
        return "[sql_query blocked] Query contains a disallowed write/DDL keyword."
    if ";" in q_stripped:
        return "[sql_query blocked] Multiple statements are not allowed."
    ...
```

This tool runs SQL against an in-memory SQLite database (`_build_sqlite_db()` loads
every CSV in `data/raw/` into its own table — e.g. `users.csv` becomes table `users`).
Because an LLM is the one writing the SQL text, it must be kept safe:

- `if not q_lower.startswith("select")` — rejects anything that isn't a `SELECT` query
  outright. This alone blocks `INSERT`, `DROP TABLE`, etc. from ever running as the
  *first* word.
- `any(kw in q_lower for kw in _WRITE_KEYWORDS)` — a second, belt-and-suspenders check:
  even if "select" is somehow snuck in as a prefix, this scans the whole query text for
  dangerous keywords like `drop`, `delete`, `pragma` anywhere in it and blocks those too.
- `if ";" in q_stripped` — blocks stacking multiple statements in one string (e.g.
  `SELECT 1; DROP TABLE users`), a classic SQL-injection trick.
- `cur.fetchmany(200)` — even a legitimate `SELECT` is capped at 200 rows, so a huge
  table can't flood the agent's context with data.

This is the "sandboxed database" tool: the LLM gets real query power, but only for
reading, never for writing or deleting.

### Tool 4 — `python_exec`: sandboxed calculator

```python
_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len",
    "list", "max", "min", "pow", "range", "round", "set", "sorted", "str",
    "sum", "tuple", "zip", "print",
)
_BLOCKED_TOKENS = (
    "import", "open(", "exec(", "eval(", "__", "os.", "sys.", "subprocess",
    "socket", "requests", "input(", "compile(", "globals(", "locals(",
)

@tool("python_exec", return_direct=False)
def python_exec_tool(code: str) -> str:
    lowered = code.lower()
    if any(tok in lowered for tok in _BLOCKED_TOKENS):
        return "[python_exec blocked] Code contains a disallowed token (import/file/network/os access)."
    if len(code) > 2000:
        return "[python_exec blocked] Code too long."

    safe_globals: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            exec(code, safe_globals, {})
        output = buf.getvalue().strip()
        return output if output else "[python_exec] Code ran with no printed output."
    except Exception as exc:
        return f"[python_exec error] {type(exc).__name__}: {exc}"
```

This lets the agent run small Python snippets for math the LLM itself is unreliable at
(e.g. precise arithmetic on many numbers). It's sandboxed several ways at once:

- `_BLOCKED_TOKENS` — a simple text scan that refuses to run code containing `import`,
  `open(`, `os.`, `subprocess`, double-underscore (`__`, often used to reach into
  Python internals), and similar dangerous substrings. No imports means no filesystem,
  network, or OS access is even reachable.
- `_SAFE_BUILTINS` — instead of giving the executed code Python's full builtin
  function set, `safe_globals = {"__builtins__": _SAFE_BUILTINS}` hands it a small
  hand-picked allowlist (`len`, `sum`, `round`, `print`, etc.) — so even if a blocked
  token check were somehow bypassed, dangerous builtins like `open` or `eval` simply
  aren't present to call.
- `redirect_stdout(buf)` — captures whatever the snippet `print()`s into a buffer, which
  becomes the tool's return value; nothing about return values, only printed output.
- `len(code) > 2000` — caps the snippet's length, guarding against pathologically large
  code blobs.

## Part 2: The agent loop — `app/agent/graph.py`

### The system prompt: telling the LLM about its toolbelt

```python
_SYSTEM_PROMPT = """\
You are an expert Enterprise Knowledge Assistant for ACME Corp.

You have access to tools:
- retrieve: search the internal knowledge base + knowledge graph ...
  ALWAYS try this first for questions about internal systems, teams, people, policies, incidents.
- web_search: public web search, only if internal retrieval is insufficient.
- sql_query: read-only SQL over structured tables (users, products, transactions, doc_metadata).
- python_exec: sandboxed Python for calculations.

Rules:
- Ground your answer in tool results. Do not invent facts.
- For multi-hop questions ... call `retrieve` and use BOTH the document text and the graph facts ...
- Cite sources inline using [Source: <name>] notation ...
"""
```

This tells the LLM, in plain language, what each tool is for and in what order to
prefer them (`retrieve` first, `web_search` only as a fallback), and insists it must
ground answers in tool output and cite sources — this is what keeps the agent from just
making things up.

### The state: one shared list of messages

```python
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    # add_messages reducer APPENDS new messages to history (a bare string
    # annotation would make each step REPLACE the list, dropping the
    # assistant tool_calls turn and breaking the tool round-trip).
    messages: Annotated[list, add_messages]
```

- `AgentState` is the one shared "memory" the state machine carries between steps — in
  this case, just a running list of chat messages (system prompt, user question, the
  LLM's replies, tool outputs, and so on).
- The `Annotated[list, add_messages]` part is subtle but important: `add_messages` is a
  **reducer** — a rule for how new data merges into existing state each time a node
  finishes. Without it, each step would simply *replace* `messages` with whatever the
  node returned, silently deleting all the earlier turns. With `add_messages`, each new
  message returned by a node gets *appended* onto the existing list instead. This
  matters a lot here specifically: when the LLM asks to call a tool, the round-trip
  needs the assistant's "I want to call this tool" message, THEN the tool's result
  message, both preserved in order — losing either one would break the tool call/response
  pairing and confuse the LLM (or the API) on the next turn.

### The two nodes and the loop between them

```python
def build_agent_graph(model: str | None = None):
    tools = get_tools()
    llm = _get_llm(model).bind_tools(tools)

    def agent_node(state: AgentState) -> dict[str, Any]:
        messages = state["messages"]
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=_SYSTEM_PROMPT)] + list(messages)
        response = llm.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return END

    tool_node = ToolNode(tools)

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile()
```

- `llm.bind_tools(tools)` — tells the LLM "here are the 4 functions you're allowed to
  call, with their names/descriptions/parameters" (LangChain translates the 4
  `@tool`-decorated functions into the format the LLM API expects).
- `agent_node` — the "thinking" step: it takes the current message history, makes sure a
  system prompt is present, and asks the LLM what to do next. The LLM's reply (`response`)
  is either a normal answer, or a request to call one or more tools (`tool_calls`).
- `should_continue` — the decision point of the state machine: if the LLM's last message
  contains `tool_calls`, go run the `"tools"` node; otherwise the loop is done (`END`).
- `tool_node = ToolNode(tools)` — a ready-made LangGraph node that actually executes
  whichever tool(s) the LLM asked for, and turns the results into `ToolMessage`s.
- The graph wiring: `agent -> (tools or END) -> tools -> agent -> ...` — this is the
  literal loop diagram from the file's own docstring: `agent (LLM decides: call a tool,
  or answer) -> tools -> agent -> ... -> END`. Each pass through `agent` is one
  "think" step; each pass through `tools` is one "act" step. This think-act-think-act
  pattern is exactly what's meant by a **ReAct-style** agent loop (the file's docstring
  even calls it that).

### Running it end-to-end: `run_agent()`

```python
def run_agent(message: str, model: str | None = None, max_steps: int = 6) -> dict[str, Any]:
    compiled = get_compiled_graph(model)
    initial_state = {"messages": [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=message)]}
    final_state = compiled.invoke(initial_state, config={"recursion_limit": max_steps * 2 + 2})
    messages = final_state["messages"]
    ...
    return {"answer": answer, "tool_calls": tool_calls, "messages": messages}
```

- `initial_state` seeds the loop with the system prompt plus the user's question.
- `recursion_limit=max_steps * 2 + 2` — LangGraph will forcibly stop the loop after this
  many node executions, as a safety net against the agent looping forever (e.g. if it
  kept calling tools without ever producing a final answer).
- After the loop finishes, the function walks back through `messages` to reconstruct a
  clean `tool_calls` trace (pairing each tool call with its result) and picks out the
  final answer (the last message that has plain text content, not another tool call) —
  giving the caller both the answer and a readable audit trail of what the agent did to
  get there.

## ✅ You just learned
- What an **AI agent** is: an LLM in a loop that can choose tools, observe their
  results, and decide what to do next instead of answering in one shot.
- What **LangGraph** is: a small library for wiring that loop up as an explicit
  **state machine** (nodes = steps, edges = "what runs next").
- The agent's 4 **tools** — `retrieve` (hybrid search, tried first), `web_search`
  (Tavily, degrades cleanly with no key), `sql_query` (SELECT-only against an in-memory
  SQLite built from the CSVs), and `python_exec` (sandboxed calculator with a blocked-
  token list and a safe-builtins allowlist) — and how each is kept safe.
- Why the `add_messages` reducer on `AgentState.messages` matters: it appends rather
  than replaces, which is what keeps the tool-call/tool-result round-trip intact across
  loop iterations.

## ▶️ Run this now
```
.venv\Scripts\python.exe -c "from app.agent.graph import run_agent; r = run_agent('If Payment-Service goes down, what does it depend on and who do I contact?'); print(r['answer'])"
```

## 🧠 Check yourself
1. What would go wrong with the tool-calling round-trip if `AgentState.messages` were
   annotated as a plain `list` (no `add_messages` reducer)?
2. Name two independent layers of protection that stop `sql_query` from ever running a
   `DROP TABLE` statement.
3. In `build_agent_graph`, what determines whether the loop goes to the `"tools"` node
   or to `END` after the `"agent"` node runs?

Continue to the next chapter → [09-guardrails.md](09-guardrails.md)
