"""Prisma SD-WAN network console.

Run from the repository root:
    python webui/server.py

An MCP client over stdio to `prisma-sdwan-mcp` -- the same relationship any
other MCP host (Claude Desktop included) has with the server. This process
never imports the server package.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

try:  # `python webui/server.py` -- webui/ itself is on sys.path
    from app import assistant, demo
    from app.mcp_client import McpClient, ToolError, TransportError, default_command
    from app.trace import TRACE
    from app.workflows import WorkflowEngine
except ImportError:  # imported as the `webui.server` module, e.g. by tests
    from webui.app import assistant, demo
    from webui.app.mcp_client import McpClient, ToolError, TransportError, default_command
    from webui.app.trace import TRACE
    from webui.app.workflows import WorkflowEngine

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MAX_BODY_BYTES = 2 * 1024 * 1024
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

CLIENT = McpClient()
ENGINE = WorkflowEngine(CLIENT)


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    server_version = "PrismaNetworkConsole/1.0"

    def log_message(self, fmt, *args):
        pass

    def _security_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )

    def _send_json(self, status: int, payload):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, error: Exception | str):
        message = str(error)
        if os.getenv("PRISMA_CONSOLE_DEBUG") == "1" and not isinstance(error, str):
            message = f"{message}\n{traceback.format_exc()}"
        self._send_json(status, {"ok": False, "error": message})

    def _send_tool_error(self, exc: ToolError | TransportError):
        if isinstance(exc, TransportError):
            self._send_json(502, {"ok": False, "error": str(exc), "error_detail": {"code": "transport_error", "message": str(exc)}})
        else:
            self._send_json(200, {"ok": False, "error": str(exc), "error_detail": exc.error})

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError("request body is too large")
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _serve_static(self, relative_path: str):
        relative_path = relative_path.lstrip("/") or "index.html"
        path = (STATIC_DIR / relative_path).resolve()
        try:
            path.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._send_json(403, {"error": "forbidden"})
            return
        if not path.is_file():
            self._send_json(404, {"error": "not found"})
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith(("text/", "application/javascript")) else content_type)
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                return self._serve_static("index.html")
            if path.startswith("/static/"):
                return self._serve_static(path[len("/static/"):])
            if path.startswith("/api/demo/"):
                return self._handle_demo_get(path, query)
            if path == "/api/status":
                return self._send_json(200, _status())
            if path == "/api/assistant/status":
                return self._send_json(200, assistant.status())
            if path == "/api/dashboard":
                return self._send_json(200, ENGINE.dashboard(refresh=_truthy(query.get("refresh"))))
            if path == "/api/sites":
                return self._send_json(200, ENGINE.sites(refresh=_truthy(query.get("refresh"))))
            if path.startswith("/api/sites/"):
                site_id = path.split("/", 3)[3]
                return self._send_json(200, ENGINE.site_detail(site_id, refresh=_truthy(query.get("refresh"))))
            if path == "/api/findings":
                return self._send_json(200, ENGINE.findings(site_id=_first(query, "site_id"), refresh=_truthy(query.get("refresh"))))
            if path == "/api/resources/search":
                return self._send_json(200, ENGINE.resources_search(_first(query, "kind"), _first(query, "q")))
            if path == "/api/telemetry":
                hours = float(_first(query, "hours") or 6)
                return self._send_json(200, ENGINE.telemetry(site_id=_first(query, "site_id"), hours=hours, refresh=_truthy(query.get("refresh"))))
            if path == "/api/admin/tools":
                return self._send_json(200, {"tools": CLIENT.list_tools()})
            if path == "/api/trace":
                return self._send_json(200, TRACE.list())
            return self._send_json(404, {"error": "not found"})
        except (ToolError, TransportError) as exc:
            return self._send_tool_error(exc)
        except Exception as error:
            return self._send_error_json(500, error)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/admin/call":
                name = str(body.get("tool", ""))
                args = body.get("args") or {}
                if not isinstance(args, dict):
                    return self._send_json(400, {"ok": False, "error": "args must be an object"})
                return self._send_json(200, {"ok": True, "result": ENGINE.admin_call(name, args)})
            if path == "/api/trace/clear":
                TRACE.clear()
                return self._send_json(200, {"ok": True})
            if path == "/api/cache/clear":
                ENGINE.cache.clear()
                return self._send_json(200, {"ok": True})
            if path == "/api/assistant/key":
                assistant.set_api_key(str(body.get("api_key", "")))
                return self._send_json(200, {"ok": True, **assistant.status()})
            if path == "/api/assistant/key/clear":
                assistant.clear_api_key()
                return self._send_json(200, {"ok": True, **assistant.status()})
            if path == "/api/assistant/ask":
                return self._stream_ask(str(body.get("question", "")))
            return self._send_json(404, {"error": "not found"})
        except (ToolError, TransportError) as exc:
            return self._send_tool_error(exc)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
            return self._send_error_json(400, error)
        except Exception as error:
            return self._send_error_json(500, error)

    def _stream_ask(self, question: str):
        """Newline-delimited JSON over chunked transfer encoding -- no framework,
        no SSE library, just the stdlib server writing one HTTP chunk per event."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self._security_headers()
        self.end_headers()

        def emit(event: dict) -> None:
            line = (json.dumps(event, ensure_ascii=False, default=str) + "\n").encode("utf-8")
            self.wfile.write(f"{len(line):x}\r\n".encode("ascii"))
            self.wfile.write(line)
            self.wfile.write(b"\r\n")

        try:
            for event in assistant.ask(question, CLIENT):
                emit(event)
        except Exception as error:  # noqa: BLE001 - reported to the client as an event, not a raised 500
            emit({"type": "error", "message": str(error)})
        finally:
            self.wfile.write(b"0\r\n\r\n")

    def _handle_demo_get(self, path: str, query: dict[str, list[str]]):
        subpath = path[len("/api/demo"):] or "/dashboard"
        if subpath == "/status":
            return self._send_json(200, {"connected": True, "controller": "Preview environment", "tenant": "Demo tenant", "demo": True})
        if subpath == "/dashboard":
            return self._send_json(200, demo.dashboard())
        if subpath == "/sites":
            return self._send_json(200, {"items": demo.SITES, "count": len(demo.SITES), "sources": [{"tool": "preview-data", "ok": True}]})
        if subpath.startswith("/sites/"):
            return self._send_json(200, demo.site_detail(subpath.split("/", 2)[2]))
        if subpath == "/findings":
            return self._send_json(200, {"items": demo.FINDINGS, "count": len(demo.FINDINGS), "sources": [{"tool": "preview-data", "ok": True}]})
        if subpath == "/resources/search":
            q = _first(query, "q").lower()
            items = demo.RESOURCES
            if q:
                items = [item for item in items if q in " ".join(str(value).lower() for value in item.values())]
            return self._send_json(200, {"items": items, "count": len(items), "sources": [{"tool": "preview-data", "ok": True}]})
        if subpath == "/telemetry":
            return self._send_json(200, demo.telemetry(_first(query, "site_id")))
        return self._send_json(404, {"error": "demo route not found"})


