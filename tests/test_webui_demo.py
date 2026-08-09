"""Preview mode makes no MCP call: a real HTTP server, real requests, and a
CLIENT stand-in that raises if anything in it is ever touched."""
from __future__ import annotations

import json
import threading
import urllib.request

import pytest

# webui/server.py imports the assistant at module scope, so starting the console
# needs the optional `webui` extra even though this test never calls the model.
pytest.importorskip("anthropic", reason="requires the webui extra: pip install -e '.[webui]'")

import webui.server as server  # noqa: E402

pytestmark = pytest.mark.webui


class _PoisonPillClient:
    """Any attribute access proves a live-tenant call was attempted."""

    connected = False

    def __getattr__(self, name):
        raise AssertionError(f"Preview mode touched the MCP client via .{name}()")


@pytest.fixture
def running_server(monkeypatch):
    monkeypatch.setattr(server, "CLIENT", _PoisonPillClient())
    monkeypatch.setattr(server, "ENGINE", server.WorkflowEngine(server.CLIENT))
    httpd = server.LocalThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get(base_url: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base_url}{path}", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_demo_dashboard_never_touches_the_mcp_client(running_server):
    data = _get(running_server, "/api/demo/dashboard")
    assert "summary" in data


def test_demo_sites_and_findings_never_touch_the_mcp_client(running_server):
    sites = _get(running_server, "/api/demo/sites")
    assert sites["count"] > 0
    findings = _get(running_server, "/api/demo/findings")
    assert findings["count"] >= 0


def test_demo_status_reports_preview_without_a_live_call(running_server):
    status = _get(running_server, "/api/demo/status")
    assert status["demo"] is True
    assert status["connected"] is True
