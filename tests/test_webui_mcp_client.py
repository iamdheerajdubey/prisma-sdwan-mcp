"""mcp_client.py: transport/tool-error/success classification, and the
hard constraint that nothing under webui/ imports the server package."""
from __future__ import annotations

import ast
import asyncio
import threading
from pathlib import Path

import pytest

from webui.app import mcp_client as mc
from webui.app.trace import TRACE

WEBUI_ROOT = Path(__file__).resolve().parents[1] / "webui"


def test_no_module_under_webui_imports_prisma_sdwan_mcp():
    offenders = []
    for path in WEBUI_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "prisma_sdwan_mcp" or name.startswith("prisma_sdwan_mcp.") for name in names):
                offenders.append(f"{path}:{node.lineno}")
    assert not offenders, f"webui/ must not import prisma_sdwan_mcp: {offenders}"


class _Block:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _Result:
    def __init__(self, text: str, is_error: bool = False):
        self.content = [_Block(text)]
        self.isError = is_error


class _FakeSession:
    def __init__(self, responses: dict):
        self._responses = responses

    async def call_tool(self, name, arguments):
        value = self._responses[name]
        if callable(value):
            return value(arguments)
        return value


@pytest.fixture
def client_factory():
    created = []

    def _make(session):
        client = mc.McpClient.__new__(mc.McpClient)
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        client._loop = loop
        client._session = session
        client._thread = thread
        created.append(client)
        return client

    yield _make

    for client in created:
        loop = client._loop
        loop.call_soon_threadsafe(loop.stop)
        client._thread.join(timeout=5)

    TRACE.clear()


def test_successful_call_returns_parsed_payload(client_factory):
    session = _FakeSession({"find_site": _Result('{"contract_version": "2.0.0", "sites": [], "returned_count": 0, "truncated": false}')})
    client = client_factory(session)
    result = client.call_tool("find_site", {"name": "amsterdam"})
    assert result["returned_count"] == 0
    records = TRACE.list()["records"]
    assert records[-1]["outcome"] == "ok"
    assert records[-1]["tool"] == "find_site"


def test_empty_but_successful_result_is_not_an_error(client_factory):
    session = _FakeSession({"find_site": _Result('{"sites": [], "returned_count": 0, "truncated": false, "match_count": 0}')})
    client = client_factory(session)
    result = client.call_tool("find_site", {"name": "nowhere"})
    assert result["match_count"] == 0
    assert TRACE.list()["records"][-1]["outcome"] == "ok"


def test_tool_returned_structured_error_raises_tool_error(client_factory):
    error_json = '{"code": "not_found", "message": "element could not be resolved", "tool": "get_device_health", "retryable": false}'
    session = _FakeSession({"get_device_health": _Result(error_json)})
    client = client_factory(session)
    with pytest.raises(mc.ToolError) as excinfo:
        client.call_tool("get_device_health", {"element": "nope"})
    assert excinfo.value.error["code"] == "not_found"
    assert TRACE.list()["records"][-1]["outcome"] == "tool_error"


def test_ambiguous_match_candidates_pass_through_intact(client_factory):
    error_json = (
        '{"code": "ambiguous_match", "message": "2 sites match", "tool": "find_site", "retryable": false, '
        '"candidates": [{"id": "1", "name": "Amsterdam Branch"}, {"id": "2", "name": "Amsterdam HQ"}]}'
    )
    session = _FakeSession({"find_site": _Result(error_json)})
    client = client_factory(session)
    with pytest.raises(mc.ToolError) as excinfo:
        client.call_tool("find_site", {"name": "amsterdam"})
    assert len(excinfo.value.error["candidates"]) == 2
    assert excinfo.value.error["candidates"][0]["name"] == "Amsterdam Branch"


def test_protocol_level_error_is_a_distinguishable_tool_error(client_factory):
    session = _FakeSession({"find_site": _Result("Invalid arguments: name is required", is_error=True)})
    client = client_factory(session)
    with pytest.raises(mc.ToolError) as excinfo:
        client.call_tool("find_site", {})
    assert excinfo.value.error["code"] == "protocol_error"
    assert "name is required" in excinfo.value.error["message"]


def test_transport_failure_when_session_call_raises(client_factory):
    def _boom(_args):
        raise ConnectionError("subprocess pipe closed")

    session = _FakeSession({"find_site": _boom})
    client = client_factory(session)
    with pytest.raises(mc.TransportError):
        client.call_tool("find_site", {"name": "amsterdam"})
    assert TRACE.list()["records"][-1]["outcome"] == "transport_error"


def test_transport_failure_when_never_connected():
    client = mc.McpClient.__new__(mc.McpClient)
    client._loop = None
    client._session = None
    with pytest.raises(mc.TransportError):
        client.call_tool("find_site", {"name": "amsterdam"})


class _Annotations:
    def __init__(self, read_only_hint):
        self.readOnlyHint = read_only_hint


class _ToolDef:
    def __init__(self, name, description, input_schema, read_only_hint):
        self.name = name
        self.description = description
        self.inputSchema = input_schema
        self.annotations = _Annotations(read_only_hint)


class _ListToolsResult:
    def __init__(self, tools):
        self.tools = tools


def test_list_tools_surfaces_the_read_only_annotation(client_factory):
    class _ListSession:
        async def list_tools(self):
            return _ListToolsResult([
                _ToolDef("find_site", "resolve a site", {"type": "object"}, True),
                _ToolDef("run_commands", "ssh to the device", {"type": "object"}, False),
            ])

    client = client_factory(_ListSession())
    tools = client.list_tools()
    by_name = {tool["name"]: tool for tool in tools}
    assert by_name["find_site"]["read_only"] is True
    assert by_name["run_commands"]["read_only"] is False


def test_credentials_are_redacted_in_the_trace(client_factory):
    session = _FakeSession({"run_commands": _Result('{"results": [], "returned_count": 0, "truncated": false}')})
    client = client_factory(session)
    client.call_tool("run_commands", {"element": "ams-ion-01", "password": "hunter2"})
    args = TRACE.list()["records"][-1]["arguments"]
    assert args["password"] == "[REDACTED]"
    assert args["element"] == "ams-ion-01"
