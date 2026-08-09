from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable


LIST_KEYS = (
    "items", "data", "results", "objects", "records", "sites", "devices", "elements",
    "alarms", "alerts", "incidents", "events", "paths", "links", "circuits", "metrics",
)


def first_value(record: dict[str, Any], *keys: str, default: Any = None) -> Any:
    lowered = {str(key).lower(): value for key, value in record.items()}
    for key in keys:
        if key.lower() in lowered and lowered[key.lower()] not in (None, ""):
            return lowered[key.lower()]
    return default


def flatten_records(payload: Any, *, max_depth: int = 5) -> list[dict[str, Any]]:
    """Extract likely business records from provider-specific response envelopes."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict) and max_depth > 0:
            nested = flatten_records(value, max_depth=max_depth - 1)
            if nested:
                return nested

    # A single record should remain usable.
    scalar_count = sum(not isinstance(value, (dict, list)) for value in payload.values())
    if scalar_count >= 2:
        return [payload]

    if max_depth > 0:
        candidates: list[dict[str, Any]] = []
        for value in payload.values():
            if isinstance(value, (dict, list)):
                candidates.extend(flatten_records(value, max_depth=max_depth - 1))
        return candidates
    return []


def stable_id(prefix: str, record: dict[str, Any]) -> str:
    raw = json.dumps(record, sort_keys=True, default=str, ensure_ascii=False)
    return f"{prefix}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"


def normalize_status(value: Any) -> str:
    text = str(value or "unknown").strip().lower().replace("_", " ").replace("-", " ")
    if any(term in text for term in ("critical", "failed", "down", "offline", "unreachable", "error")):
        return "critical"
    if any(term in text for term in ("degraded", "warning", "warn", "impaired", "partial", "unstable")):
        return "degraded"
    if any(term in text for term in ("healthy", "good", "up", "online", "active", "connected", "ok", "normal")):
        return "healthy"
    if any(term in text for term in ("closed", "cleared", "resolved", "inactive")):
        return "resolved"
    return "unknown"


def normalize_severity(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.isdigit():
        number = int(text)
        if number >= 4:
            return "critical"
        if number == 3:
            return "high"
        if number == 2:
            return "medium"
        return "low"
    if any(term in text for term in ("critical", "fatal", "emergency", "sev1", "p1")):
        return "critical"
    if any(term in text for term in ("high", "major", "sev2", "p2")):
        return "high"
    if any(term in text for term in ("medium", "minor", "warning", "warn", "sev3", "p3")):
        return "medium"
    return "low"


def normalize_sites(payload: Any) -> list[dict[str, Any]]:
    sites: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in flatten_records(payload):
        site_id = first_value(record, "site_id", "siteid", "id", "_id", "resource_id")
        name = first_value(record, "site_name", "sitename", "name", "display_name", "label")
        # Avoid treating unrelated records as sites.
        text = json.dumps(record, default=str).lower()
        if not name and "site" not in text:
            continue
        site_id = str(site_id or stable_id("site", record))
        if site_id in seen:
            continue
        seen.add(site_id)
        status = normalize_status(first_value(record, "health", "status", "state", "connectivity_status", "admin_state"))
        sites.append({
            "id": site_id,
            "name": str(name or f"Site {len(sites) + 1}"),
            "status": status,
            "city": first_value(record, "city", "location", "address", "region", default=""),
            "country": first_value(record, "country", "country_name", default=""),
            "device_count": _to_int(first_value(record, "device_count", "devices", "element_count")),
            "active_findings": _to_int(first_value(record, "alarm_count", "active_alarms", "incident_count")),
            "raw": record,
        })
    return sorted(sites, key=lambda item: item["name"].lower())


def normalize_resources(payload: Any, resource_type: str | None = None) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in flatten_records(payload):
        rid = first_value(record, "id", "_id", "resource_id", "element_id", "device_id", "wan_id", "path_id", "interface_id", "site_id")
        name = first_value(record, "name", "display_name", "site_name", "device_name", "element_name", "path_name", "wan_name", "label")
        if not name and not rid:
            continue
        rid = str(rid or stable_id("resource", record))
        if rid in seen:
            continue
        seen.add(rid)
        inferred_type = resource_type or infer_resource_type(record)
        resources.append({
            "id": rid,
            "name": str(name or rid),
            "type": inferred_type,
            "status": normalize_status(first_value(record, "health", "status", "state", "oper_status", "connectivity_status")),
            "site_id": first_value(record, "site_id", "parent_site_id", default=""),
            "site_name": first_value(record, "site_name", "parent_site_name", default=""),
            "model": first_value(record, "model", "device_model", "platform", "type", default=""),
            "description": first_value(record, "description", "summary", default=""),
            "raw": record,
        })
    return resources


def infer_resource_type(record: dict[str, Any]) -> str:
    explicit = str(first_value(record, "resource_type", "object_type", "kind", "type", default="")).lower()
    keys = " ".join(str(key).lower() for key in record)
    values = " ".join(str(value).lower() for value in record.values() if isinstance(value, (str, int)))
    text = f"{explicit} {keys} {values}"
    if any(term in explicit for term in ("wan", "circuit")) or any(key in keys for key in ("wan_id", "circuit_id")):
        return "WAN circuit"
    if "path" in explicit or "link" in explicit or any(key in keys for key in ("path_id", "link_id")):
        return "Network path"
    if any(term in explicit for term in ("device", "element", "ion", "appliance")) or any(key in keys for key in ("device_id", "element_id")):
        return "Device"
    if "interface" in explicit or "port" in explicit or "interface_id" in keys:
        return "Interface"
    if "vpn" in text:
        return "VPN"
    if "peer" in text or "bgp" in text:
        return "Routing peer"
    if "site" in explicit or "branch" in explicit or "site_id" in keys:
        return "Site"
    return "Resource"


def normalize_findings(payload: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in flatten_records(payload):
        fid = first_value(record, "id", "alarm_id", "incident_id", "event_id", "code", "event_code")
        title = first_value(record, "title", "name", "summary", "message", "description", "code", "event_code")
        if not title:
            continue
        fid = str(fid or stable_id("finding", record))
        if fid in seen:
            continue
        seen.add(fid)
        raw_state = str(first_value(record, "status", "state", "lifecycle_state", default="active")).strip().lower()
        if any(term in raw_state for term in ("closed", "cleared", "resolved")):
            status = "resolved"
        elif any(term in raw_state for term in ("active", "open", "raised", "new", "ongoing")):
            status = "active"
        else:
            status = normalize_status(raw_state)
        severity = normalize_severity(first_value(record, "severity", "priority", "level", "impact"))
        site_name = first_value(record, "site_name", "site", "location_name", default="")
        resource = first_value(record, "resource_name", "entity_name", "device_name", "element_name", "path_name", "interface_name", default="")
        started = first_value(record, "created_at", "start_time", "timestamp", "event_time", "raised_at", default="")
        findings.append({
            "id": fid,
            "title": str(title),
            "severity": severity,
            "status": status if status != "unknown" else "active",
            "site_name": str(site_name or "Unknown site"),
            "resource": str(resource or "Network resource"),
            "started": started,
            "impact": impact_text(str(title), severity),
            "recommendation": recommendation_text(str(title)),
            "raw": record,
        })
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(findings, key=lambda item: (order.get(item["severity"], 9), str(item["started"])), reverse=False)


def impact_text(title: str, severity: str) -> str:
    text = title.lower()
    if "packet" in text and "loss" in text:
        return "Interactive applications, voice, and video may experience degraded quality."
    if "latency" in text or "delay" in text:
        return "Applications may respond slowly for users on the affected path."
    if any(term in text for term in ("down", "unreachable", "offline", "lost")):
        return "Connectivity may be unavailable unless a healthy backup path is active."
    if "bgp" in text or "peer" in text:
        return "Route reachability may be reduced or unstable."
    if severity in ("critical", "high"):
        return "Service quality or availability may be affected."
    return "No confirmed customer impact is available from the current evidence."


def recommendation_text(title: str) -> str:
    text = title.lower()
    if "packet" in text and "loss" in text:
        return "Review the affected circuit and compare performance against the backup path."
    if "latency" in text:
        return "Compare path latency and utilization, then check provider performance."
    if "bgp" in text or "peer" in text:
        return "Verify peer reachability, session state, and recent routing changes."
    if "interface" in text or "link" in text:
        return "Check physical state, administrative state, and upstream connectivity."
    return "Review the technical evidence and the affected resource state."


def normalize_telemetry(payload: Any) -> dict[str, Any]:
    points: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}

    records = _metric_records(payload)
    for index, record in enumerate(records):
        timestamp = first_value(record, "timestamp", "time", "ts", "sample_time", "start_time", default=index)
        point = {
            "timestamp": timestamp,
            "latency_ms": _to_float(first_value(record, "latency_ms", "rtt_latency_ms", "latency", "rtt")),
            "packet_loss_pct": _to_float(first_value(record, "packet_loss_pct", "packet_loss", "loss_pct", "loss")),
            "jitter_ms": _to_float(first_value(record, "jitter_ms", "jitter")),
            "utilization_pct": _to_float(first_value(record, "utilization_pct", "utilization", "usage_pct", "throughput_pct")),
            "availability_pct": _to_float(first_value(record, "availability_pct", "availability", "uptime_pct")),
        }
        if any(value is not None for key, value in point.items() if key != "timestamp"):
            points.append(point)

    for metric in ("latency_ms", "packet_loss_pct", "jitter_ms", "utilization_pct", "availability_pct"):
        values = [point[metric] for point in points if point[metric] is not None]
        if values:
            summary[metric] = {
                "current": values[-1],
                "average": round(sum(values) / len(values), 2),
                "maximum": max(values),
            }

    return {"summary": summary, "points": points, "raw": payload}


def _metric_records(payload: Any, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 7:
        return []
    metric_terms = (
        "latency", "rtt_latency_ms", "packet_loss", "loss_pct", "jitter",
        "utilization", "availability", "timestamp", "sample_time",
    )
    if isinstance(payload, list):
        result: list[dict[str, Any]] = []
        for item in payload:
            result.extend(_metric_records(item, depth + 1))
        return result
    if not isinstance(payload, dict):
        return []
    lowered = {str(key).lower() for key in payload}
    result = [payload] if any(any(term in key for term in metric_terms) for key in lowered) else []
    for value in payload.values():
        if isinstance(value, (dict, list)):
            result.extend(_metric_records(value, depth + 1))
    return result


def dashboard_summary(sites: list[dict[str, Any]], findings: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"healthy": 0, "degraded": 0, "critical": 0, "unknown": 0}
    for site in sites:
        counts[site.get("status", "unknown")] = counts.get(site.get("status", "unknown"), 0) + 1

    active = [finding for finding in findings if finding.get("status") not in ("resolved", "closed", "cleared")]
    return {
        "sites_total": len(sites),
        "sites_healthy": counts.get("healthy", 0),
        "sites_degraded": counts.get("degraded", 0),
        "sites_critical": counts.get("critical", 0),
        "sites_unknown": counts.get("unknown", 0),
        "active_findings": len(active),
        "critical_findings": sum(finding.get("severity") == "critical" for finding in active),
        "high_findings": sum(finding.get("severity") == "high" for finding in active),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        return round(float(value), 3) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
