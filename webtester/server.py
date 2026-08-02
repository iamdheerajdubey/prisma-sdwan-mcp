"""Customer-facing Prisma SD-WAN portal powered by the existing MCP tools.

Run from the repository root:
    python webtester/server.py

The bind address and port are configurable with CLI options or environment variables.
"""
from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from app import demo
from app.mcp_gateway import MCPGateway
from app.workflows import WorkflowEngine


logging.basicConfig(level=logging.WARNING)
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MAX_BODY_BYTES = 2 * 1024 * 1024

GATEWAY = MCPGateway()
ENGINE = WorkflowEngine(GATEWAY)


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    server_version = "PrismaNetworkExperience/1.0"

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
        if os.getenv("PRISMA_PORTAL_DEBUG") == "1" and not isinstance(error, str):
            message = f"{message}\n{traceback.format_exc()}"
        self._send_json(status, {"ok": False, "error": message})

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
                return self._send_json(200, GATEWAY.status())
            if path == "/api/capabilities":
                return self._send_json(200, ENGINE.capabilities())
            if path == "/api/dashboard":
                return self._send_json(200, ENGINE.dashboard(refresh=_truthy(query.get("refresh"))))
            if path == "/api/sites":
                return self._send_json(200, ENGINE.sites(refresh=_truthy(query.get("refresh"))))
            if path.startswith("/api/sites/"):
                site_id = path.split("/", 3)[3]
                return self._send_json(200, ENGINE.site_detail(site_id, refresh=_truthy(query.get("refresh"))))
            if path == "/api/findings":
                site_id = _first(query, "site_id")
                return self._send_json(200, ENGINE.findings(site_id=site_id, refresh=_truthy(query.get("refresh"))))
            if path == "/api/resources/search":
                return self._send_json(200, ENGINE.resources_search(_first(query, "q")))
            if path == "/api/telemetry":
                return self._send_json(
                    200,
                    ENGINE.telemetry(
                        site_id=_first(query, "site_id"),
                        element_id=_first(query, "element_id"),
                        wan_id=_first(query, "wan_id"),
                        start_time=_first(query, "start_time"),
                        end_time=_first(query, "end_time"),
                        refresh=_truthy(query.get("refresh")),
                    ),
                )
            if path == "/api/admin/tools":
                return self._send_json(200, {"tools": GATEWAY.public_tools()})
            return self._send_json(404, {"error": "not found"})
        except Exception as error:
            return self._send_error_json(500, error)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/demo/ask":
                question = str(body.get("question", "")).strip().lower()
                if any(term in question for term in ("issue", "problem", "alarm", "incident", "attention", "wrong")):
                    return self._send_json(200, {"answer": f"{len(demo.FINDINGS)} network findings are visible in preview mode.", "type": "findings", "items": demo.FINDINGS})
                if any(term in question for term in ("latency", "packet loss", "jitter", "performance", "telemetry")):
                    return self._send_json(200, {"answer": "The preview telemetry shows elevated latency and packet loss for Amsterdam Branch.", "type": "telemetry", "items": demo.telemetry("site-amsterdam")})
                matched_sites = [site for site in demo.SITES if site["name"].lower() in question or any(token in site["name"].lower() for token in question.split() if len(token) > 3)]
                if matched_sites:
                    return self._send_json(200, {"answer": f"Here is the current preview view for {', '.join(site['name'] for site in matched_sites[:3])}.", "type": "sites", "items": [demo.site_detail(site["id"]) for site in matched_sites[:3]]})
                if any(term in question for term in ("site", "branch", "health", "healthy")):
                    attention = [site for site in demo.SITES if site["status"] in ("critical", "degraded")]
                    return self._send_json(200, {"answer": f"{len(attention)} of {len(demo.SITES)} preview sites need attention.", "type": "site_list", "items": attention})
                return self._send_json(200, {"answer": "I found network resources matching the preview question.", "type": "resources", "items": demo.RESOURCES[:8]})
            if path == "/api/connect":
                required = ("client_id", "client_secret", "tsg_id")
                if not all(str(body.get(key, "")).strip() for key in required):
                    return self._send_json(400, {"ok": False, "error": "client_id, client_secret, and tsg_id are required"})
                result = GATEWAY.connect(
                    client_id=str(body["client_id"]),
                    client_secret=str(body["client_secret"]),
                    tsg_id=str(body["tsg_id"]),
                    region=str(body.get("region", "")),
                )
                if result.get("ok"):
                    ENGINE.cache.clear()
                return self._send_json(200, result)
            if path == "/api/ask":
                return self._send_json(200, ENGINE.ask(str(body.get("question", ""))))
            if path == "/api/admin/call":
                name = str(body.get("tool", ""))
                args = body.get("args") or {}
                if not isinstance(args, dict):
                    return self._send_json(400, {"ok": False, "error": "args must be an object"})
                return self._send_json(200, {"ok": True, "result": ENGINE.admin_call(name, args)})
            if path == "/api/cache/clear":
                ENGINE.cache.clear()
                return self._send_json(200, {"ok": True})
            return self._send_json(404, {"error": "not found"})
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
            return self._send_error_json(400, error)
        except Exception as error:
            return self._send_error_json(500, error)

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
            items = demo.RESOURCES + [
                {"id": site["id"], "name": site["name"], "type": "Site", "status": site["status"], "site_id": site["id"], "site_name": site["name"], "model": "", "description": ""}
                for site in demo.SITES
            ]
            if q:
                items = [item for item in items if q in " ".join(str(value).lower() for value in item.values())]
            return self._send_json(200, {"items": items, "count": len(items), "sources": [{"tool": "preview-data", "ok": True}]})
        if subpath == "/telemetry":
            return self._send_json(200, demo.telemetry(_first(query, "site_id")))
        return self._send_json(404, {"error": "demo route not found"})


def _first(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name) or []
    return values[0] if values else ""


def _truthy(values: list[str] | None) -> bool:
    return bool(values and values[0].lower() in ("1", "true", "yes", "on"))


def main():
    parser = argparse.ArgumentParser(description="Customer-facing Prisma SD-WAN network portal")
    parser.add_argument(
        "--host",
        default=os.getenv("PRISMA_PORTAL_HOST", "127.0.0.1"),
        help="Bind address (default: PRISMA_PORTAL_HOST or 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PRISMA_PORTAL_PORT", "8765")),
        help="TCP port (default: PRISMA_PORTAL_PORT or 8765)",
    )
    args = parser.parse_args()

    if all(os.getenv(key) for key in ("PAN_CLIENT_ID", "PAN_CLIENT_SECRET", "PAN_TSG_ID")):
        result = GATEWAY.auto_connect_from_environment()
        if not result.get("ok"):
            print(f"Environment auto-connect failed: {result.get('error')}")

    server = LocalThreadingHTTPServer((args.host, args.port), Handler)
    display_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print(f"Prisma SD-WAN Network Experience: http://{display_host}:{args.port}/")
    print(f"Bound to {args.host}:{args.port}.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
