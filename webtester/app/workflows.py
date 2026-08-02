from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime
from typing import Any

from .catalog import ToolSpec, rank_tools, score_tool
from .mcp_gateway import MCPGateway
from .normalizer import (
    dashboard_summary,
    normalize_findings,
    normalize_resources,
    normalize_sites,
    normalize_telemetry,
)


ARG_ALIASES: dict[str, tuple[str, ...]] = {
    "site_id": ("site_id", "siteid", "site", "id"),
    "element_id": ("element_id", "device_id", "deviceid", "elementid", "device", "element"),
    "wan_id": ("wan_id", "circuit_id", "path_id", "link_id", "wanid"),
    "path_id": ("path_id", "wan_id", "link_id", "circuit_id"),
    "start_time": ("start_time", "start", "from_time", "from", "since"),
    "end_time": ("end_time", "end", "to_time", "to", "until"),
    "limit": ("limit", "page_size", "size", "count"),
}


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


class WorkflowEngine:
    def __init__(self, gateway: MCPGateway) -> None:
        self.gateway = gateway
        self.cache = TTLCache()

    def capabilities(self) -> dict[str, Any]:
        tools = list(self.gateway.tools().values())
        intents: dict[str, Any] = {}
        for intent in ("sites", "devices", "alarms", "connectivity", "telemetry", "resources"):
            ranked = rank_tools(tools, intent)
            intents[intent] = {
                "available": bool(ranked),
                "candidate_count": len(ranked),
                "best_match": ranked[0].name if ranked else None,
            }
        return {"intents": intents, "tool_count": len(tools)}

    def dashboard(self, *, refresh: bool = False) -> dict[str, Any]:
        key = "dashboard"
        if not refresh and (cached := self.cache.get(key, 45)) is not None:
            return cached
        sites = self.sites(refresh=refresh)["items"]
        findings = self.findings(refresh=refresh)["items"]
        result = {
            "summary": dashboard_summary(sites, findings),
            "attention": findings[:6],
            "sites": _prioritize_sites(sites)[:8],
            "data_quality": self._data_quality(sites=sites, findings=findings),
        }
        self.cache.put(key, result)
        return result

    def sites(self, *, refresh: bool = False) -> dict[str, Any]:
        key = "sites"
        if not refresh and (cached := self.cache.get(key, 90)) is not None:
            return cached
        calls = self._call_candidates("sites", context={}, max_calls=3)
        items: list[dict[str, Any]] = []
        for call in calls:
            items.extend(normalize_sites(call["result"]))
        items = _dedupe(items)
        result = {"items": items, "sources": _source_meta(calls), "count": len(items)}
        self.cache.put(key, result)
        return result

    def site_detail(self, site_id: str, *, refresh: bool = False) -> dict[str, Any]:
        key = f"site:{site_id}"
        if not refresh and (cached := self.cache.get(key, 45)) is not None:
            return cached

        sites = self.sites(refresh=refresh)["items"]
        site = next((item for item in sites if item["id"] == site_id), None)
        context = {"site_id": site_id, "limit": 200}
        device_calls = self._call_candidates("devices", context=context, max_calls=2)
        connection_calls = self._call_candidates("connectivity", context=context, max_calls=3)
        alarm_calls = self._call_candidates("alarms", context=context, max_calls=2)

        devices = _dedupe(
            [resource for call in device_calls for resource in normalize_resources(call["result"], "Device")]
        )
        connectivity = _dedupe(
            [resource for call in connection_calls for resource in normalize_resources(call["result"])]
        )
        findings = _dedupe(
            [finding for call in alarm_calls for finding in normalize_findings(call["result"])]
        )

        if site is None:
            site = {"id": site_id, "name": "Selected site", "status": "unknown", "city": "", "country": ""}
        calculated_status = _worst_status(
            [site.get("status", "unknown")]
            + [resource.get("status", "unknown") for resource in connectivity]
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
            "sources": _source_meta(device_calls + connection_calls + alarm_calls),
        }
        self.cache.put(key, result)
        return result

    def findings(self, *, site_id: str = "", refresh: bool = False) -> dict[str, Any]:
        key = f"findings:{site_id or 'all'}"
        if not refresh and (cached := self.cache.get(key, 45)) is not None:
            return cached
        context = {"site_id": site_id, "limit": 250} if site_id else {"limit": 250}
        calls = self._call_candidates("alarms", context=context, max_calls=4)
        items = _dedupe([finding for call in calls for finding in normalize_findings(call["result"])])
        result = {"items": items, "sources": _source_meta(calls), "count": len(items)}
        self.cache.put(key, result)
        return result

    def resources_search(self, query: str) -> dict[str, Any]:
        query = query.strip()
        resources: list[dict[str, Any]] = []

        # Reuse cached top-level inventories first.
        for site in self.sites()["items"]:
            resources.append({
                "id": site["id"], "name": site["name"], "type": "Site", "status": site["status"],
                "site_id": site["id"], "site_name": site["name"], "model": "", "description": "",
            })

        calls = self._call_candidates("resources", context={"limit": 300}, max_calls=5)
        for call in calls:
            resources.extend(normalize_resources(call["result"]))
        resources = _dedupe(resources)

        if query:
            tokens = [token for token in re.split(r"\s+", query.lower()) if token]
            resources = [item for item in resources if all(token in _resource_text(item) for token in tokens)]
        return {"items": resources[:100], "count": min(len(resources), 100), "sources": _source_meta(calls)}

    def telemetry(
        self,
        *,
        site_id: str = "",
        element_id: str = "",
        wan_id: str = "",
        start_time: Any = None,
        end_time: Any = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        context = {
            "site_id": site_id,
            "element_id": element_id,
            "wan_id": wan_id,
            "path_id": wan_id,
            "start_time": start_time,
            "end_time": end_time,
            "limit": 500,
        }
        key = "telemetry:" + ":".join(str(context[name] or "") for name in ("site_id", "element_id", "wan_id", "start_time", "end_time"))
        if not refresh and (cached := self.cache.get(key, 30)) is not None:
            return cached

        calls = self._call_candidates("telemetry", context=context, max_calls=4)
        merged_points: list[dict[str, Any]] = []
        merged_summary: dict[str, Any] = {}
        raw_sources: list[Any] = []
        for call in calls:
            normalized = normalize_telemetry(call["result"])
            merged_points.extend(normalized["points"])
            merged_summary.update(normalized["summary"])
            raw_sources.append(normalized["raw"])
        result = {
            "summary": merged_summary,
            "points": merged_points,
            "sources": _source_meta(calls),
            "raw_source_count": len(raw_sources),
        }
        self.cache.put(key, result)
        return result

    def ask(self, question: str) -> dict[str, Any]:
        text = question.strip()
        lowered = text.lower()
        if not text:
            return {"answer": "Enter a network question.", "type": "empty", "items": []}

        if any(term in lowered for term in ("attention", "problem", "issue", "alarm", "incident", "wrong")):
            findings = self.findings()["items"]
            if not findings:
                return {"answer": "No active findings were returned by the available monitoring tools.", "type": "findings", "items": []}
            return {
                "answer": f"{len(findings)} network findings are currently visible. The highest-priority items are shown below.",
                "type": "findings",
                "items": findings[:8],
            }

        if any(term in lowered for term in ("site", "branch", "location", "healthy", "health")):
            sites = self.sites()["items"]
            matched = [site for site in sites if site["name"].lower() in lowered or any(token in site["name"].lower() for token in lowered.split() if len(token) > 3)]
            if matched:
                details = [self.site_detail(site["id"]) for site in matched[:3]]
                names = ", ".join(detail["site"]["name"] for detail in details)
                return {"answer": f"Here is the current network view for {names}.", "type": "sites", "items": details}
            degraded = [site for site in sites if site.get("status") in ("critical", "degraded")]
            return {
                "answer": f"{len(degraded)} of {len(sites)} visible sites currently need attention.",
                "type": "site_list",
                "items": degraded[:10] if degraded else sites[:10],
            }

        if any(term in lowered for term in ("latency", "packet loss", "jitter", "telemetry", "performance")):
            telemetry = self.telemetry()
            if not telemetry["summary"]:
                return {"answer": "No top-level telemetry could be returned without selecting a site or path.", "type": "telemetry", "items": telemetry}
            return {"answer": "The latest available performance metrics are shown below.", "type": "telemetry", "items": telemetry}

        resources = self.resources_search(text)
        if resources["items"]:
            return {
                "answer": f"I found {resources['count']} network resources matching your question.",
                "type": "resources",
                "items": resources["items"][:12],
            }
        return {
            "answer": "I could not map that question to a supported network workflow. Try asking about site health, active issues, devices, paths, or performance.",
            "type": "unsupported",
            "items": [],
        }

    def admin_call(self, name: str, args: dict[str, Any]) -> Any:
        return self.gateway.invoke(name, args)

    def _call_candidates(self, intent: str, *, context: dict[str, Any], max_calls: int) -> list[dict[str, Any]]:
        tools = list(self.gateway.tools().values())
        calls: list[dict[str, Any]] = []
        for tool in rank_tools(tools, intent):
            args = _build_args(tool, context)
            if args is None:
                continue
            try:
                result = self.gateway.invoke(tool.name, args)
            except Exception as error:
                calls.append({"tool": tool.name, "args": args, "error": str(error), "score": score_tool(tool, intent)})
                continue
            calls.append({"tool": tool.name, "args": args, "result": result, "score": score_tool(tool, intent)})
            if len([call for call in calls if "result" in call]) >= max_calls:
                break
        return calls

    def _data_quality(self, *, sites: list[dict[str, Any]], findings: list[dict[str, Any]]) -> dict[str, Any]:
        missing = []
        if not sites:
            missing.append("site inventory")
        if not findings:
            missing.append("active findings")
        return {
            "complete": not missing,
            "missing": missing,
            "message": "Live network data loaded." if not missing else "Some customer views have limited data because no compatible tool result was returned.",
        }


def _build_args(tool: ToolSpec, context: dict[str, Any]) -> dict[str, Any] | None:
    args: dict[str, Any] = {}
    for param_name, schema in tool.properties.items():
        value = _context_value(param_name, context)
        if value not in (None, ""):
            args[param_name] = _coerce(value, schema)
            continue
        if param_name in tool.required:
            if "default" in schema:
                args[param_name] = schema["default"]
            elif param_name.lower() in ("limit", "page_size", "size", "count"):
                args[param_name] = 200
            elif param_name.lower() in ("offset", "page", "page_number"):
                args[param_name] = 0
            elif param_name.lower() in ("interval", "granularity", "sampling_interval"):
                args[param_name] = 300 if schema.get("type") in ("integer", "number") else "5min"
            elif param_name.lower() in ("api_version", "version"):
                args[param_name] = schema.get("default") or "v2.0"
            else:
                return None
    return args


def _context_value(param_name: str, context: dict[str, Any]) -> Any:
    lower = param_name.lower()
    if lower in context:
        return context[lower]
    if lower in ("tsg_id", "tenant_id", "tenant_service_group_id"):
        return os.getenv("PAN_TSG_ID")
    if lower in ("region", "pan_region"):
        return os.getenv("PAN_REGION")
    for canonical, aliases in ARG_ALIASES.items():
        if lower in aliases and context.get(canonical) not in (None, ""):
            return context[canonical]
    # Common plural/filter variations.
    for key, value in context.items():
        if value in (None, ""):
            continue
        normalized = key.lower().replace("_", "")
        if normalized == lower.replace("_", ""):
            return value
    return None


def _coerce(value: Any, schema: dict[str, Any]) -> Any:
    kind = schema.get("type")
    if kind == "integer":
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                description = str(schema.get("description", "")).lower()
                multiplier = 1000 if "millisecond" in description or "epoch ms" in description else 1
                return int(parsed.timestamp() * multiplier)
            except (TypeError, ValueError):
                return value
    if kind == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("1", "true", "yes", "on")
    if kind == "array" and not isinstance(value, list):
        return [value]
    return value


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = str(item.get("id") or f"{item.get('type')}:{item.get('name')}:{item.get('title')}")
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _source_meta(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "tool": call["tool"],
            "ok": "result" in call,
            "error": call.get("error"),
            "score": call.get("score"),
        }
        for call in calls
    ]


def _resource_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key, "")).lower() for key in ("name", "type", "status", "site_name", "model", "description"))


def _prioritize_sites(sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {"critical": 0, "degraded": 1, "unknown": 2, "healthy": 3}
    return sorted(sites, key=lambda item: (order.get(item.get("status"), 9), item.get("name", "").lower()))


def _worst_status(statuses: list[str]) -> str:
    order = {"critical": 4, "degraded": 3, "unknown": 2, "healthy": 1, "resolved": 0}
    return max(statuses, key=lambda item: order.get(item, 2), default="unknown")
