"""Tests for the optional 1c-mcp-metacode graph bridge (graph_bridge.py).

The MCP client is mocked via the call_tool_fn / list_tools_fn injection
points of make_graph_helpers — no network, no metacode server required.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from rlm_tools_bsl.graph_bridge import (
    DEFAULT_TIMEOUT_SECONDS,
    GRAPH_HELPER_NAMES,
    GRAPH_HELPER_SIGNATURES,
    _extract_text,
    get_graph_config,
    make_graph_helpers,
)


URL = "http://127.0.0.1:8000/mcp"


def _helpers(call_tool_fn=None, list_tools_fn=None):
    return make_graph_helpers(
        URL,
        call_tool_fn=call_tool_fn or MagicMock(return_value="ok"),
        list_tools_fn=list_tools_fn or MagicMock(return_value=[]),
    )


# ── get_graph_config ──────────────────────────────────


def test_config_disabled_without_url():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("RLM_METACODE_URL", None)
        assert get_graph_config() is None


def test_config_enabled_with_url():
    with patch.dict(os.environ, {"RLM_METACODE_URL": URL}):
        os.environ.pop("RLM_METACODE_TIMEOUT", None)
        assert get_graph_config() == (URL, DEFAULT_TIMEOUT_SECONDS)


def test_config_custom_timeout():
    with patch.dict(os.environ, {"RLM_METACODE_URL": URL, "RLM_METACODE_TIMEOUT": "15"}):
        assert get_graph_config() == (URL, 15.0)


def test_config_bad_timeout_falls_back_to_default():
    with patch.dict(os.environ, {"RLM_METACODE_URL": URL, "RLM_METACODE_TIMEOUT": "abc"}):
        assert get_graph_config() == (URL, DEFAULT_TIMEOUT_SECONDS)


def test_config_nonpositive_timeout_falls_back_to_default():
    with patch.dict(os.environ, {"RLM_METACODE_URL": URL, "RLM_METACODE_TIMEOUT": "-5"}):
        assert get_graph_config() == (URL, DEFAULT_TIMEOUT_SECONDS)


def test_config_blank_url_disabled():
    with patch.dict(os.environ, {"RLM_METACODE_URL": "   "}):
        assert get_graph_config() is None


# ── helper factory shape ──────────────────────────────


def test_factory_returns_all_helpers():
    helpers = _helpers()
    assert set(helpers.keys()) == set(GRAPH_HELPER_NAMES)
    assert all(callable(fn) for fn in helpers.values())


def test_signatures_cover_all_helpers():
    for name in GRAPH_HELPER_NAMES:
        assert any(sig.startswith(name + "(") for sig in GRAPH_HELPER_SIGNATURES)


# ── graph_call ────────────────────────────────────────


def test_graph_call_passes_tool_and_params():
    call = MagicMock(return_value="result-text")
    helpers = _helpers(call_tool_fn=call)

    out = helpers["graph_call"]("find_metadata_usages", object_ref="Справочник.Контрагенты", limit=3)

    assert out == "result-text"
    call.assert_called_once_with(
        "find_metadata_usages", {"object_ref": "Справочник.Контрагенты", "limit": 3}
    )


def test_graph_call_rejects_empty_tool():
    helpers = _helpers()
    with pytest.raises(ValueError):
        helpers["graph_call"]("")


def test_graph_call_propagates_server_error():
    call = MagicMock(side_effect=RuntimeError("graph bridge: tool 'x' failed: boom"))
    helpers = _helpers(call_tool_fn=call)
    with pytest.raises(RuntimeError, match="boom"):
        helpers["graph_call"]("x")


# ── graph_tools ───────────────────────────────────────


def test_graph_tools_lists_and_caches():
    tools = [{"name": "search_bsl_code", "description": "Semantic search"}]
    lister = MagicMock(return_value=tools)
    helpers = _helpers(list_tools_fn=lister)

    assert helpers["graph_tools"]() == tools
    assert helpers["graph_tools"]() == tools
    lister.assert_called_once()  # cached


def test_graph_tools_refresh_refetches():
    lister = MagicMock(return_value=[])
    helpers = _helpers(list_tools_fn=lister)

    helpers["graph_tools"]()
    helpers["graph_tools"](refresh=True)
    assert lister.call_count == 2


# ── curated wrappers ──────────────────────────────────


def test_graph_search_code_maps_to_search_bsl_code():
    call = MagicMock(return_value="code-hits")
    helpers = _helpers(call_tool_fn=call)

    out = helpers["graph_search_code"]("где формируется уведомление", limit=7, module_type="CommonModule")

    assert out == "code-hits"
    call.assert_called_once_with(
        "search_bsl_code",
        {"query": "где формируется уведомление", "limit": 7, "module_type": "CommonModule"},
    )


def test_graph_search_code_rejects_empty_query():
    helpers = _helpers()
    with pytest.raises(ValueError):
        helpers["graph_search_code"]("")


def test_graph_search_routines_maps_to_search_bsl_routines():
    call = MagicMock(return_value="routine-hits")
    helpers = _helpers(call_tool_fn=call)

    out = helpers["graph_search_routines"]("РассчитатьГрафик", limit=2)

    assert out == "routine-hits"
    call.assert_called_once_with(
        "search_bsl_routines", {"query": "РассчитатьГрафик", "limit": 2}
    )


def test_graph_object_structure_maps_params():
    call = MagicMock(return_value="card")
    helpers = _helpers(call_tool_fn=call)

    out = helpers["graph_object_structure"](
        "Справочник.Контрагенты", sections=["attributes"], detail="standard"
    )

    assert out == "card"
    call.assert_called_once_with(
        "get_metadata_object_structure",
        {
            "detail": "standard",
            "sections": ["attributes"],
            "object_ref": "Справочник.Контрагенты",
        },
    )


def test_graph_object_structure_without_sections_omits_key():
    call = MagicMock(return_value="card")
    helpers = _helpers(call_tool_fn=call)

    helpers["graph_object_structure"]("Документ.Заказ")

    call.assert_called_once_with(
        "get_metadata_object_structure", {"object_ref": "Документ.Заказ"}
    )


def test_graph_object_structure_rejects_empty_ref():
    helpers = _helpers()
    with pytest.raises(ValueError):
        helpers["graph_object_structure"]("")


# ── _extract_text ─────────────────────────────────────


def test_extract_text_joins_text_blocks():
    block1 = MagicMock(text="part1")
    block2 = MagicMock(text="part2")
    result = MagicMock(content=[block1, block2])
    assert _extract_text(result) == "part1\npart2"


def test_extract_text_empty_content():
    assert _extract_text(MagicMock(content=[])) == ""
    assert _extract_text(MagicMock(content=None)) == ""


# ── strategy data stays in sync ───────────────────────


def test_strategy_io_section_mentions_graph_helpers():
    from rlm_tools_bsl.bsl_knowledge import _STRATEGY_IO_SECTION
    from rlm_tools_bsl.bsl_strategy_data import STRATEGY_SECTIONS

    for text in (STRATEGY_SECTIONS["io"], _STRATEGY_IO_SECTION):
        assert "GRAPH (if available" in text
        for name in GRAPH_HELPER_NAMES:
            assert name in text