def _status() -> dict:
    connected = CLIENT.connected
    error = None
    tool_count = None
    if connected:
        try:
            tool_count = len(CLIENT.list_tools())
        except (ToolError, TransportError) as exc:
            connected = False
            error = str(exc)
    else:
        error = "not connected"
    return {"connected": connected, "tool_count": tool_count, "command": default_command(), "error": error}


def _first(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name) or []
    return values[0] if values else ""


def _truthy(values: list[str] | None) -> bool:
    return bool(values and values[0].lower() in ("1", "true", "yes", "on"))


def main():
    parser = argparse.ArgumentParser(description="Prisma SD-WAN network console")
    parser.add_argument("--host", default=os.getenv("PRISMA_CONSOLE_HOST", "127.0.0.1"), help="Bind address (default: PRISMA_CONSOLE_HOST or 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PRISMA_CONSOLE_PORT", "8766")), help="TCP port (default: PRISMA_CONSOLE_PORT or 8766)")
    args = parser.parse_args()

    if args.host not in LOOPBACK_HOSTS:
        print(
            f"WARNING: binding to {args.host}, not loopback. The console has no authentication of its "
            "own -- anything that can reach this address can drive your live tenant through it, and read "
            "the call trace. Anthropic API keys posted from the browser also cross this address in plaintext.",
            file=sys.stderr,
        )

    try:
        CLIENT.start()
    except TransportError as exc:
        print(f"Could not start the MCP session: {exc}. Browsing and Preview still work; live pages will report a connection error.", file=sys.stderr)

    server = LocalThreadingHTTPServer((args.host, args.port), Handler)
    display_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print(f"Prisma SD-WAN Network Console: http://{display_host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        CLIENT.close()


if __name__ == "__main__":
    main()
