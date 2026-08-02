from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from importlib import import_module
from pathlib import Path
from typing import Any

from .catalog import ToolSpec, safe_public_tool


class MCPGateway:
    """Adapter around the installed Prisma SD-WAN MCP package and tool registry."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] | None = None
        self._lock = threading.RLock()
        self._imports_loaded = False
        self._mcp_server = None
        self._registry = None
        self._client_cls = None

    @staticmethod
    def _add_repository_to_path() -> None:
        """Locate the repository without assuming a clone path or working directory."""
        configured_root = os.getenv("PRISMA_MCP_ROOT", "").strip()
        candidates: list[Path] = []

        if configured_root:
            candidates.append(Path(configured_root).expanduser().resolve())

        current_file = Path(__file__).resolve()
        candidates.extend(current_file.parents)
        candidates.append(Path.cwd().resolve())
        candidates.extend(Path.cwd().resolve().parents)

        seen: set[Path] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            # "api-mcp" covers the PRISMA-MCP layout, where webtester sits
            # alongside api-mcp/ rather than inside it.
            for pkg_root in (candidate, candidate / "api-mcp"):
                if (pkg_root / "prisma_sdwan_mcp").is_dir():
                    candidate_text = str(pkg_root)
                    if candidate_text not in sys.path:
                        sys.path.insert(0, candidate_text)
                    return

        # The package may already be installed in the active Python environment.
        # Import will provide the normal ModuleNotFoundError if it is unavailable.

    def _load_imports(self) -> None:
        if self._imports_loaded:
            return

        self._add_repository_to_path()
        self._mcp_server = import_module("prisma_sdwan_mcp.server")
        self._registry = import_module("prisma_sdwan_mcp.registry")
        self._client_cls = import_module("prisma_sdwan_mcp.client").PrismaSDWANClient
        self._imports_loaded = True

    def tools(self) -> dict[str, ToolSpec]:
        with self._lock:
            if self._tools is not None:
                return self._tools
            self._load_imports()
            discovered = asyncio.run(self._mcp_server.mcp.list_tools())
            result: dict[str, ToolSpec] = {}
            for tool in discovered:
                module = getattr(tool.fn, "__module__", "")
                category = module.rsplit(".", 1)[-1] if module else "tool"
                result[tool.name] = ToolSpec(
                    name=tool.name,
                    description=tool.description or "",
                    category=category,
                    parameters=tool.parameters or {},
                    fn=tool.fn,
                )
            self._tools = result
            return result

    def public_tools(self) -> list[dict[str, Any]]:
        return [safe_public_tool(tool) for tool in self.tools().values()]

    def status(self) -> dict[str, Any]:
        self._load_imports()
        client = getattr(self._registry, "client", None)
        connected = bool(client and getattr(client, "logged_in", False))
        return {
            "connected": connected,
            "controller": getattr(client, "controller", None) if connected else None,
            "tenant": os.getenv("PAN_TSG_ID") if connected else None,
        }

    def auto_connect_from_environment(self) -> dict[str, Any]:
        status = self.status()
        if status["connected"]:
            return {"ok": True, **status}
        required = ("PAN_CLIENT_ID", "PAN_CLIENT_SECRET", "PAN_TSG_ID")
        if not all(os.getenv(key) for key in required):
            return {"ok": False, "error": "credentials are not configured", **status}
        return self.connect(
            client_id=os.environ["PAN_CLIENT_ID"],
            client_secret=os.environ["PAN_CLIENT_SECRET"],
            tsg_id=os.environ["PAN_TSG_ID"],
            region=os.getenv("PAN_REGION", ""),
        )

    def connect(self, *, client_id: str, client_secret: str, tsg_id: str, region: str = "") -> dict[str, Any]:
        self._load_imports()
        os.environ["PAN_CLIENT_ID"] = client_id.strip()
        os.environ["PAN_CLIENT_SECRET"] = client_secret.strip()
        os.environ["PAN_TSG_ID"] = tsg_id.strip()
        if region.strip():
            os.environ["PAN_REGION"] = region.strip()
        else:
            os.environ.pop("PAN_REGION", None)

        try:
            client = self._client_cls()
            client.login()
        except Exception as error:
            return {"ok": False, "error": str(error)}

        self._registry.client = client
        return {
            "ok": True,
            "connected": True,
            "controller": getattr(client, "controller", None),
            "tenant": tsg_id.strip(),
        }

    def invoke(self, name: str, args: dict[str, Any] | None = None) -> Any:
        self._load_imports()
        tool = self.tools().get(name)
        if tool is None:
            raise KeyError(f"unknown tool '{name}'")
        status = self.status()
        if not status["connected"]:
            auto = self.auto_connect_from_environment()
            if not auto.get("ok"):
                raise RuntimeError("Prisma SD-WAN is not connected")

        try:
            raw = tool.fn(**(args or {}))
        except TypeError as error:
            raise ValueError(f"bad arguments for {name}: {error}") from error

        if isinstance(raw, (dict, list, int, float, bool)) or raw is None:
            return raw
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return raw
