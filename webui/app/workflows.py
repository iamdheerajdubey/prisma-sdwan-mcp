"""Page-facing workflows: known MCP tools, called by name, normalized for display.

This is the rewritten half of what webtester's workflows.py did. What is gone
is `_call_candidates`/`_build_args`/`ask()` -- ranking every discovered tool
against a hand-written intent table and guessing arguments from parameter
names. A page here calls one specific, known tool by name with arguments the
page itself constructs, exactly as any ordinary frontend calls a known
backend endpoint. `normalizer.py` still does the real work of turning a
messy controller record into a stable shape; it is unchanged.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from . import normalizer as norm
from .mcp_client import McpClient, ToolError, TransportError


class TTLCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.RLock()

    def get(self, key: str, ttl: int) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            created, value = item
            if time.time() - created > ttl:
                self._data.pop(key, None)
                return None
            return value

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.time(), value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


def _source_meta(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"tool": call["tool"], "ok": "result" in call, "error": call.get("error")} for call in calls]


def _worst_status(statuses: list[str]) -> str:
    order = {"critical": 4, "degraded": 3, "unknown": 2, "healthy": 1, "resolved": 0}
    return max(statuses, key=lambda item: order.get(item, 2), default="unknown")


class WorkflowEngine:
    def __init__(self, client: McpClient) -> None:
        self.client = client
        self.cache = TTLCache()

    def _call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Invoke one known tool; never raises -- failure is a field on the record."""
        try:
            result = self.client.call_tool(tool, args)
            return {"tool": tool, "args": args, "result": result}
        except ToolError as exc:
            return {"tool": tool, "args": args, "error": str(exc), "error_detail": exc.error}
        except TransportError as exc:
            return {"tool": tool, "args": args, "error": str(exc), "error_detail": {"code": "transport_error", "message": str(exc)}}

    # -- pages -----------------------------------------------------------

    def dashboard(self, *, refresh: bool = False) -> dict[str, Any]:
        key = "dashboard"
        if not refresh and (cached := self.cache.get(key, 45)) is not None:
            return cached
        site_items = self.sites(refresh=refresh)["items"]
        finding_items = self.findings(refresh=refresh)["items"]
        result = {
            "summary": norm.dashboard_summary(site_items, finding_items),
            "attention": finding_items[:6],
            "sites": _prioritize_sites(site_items)[:8],
            "data_quality": _data_quality(sites=site_items, findings=finding_items),
        }
        self.cache.put(key, result)
        return result

    def sites(self, *, refresh: bool = False) -> dict[str, Any]:
        key = "sites"
        if not refresh and (cached := self.cache.get(key, 90)) is not None:
            return cached
        call = self._call("get_inventory", {"kind": "sites", "limit": 200})
        items = norm.normalize_sites(call["result"].get("sites", [])) if "result" in call else []
        result = {"items": items, "sources": _source_meta([call]), "count": len(items)}
        self.cache.put(key, result)
        return result

    def site_detail(self, site_id: str, *, refresh: bool = False) -> dict[str, Any]:
        key = f"site:{site_id}"
        if not refresh and (cached := self.cache.get(key, 45)) is not None:
            return cached

        site = next((item for item in self.sites(refresh=refresh)["items"] if item["id"] == site_id), None)
        element_call = self._call("get_inventory", {"kind": "elements", "limit": 200})
        wan_call = self._call("get_wan", {"operation": "interfaces", "site": site_id})
        alarm_call = self._call("get_monitoring", {"operation": "alarms", "site": site_id, "limit": 100})

        devices = [
            item
            for item in norm.normalize_resources(element_call["result"].get("elements", []), "Device")
            if item.get("site_id") == site_id
        ] if "result" in element_call else []
        connectivity = norm.normalize_resources(wan_call["result"].get("items", [])) if "result" in wan_call else []
        findings = norm.normalize_findings(alarm_call["result"].get("alarms", [])) if "result" in alarm_call else []

        if site is None:
            site = {"id": site_id, "name": "Selected site", "status": "unknown", "city": "", "country": ""}
        calculated_status = _worst_status(
            [site.get("status", "unknown")]
            + [item.get("status", "unknown") for item in connectivity]
            + ["critical" if finding.get("severity") == "critical" else "degraded" for finding in findings]
        )
        site = {**site, "status": calculated_status}

        result = {
            "site": site,
            "summary": {
                "devices_total": len(devices),
                "devices_healthy": sum(item.get("status") == "healthy" for item in devices),
                "connectivity_total": len(connectivity),
                "connectivity_degraded": sum(item.get("status") in ("critical", "degraded") for item in connectivity),
                "active_findings": len(findings),
            },
            "devices": devices,
            "connectivity": connectivity,
            "findings": findings,
            "sources": _source_meta([element_call, wan_call, alarm_call]),
        }
        self.cache.put(key, result)
        return result

    def findings(self, *, site_id: str = "", refresh: bool = False) -> dict[str, Any]:
        key = f"findings:{site_id or 'all'}"
        if not refresh and (cached := self.cache.get(key, 45)) is not None:
            return cached
        args: dict[str, Any] = {"operation": "alarms", "limit": 100}
        if site_id:
            args["site"] = site_id
        call = self._call("get_monitoring", args)
        items = norm.normalize_findings(call["result"].get("alarms", [])) if "result" in call else []
        result = {"items": items, "sources": _source_meta([call]), "count": len(items)}
        self.cache.put(key, result)
        return result

    def resources_search(self, kind: str, name: str) -> dict[str, Any]:
        """The user names the kind explicitly -- `find_resource`'s own contract,
        not a guess at which of several tools might match free text."""
        if not kind or not name.strip():
            return {"items": [], "count": 0, "sources": []}
        call = self._call("find_resource", {"kind": kind, "name": name.strip(), "limit": 100})
        if "result" not in call:
            return {"items": [], "count": 0, "sources": _source_meta([call])}
        items = norm.normalize_resources(call["result"].get("matches", []))
        return {"items": items, "count": len(items), "sources": _source_meta([call])}

    def telemetry(self, *, site_id: str, hours: float = 6, refresh: bool = False) -> dict[str, Any]:
        key = f"telemetry:{site_id}:{hours}"
        if not refresh and (cached := self.cache.get(key, 30)) is not None:
            return cached
        call = self._call("get_monitoring", {"operation": "link_metrics", "site": site_id, "hours": hours})
        metrics = call["result"].get("metrics", {}) if "result" in call else {}
        result = {
            "bandwidth": metrics.get("bandwidth", []),
            "link_quality": metrics.get("link_quality", []),
            "window": metrics.get("window"),
            "snapshot_time": metrics.get("snapshot_time"),
            "sources": _source_meta([call]),
        }
        self.cache.put(key, result)
        return result

    def admin_call(self, name: str, args: dict[str, Any]) -> Any:
        return self.client.call_tool(name, args)


def _data_quality(*, sites: list[dict[str, Any]], findings: list[dict[str, Any]]) -> dict[str, Any]:
    missing = []
    if not sites:
        missing.append("site inventory")
    return {
        "complete": not missing,
        "missing": missing,
        "message": "Live network data loaded." if not missing else "Some views have limited data because the tool returned nothing.",
    }


def _prioritize_sites(sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {"critical": 0, "degraded": 1, "unknown": 2, "healthy": 3}
    return sorted(sites, key=lambda item: (order.get(item.get("status"), 9), item.get("name", "").lower()))
