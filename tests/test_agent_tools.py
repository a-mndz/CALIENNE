"""Tests for Agent Tools: Python REPL and Web Search (P2-01)."""

from __future__ import annotations

import pytest

from core.tools import PythonREPLTool, ToolRegistry, WebSearchTool


@pytest.mark.asyncio
async def test_python_repl_basic_execution() -> None:
    repl = PythonREPLTool(timeout_seconds=2.0)
    result = await repl.execute("x = 5 * 10\nprint(f'result={x}')")
    assert result.success is True
    assert "result=50" in result.output
    assert result.error is None
    assert result.execution_time_ms > 0


@pytest.mark.asyncio
async def test_python_repl_syntax_error() -> None:
    repl = PythonREPLTool()
    result = await repl.execute("def broken(")
    assert result.success is False
    assert "Syntax error" in (result.error or "")


@pytest.mark.asyncio
async def test_python_repl_banned_modules() -> None:
    repl = PythonREPLTool()
    result = await repl.execute("import subprocess\nsubprocess.run(['dir'])")
    assert result.success is False
    assert "prohibited" in (result.error or "")

    result_os = await repl.execute("import os\nos.listdir('.')")
    assert result_os.success is False
    assert "prohibited" in (result_os.error or "")


@pytest.mark.asyncio
async def test_python_repl_banned_builtins() -> None:
    repl = PythonREPLTool()
    result_eval = await repl.execute("eval('1 + 1')")
    assert result_eval.success is False
    assert "prohibited" in (result_eval.error or "")

    result_open = await repl.execute("open('file.txt', 'w')")
    assert result_open.success is False
    assert "prohibited" in (result_open.error or "")


@pytest.mark.asyncio
async def test_python_repl_dunder_attributes() -> None:
    repl = PythonREPLTool()
    result = await repl.execute("x = ().__class__.__base__")
    assert result.success is False
    assert "prohibited" in (result.error or "")


@pytest.mark.asyncio
async def test_web_search_tool_schema_compliance() -> None:
    search = WebSearchTool()
    res = await search.search("What is the consensus algorithm in Calienne?")
    assert res["status"] == "completed"
    assert res["agent"] == "WebSearchEngine"
    assert len(res["results"]) > 0
    assert "url" in res["results"][0]
    assert "confidence" in res
    assert res["search_performed"] is True
    assert res["results"][0]["source_authority"] == "SIMULATED"
    assert res["confidence"]["level"] == "LOW"


@pytest.mark.asyncio
async def test_tool_registry_definitions_and_dispatch() -> None:
    registry = ToolRegistry()
    defs = registry.get_tool_definitions()
    assert len(defs) == 2
    names = [d["function"]["name"] for d in defs]
    assert "execute_python" in names
    assert "web_search" in names

    # Dispatch python
    py_res = await registry.execute_tool("execute_python", {"code": "print(2 + 2)"})
    assert py_res.success is True
    assert "4" in py_res.output

    # Dispatch search
    search_res = await registry.execute_tool("web_search", {"query": "Calienne architecture"})
    assert search_res["status"] == "completed"
