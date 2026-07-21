"""Optional bridge to a 1c-mcp-metacode graph server (Neo4j).

Mirrors the ``llm_bridge`` pattern: the bridge is OFF by default and activates
only when ``RLM_METACODE_URL`` is set (e.g. ``http://127.0.0.1:8000/mcp``).
When active, ``server.py`` injects ``graph_*`` helpers into the sandbox so
``rlm_execute`` scripts can enrich on-the-fly RLM analysis with pre-indexed
graph context (semantic code search, metadata structure, call graph) WITHOUT
returning intermediate data to the agent context — only the final ``print()``
reaches the agent.

Design notes:
- Transport: MCP streamable-http client from the ``mcp`` package (already a
  project dependency) — no new dependencies.
- Each call opens a fresh connection. Robust (no stale session state between
  rlm_execute rounds), and connection overhead against a localhost metacode
  instance is negligible compared to graph query time.
- Async MCP client is driven by a dedicated daemon thread with a persistent
  event loop, so helpers stay synchronous and safe to call from the sandbox
  worker thread regardless of any event loop in the caller.

Environment variables:
- ``RLM_METACODE_URL``     — metacode MCP endpoint; unset → bridge disabled.
- ``RLM_METACODE_TIMEOUT`` — per-call timeout in seconds (default 60).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from concurrent.futures import TimeoutError as _FuturesTimeoutError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 60.0

# ── Dedicated event-loop thread ───────────────────────

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """Lazily start the shared daemon loop thread (one per process)."""
    global _loop
    if _loop is not None and not _loop.is_closed():
        return _loop
    with _loop_lock:
        if _loop is not None and not _loop.is_closed():
            return _loop
        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=loop.run_forever, name="graph_bridge_loop", daemon=True
        )
        thread.start()
        _loop = loop
        return loop


def _run_sync(coro, timeout: float):
    future = asyncio.run_coroutine_threadsafe(coro, _get_loop())
    try:
        return future.result(timeout=timeout)
    except (_FuturesTimeoutError, TimeoutError):  # distinct classes on Python 3.10
        future.cancel()
        raise RuntimeError(
            f"graph bridge: call timed out after {timeout:.0f}s "
            "(is the metacode server responsive? see RLM_METACODE_TIMEOUT)"
        ) from None


# ── MCP client primitives ─────────────────────────────


async def _call_tool_async(url: str, tool: str, params: dict) -> str:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, params)
            text = _extract_text(result)
            if getattr(result, "isError", False):
                raise RuntimeError(f"graph bridge: tool '{tool}' failed: {text[:2000]}")
            return text


async def _list_tools_async(url: str) -> list[dict]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            tools = []
            for t in listed.tools:
                desc = (t.description or "").strip()
                first_line = desc.splitlines()[0] if desc else ""
                tools.append({"name": t.name, "description": first_line})
            return tools


def _extract_text(result) -> str:
    """Join text content blocks of a CallToolResult into one string."""
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
        else:
            try:
                parts.append(json.dumps(block, ensure_ascii=False, default=str))
            except Exception:
                parts.append(str(block))
    return "\n".join(parts)


# ── Helper factory ────────────────────────────────────


def get_graph_config() -> tuple[str, float] | None:
    """Read bridge config from env. None → bridge disabled."""
    url = (os.environ.get("RLM_METACODE_URL") or "").strip()
    if not url:
        return None
    raw_timeout = os.environ.get("RLM_METACODE_TIMEOUT", "")
    try:
        timeout = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        logger.warning(
            "RLM_METACODE_TIMEOUT=%r is not a number; using default %.0fs",
            raw_timeout,
            DEFAULT_TIMEOUT_SECONDS,
        )
        timeout = DEFAULT_TIMEOUT_SECONDS
    if timeout <= 0:
        timeout = DEFAULT_TIMEOUT_SECONDS
    return url, timeout


def make_graph_helpers(
    url: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    *,
    call_tool_fn=None,
    list_tools_fn=None,
) -> dict:
    """Build sandbox helpers bound to a metacode MCP endpoint.

    ``call_tool_fn`` / ``list_tools_fn`` are injection points for tests:
    synchronous callables ``(tool, params) -> str`` and ``() -> list[dict]``.
    """

    if call_tool_fn is None:

        def call_tool_fn(tool: str, params: dict) -> str:
            return _run_sync(_call_tool_async(url, tool, params), timeout)

    if list_tools_fn is None:

        def list_tools_fn() -> list[dict]:
            return _run_sync(_list_tools_async(url), timeout)

    _tools_cache: dict[str, list[dict]] = {}

    def graph_tools(refresh: bool = False) -> list[dict]:
        """List tools of the connected metacode graph server.

        Returns [{'name', 'description'}]; descriptions are first lines only.
        Cached per session — pass refresh=True to re-fetch.
        """
        if refresh or "tools" not in _tools_cache:
            _tools_cache["tools"] = list_tools_fn()
        return _tools_cache["tools"]

    def graph_call(tool: str, **params) -> str:
        """Call any metacode graph tool by name; returns its text payload.

        Discover tools and their names via graph_tools(). Parameter validation
        happens server-side — on errors re-check names against graph_tools().
        """
        if not tool or not isinstance(tool, str):
            raise ValueError("graph_call: 'tool' must be a non-empty string")
        return call_tool_fn(tool, params)

    # ── Curated wrappers over the most useful graph tools ──

    def graph_search_code(query: str, limit: int = 5, **filters) -> str:
        """Semantic search by BSL routine BODY (metacode: search_bsl_code).

        `query` — natural-language description of what the code does.
        Optional filters: config_name, owner_qn, owner_qn_prefix,
        owner_categories, module_type, routine_type, export.
        Covers exactly the gap of pure RLM: недетерминированные запросы
        («где формируется уведомление пользователю»).
        """
        if not query:
            raise ValueError("graph_search_code: 'query' cannot be empty")
        return call_tool_fn("search_bsl_code", {"query": query, "limit": limit, **filters})

    def graph_search_routines(query: str, limit: int = 5, **filters) -> str:
        """Search routines by name/signature/description (metacode: search_bsl_routines)."""
        if not query:
            raise ValueError("graph_search_routines: 'query' cannot be empty")
        return call_tool_fn(
            "search_bsl_routines", {"query": query, "limit": limit, **filters}
        )

    def graph_object_structure(object_ref: str, sections: list[str] | None = None, **params) -> str:
        """Indexed structure card of a metadata object (metacode: get_metadata_object_structure).

        sections=None → compact inventory card (counts). Pass sections like
        ['attributes', 'tabular_parts', 'forms'] for detailed lists.
        """
        if not object_ref:
            raise ValueError("graph_object_structure: 'object_ref' cannot be empty")
        if sections is not None:
            params["sections"] = sections
        params["object_ref"] = object_ref
        return call_tool_fn("get_metadata_object_structure", params)

    return {
        "graph_tools": graph_tools,
        "graph_call": graph_call,
        "graph_search_code": graph_search_code,
        "graph_search_routines": graph_search_routines,
        "graph_object_structure": graph_object_structure,
    }


GRAPH_HELPER_NAMES: tuple[str, ...] = (
    "graph_tools",
    "graph_call",
    "graph_search_code",
    "graph_search_routines",
    "graph_object_structure",
)

GRAPH_HELPER_SIGNATURES: tuple[str, ...] = (
    "graph_tools(refresh=False) -> [{name, description}] — список инструментов графового сервера",
    "graph_call(tool, **params) -> str — любой инструмент metacode по имени",
    "graph_search_code(query, limit=5, **filters) -> str — семантический поиск по ТЕЛУ кода (граф)",
    "graph_search_routines(query, limit=5, **filters) -> str — поиск процедур по имени/сигнатуре/описанию (граф)",
    "graph_object_structure(object_ref, sections=None) -> str — индексированная структура объекта (граф)",
)
