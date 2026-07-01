"""
agent/graph.py
================
LangGraph state machine: plan -> tool-select/execute -> synthesize a cited
answer. Built on LangChain's ChatOpenAI pointed at OpenRouter (base_url from
settings) so it reuses the same LLM access as the rest of the app.

The graph is a standard ReAct-style tool-calling loop:
    agent (LLM decides: call a tool, or answer) -> tools -> agent -> ... -> END

Usage:
    from app.agent.graph import run_agent
    result = run_agent("If Payment-Service goes down, what does it depend on
                         and who do I contact?")
    # -> {"answer": str, "tool_calls": [...], "messages": [...]}
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any, TypedDict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import structlog

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """\
You are an expert Enterprise Knowledge Assistant for ACME Corp.

You have access to tools:
- retrieve: search the internal knowledge base + knowledge graph (policies, SOPs,
  manuals, incident reports, entity relationships like DEPENDS_ON/OWNS/MANAGES/RESOLVED_BY).
  ALWAYS try this first for questions about internal systems, teams, people, policies, incidents.
- web_search: public web search, only if internal retrieval is insufficient.
- sql_query: read-only SQL over structured tables (users, products, transactions, doc_metadata).
- python_exec: sandboxed Python for calculations.

Rules:
- Ground your answer in tool results. Do not invent facts.
- For multi-hop questions (e.g. "what does X depend on and who owns it"), call `retrieve`
  and use BOTH the document text and the graph facts (e.g. "A depends on B", "Team owns A").
- Cite sources inline using [Source: <name>] notation, where <name> is the source shown
  in brackets in the tool output (e.g. "[INC-204.md]" or "[graph]").
- If you don't have enough information after using the tools, say so plainly.
- Be concise and precise.
"""


from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # add_messages reducer APPENDS new messages to history (a bare string
    # annotation would make each step REPLACE the list, dropping the
    # assistant tool_calls turn and breaking the tool round-trip).
    messages: Annotated[list, add_messages]


def _get_llm(model: str | None = None):
    from langchain_openai import ChatOpenAI

    from app.config import get_settings

    s = get_settings()
    return ChatOpenAI(
        model=model or s.llm_default_model,
        api_key=s.openai_api_key,
        base_url=s.openai_base_url,
        temperature=0.1,
        # OpenRouter's Azure-backed upstream for openai/gpt-4.1* sometimes
        # rejects the second turn of a tool-calling round-trip with
        # "No tool call found for function call output with call_id ..." —
        # an Azure Responses-API-style validation quirk that the Chat
        # Completions tool-message format trips over. Excluding Azure from
        # the candidate providers routes the request to a provider that
        # accepts standard OpenAI-format tool messages.
        extra_body={"provider": {"ignore": ["Azure"]}},
    )


def build_agent_graph(model: str | None = None):
    """Construct the compiled LangGraph state machine."""
    from langchain_core.messages import SystemMessage
    from langgraph.graph import END, StateGraph
    from langgraph.prebuilt import ToolNode

    from app.agent.tools import get_tools

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


_compiled_graphs: dict[str, Any] = {}


def get_compiled_graph(model: str | None = None):
    key = model or "default"
    if key not in _compiled_graphs:
        _compiled_graphs[key] = build_agent_graph(model)
    return _compiled_graphs[key]


def run_agent(
    message: str,
    model: str | None = None,
    max_steps: int = 6,
) -> dict[str, Any]:
    """
    Run the LangGraph agent end-to-end on a single user message.

    Returns
    -------
    {
        "answer": str,
        "tool_calls": [{"tool": str, "input": Any, "output": str}],
        "messages": [...]   # raw LangChain message objects, for debugging
    }
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    compiled = get_compiled_graph(model)
    initial_state = {"messages": [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=message)]}

    final_state = compiled.invoke(initial_state, config={"recursion_limit": max_steps * 2 + 2})
    messages = final_state["messages"]

    # Reconstruct tool_calls trace: pair AIMessage.tool_calls with following ToolMessages
    tool_calls: list[dict[str, Any]] = []
    pending: dict[str, dict[str, Any]] = {}
    for m in messages:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                pending[tc["id"]] = {"tool": tc["name"], "input": tc["args"]}
        elif isinstance(m, ToolMessage):
            call = pending.pop(m.tool_call_id, {"tool": m.name, "input": None})
            call["output"] = m.content if isinstance(m.content, str) else str(m.content)
            tool_calls.append(call)

    # Final answer = last AIMessage with content (no further tool calls)
    answer = ""
    for m in reversed(messages):
        if isinstance(m, AIMessage) and m.content:
            answer = m.content if isinstance(m.content, str) else str(m.content)
            break

    return {"answer": answer, "tool_calls": tool_calls, "messages": messages}
