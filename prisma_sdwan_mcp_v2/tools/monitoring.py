from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from ..mcp import READ_ONLY, mcp
from ..response import collection_json, error_json, single_json
from .common import execute, fail_from_upstream, handle_error, records, resolve, site_element

MonitoringOperation = Literal[
    "events",
    "alarms",
    "flows",
    "link_metrics",
    "probe_metrics",
    "aiops_health",
    "aiops_anomaly",
    "aiops_forecast",
    "aiops_aggregates",
    "system_metrics",
    "qos_metrics",
    "bandwidth_stats",
]

TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.000Z"
RELATIVE_HOURS_CAP = 168
FLOW_SAMPLE_CAP = 500
TOP_TALKERS_LIMIT = 10
LQM_INTERVAL = "5min"

LQM_METRICS = [
    {"name": "LqmLatencyPointMetric", "unit": "milliseconds", "statistics": ["AVG"]},
    {"name": "LqmPktLossPointMetric", "unit": "percentage", "statistics": ["AVG"]},
    {"name": "LqmJitterPointMetric", "unit": "milliseconds", "statistics": ["AVG"]},
    {"name": "LqmMosPointMetric", "unit": "count", "statistics": ["AVG", "MIN", "MAX"]},
]
PROBE_METRICS = [
    {"name": "ProbeLatencyPointMetric", "unit": "milliseconds", "statistics": ["AVG", "MIN", "MAX"]},
    {"name": "ProbeJitterPointMetric", "unit": "milliseconds", "statistics": ["AVG", "MIN", "MAX"]},
    {"name": "ProbePktLossPointMetric", "unit": "percentage", "statistics": ["AVG", "MIN", "MAX"]},
]


def _parse_iso(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _window(hours: float, start_time: str | None, end_time: str | None) -> tuple[str, str, dict[str, str]]:
    if start_time is None and end_time is None:
        if isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours <= 0 or hours > RELATIVE_HOURS_CAP:
            raise ValueError(f"hours must be greater than 0 and no more than {RELATIVE_HOURS_CAP}")
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=float(hours))
        source = "relative_hours"
    else:
        if start_time is None or end_time is None:
            raise ValueError("start_time and end_time must both be supplied")
        start = _parse_iso(start_time)
        end = _parse_iso(end_time)
        if start is None or end is None:
            raise ValueError("start_time/end_time must be ISO 8601 timestamps")
        if start >= end:
            raise ValueError("start_time must be earlier than end_time")
        source = "explicit"
    start_s = start.strftime(TIME_FORMAT)
    end_s = end.strftime(TIME_FORMAT)
    return start_s, end_s, {"start_time": start_s, "end_time": end_s, "source": source}


def _event_payload(
    severity_default: list[str],
    limit: int,
    site_id: str | None,
    element_id: str | None,
    severity: str | None,
    start_time: str | None,
    end_time: str | None,
) -> dict[str, Any]:
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    payload: dict[str, Any] = {
        "severity": severity_default,
        "limit": {"count": limit, "sort_on": "time", "sort_order": "descending"},
    }
    query: dict[str, Any] = {}
    if site_id:
        query["site"] = [site_id]
    if element_id:
        query["element"] = [element_id]
    if query:
        payload["query"] = query
    if severity:
        values = [x.strip() for x in severity.split(",") if x.strip()]
        if not values:
            raise ValueError("severity cannot be empty")
        payload["severity"] = values
    if start_time:
        payload["start_time"] = start_time
    if end_time:
        payload["end_time"] = end_time
    return payload


def _flow_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        flows = data.get("flows")
        if isinstance(flows, dict) and isinstance(flows.get("items"), list):
            return [x for x in flows["items"] if isinstance(x, dict)]
        if isinstance(data.get("items"), list):
            return [x for x in data["items"] if isinstance(x, dict)]
    return []


def _flow_digest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_app: Counter[str] = Counter()
    by_path: Counter[str] = Counter()
    by_action: Counter[str] = Counter()
    talkers: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        by_app[str(row.get("app_id") or row.get("fc_app_id") or "unknown")] += 1
        by_path[str(row.get("path_id") or "unknown")] += 1
        by_action[str(row.get("flow_action") or "unknown")] += 1
        src = str(row.get("src_ip") or row.get("source_ip") or "unknown")
        dst = str(row.get("dst_ip") or row.get("destination_ip") or "unknown")
        try:
            c2s = int(row.get("bytes_c2s") or 0)
            s2c = int(row.get("bytes_s2c") or 0)
        except (TypeError, ValueError):
            c2s = s2c = 0
        entry = talkers.setdefault((src, dst), {"src_ip": src, "dst_ip": dst, "bytes_c2s": 0, "bytes_s2c": 0, "total_bytes": 0})
        entry["bytes_c2s"] += c2s
        entry["bytes_s2c"] += s2c
        entry["total_bytes"] += c2s + s2c
    return {
        "sample_count": len(rows),
        "by_app": dict(by_app.most_common()),
        "by_path": dict(by_path.most_common()),
        "by_action": dict(by_action.most_common()),
        "top_talkers": sorted(talkers.values(), key=lambda x: x["total_bytes"], reverse=True)[:TOP_TALKERS_LIMIT],
    }


def _metric_series(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return records(data)
    out: list[dict[str, Any]] = []
    for metric in data.get("metrics") or []:
        if not isinstance(metric, dict):
            continue
        for series in metric.get("series") or []:
            if not isinstance(series, dict):
                continue
            datapoints = []
            for block in series.get("data") or []:
                if isinstance(block, dict):
                    datapoints.extend(block.get("datapoints") or [])
            identity = {k: series[k] for k in ("wan_interface_id", "waninterface_id", "path_id", "element_id", "site_id", "name") if series.get(k) is not None}
            out.append({"metric": metric.get("name"), **identity, "datapoints": datapoints})
    return out or records(data)


def _pivot_lqm(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return records(data)
    paths: dict[str, dict[str, Any]] = {}
    for metric in data.get("metrics") or []:
        if not isinstance(metric, dict):
            continue
        metric_name = metric.get("name")
        for site in metric.get("sites") or []:
            if not isinstance(site, dict):
                continue
            for path in site.get("paths") or []:
                if not isinstance(path, dict) or path.get("path_id") is None:
                    continue
                key = str(path["path_id"])
                entry = paths.setdefault(key, {"path_id": path["path_id"], "remote_site_id": path.get("remote_site_id")})
                entry[str(metric_name)] = path.get("data")
    return list(paths.values())


def _pivot_probe(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return records(data)
    probes: dict[tuple[str, str, str], dict[str, Any]] = {}
    for metric in data.get("metrics") or []:
        if not isinstance(metric, dict):
            continue
        metric_name = str(metric.get("name"))
        for site in metric.get("sites") or []:
            if not isinstance(site, dict):
                continue
            for path in site.get("wn_paths") or []:
                if not isinstance(path, dict):
                    continue
                for point in path.get("datapoints") or []:
                    if not isinstance(point, dict):
                        continue
                    path_id = point.get("path_id")
                    probe_id = point.get("probe_config_id")
                    if path_id is None or probe_id is None:
                        continue
                    endpoint = str(point.get("endpoint_ipv4") or point.get("endpoint_fqdn") or "unknown")
                    key = (str(path_id), str(probe_id), endpoint)
                    entry = probes.setdefault(key, {"path_id": path_id, "probe_config_id": probe_id, "endpoint_ipv4": point.get("endpoint_ipv4"), "endpoint_fqdn": point.get("endpoint_fqdn"), "protocol": point.get("protocol")})
                    entry[metric_name] = point.get("data")
    return list(probes.values())


@mcp.tool(annotations=READ_ONLY)
def get_monitoring(
    operation: MonitoringOperation,
    site: Optional[str] = None,
    element: Optional[str] = None,
    hours: float = 1,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    severity: Optional[str] = None,
    raw: bool = False,
    limit: int = 50,
    cursor: Optional[str] = None,
    app: Optional[str] = None,
    path_id: Optional[str] = None,
    waninterface_id: Optional[str] = None,
) -> str:
    """Unified operational monitoring for incidents, flows, metrics, and AIOps.

    Events/alarms preserve v1's warning: an unwindowed call only sees the most
    recent records and may miss an older incident. Use ``start_time`` and
    ``end_time`` for incident analysis. Flow digest mode summarizes application,
    path, action, and top talkers; ``raw=true`` returns records. Link/probe
    metrics are recorded telemetry, not an active ping test.
    """
    tool = "get_monitoring"
    try:
        site_id, element_id, _ = site_element(site, element) if (site or element) else (None, None, None)
        if operation in {"events", "alarms"}:
            defaults = ["major", "critical"] if operation == "alarms" else ["critical", "major", "minor"]
            payload = _event_payload(defaults, min(limit, 100), site_id, element_id, severity, start_time, end_time)
            data = execute("compat.events_query", body=payload)
            upstream = fail_from_upstream(tool, data)
            if upstream:
                return upstream
            items = records(data)
            return collection_json(tool, f"Recent {operation}; use an explicit time window for incident investigation", operation, items, cursor=cursor, limit=min(limit, 100), extra={"site_id": site_id, "element_id": element_id, "windowed": bool(start_time and end_time)})

        if operation == "flows":
            if not site_id:
                return error_json("invalid_argument", "site is required for flows", tool, 400)
            start, end, window = _window(hours, start_time, end_time)
            filters: dict[str, Any] = {"site": [site_id]}
            if element_id:
                filters["element"] = [element_id]
            if app:
                filters["app"] = [app.strip()]
            if path_id:
                filters["path"] = [path_id.strip()]
            if waninterface_id:
                filters["wan_interface"] = [waninterface_id.strip()]
            request_limit = min(limit if raw else FLOW_SAMPLE_CAP, FLOW_SAMPLE_CAP)
            data = execute("compat.monitor_flows", body={"start_time": start, "end_time": end, "filter": filters, "debug_level": "all", "page_size": request_limit, "dest_page": 1})
            upstream = fail_from_upstream(tool, data)
            if upstream:
                return upstream
            rows = _flow_items(data)
            if raw:
                return collection_json(tool, f"Raw flows for site '{site_id}'", "flows", rows, cursor=cursor, limit=min(limit, 200), extra={"window": window, "filters": filters})
            digest = _flow_digest(rows)
            digest["complete"] = len(rows) < request_limit
            if not digest["complete"]:
                digest["warning"] = "digest is based on a capped sample, not the full window"
            return single_json(tool, f"Flow digest for site '{site_id}'", "digest", digest, extra={"window": window, "filters": filters})

        if operation in {"link_metrics", "probe_metrics"}:
            if not site_id:
                return error_json("invalid_argument", "site is required for metric operations", tool, 400)
            start, end, window = _window(hours, start_time, end_time)
            if operation == "link_metrics":
                filters: dict[str, Any] = {"site": [site_id]}
                if element_id:
                    filters["element"] = [element_id]
                bandwidth = execute("compat.monitor_metrics", body={"start_time": start, "end_time": end, "interval": LQM_INTERVAL, "metrics": [{"name": "BandwidthUsage", "statistics": ["average"], "unit": "Mbps"}], "filter": filters})
                lqm = execute("compat.monitor_lqm_point_metrics", body={"start_time": end, "interval": LQM_INTERVAL, "metrics": LQM_METRICS, "filter": {"site": [site_id]}})
                result = {"bandwidth": _metric_series(bandwidth), "link_quality": _metric_series(lqm) if raw else _pivot_lqm(lqm), "window": window, "snapshot_time": end, "recorded_telemetry": True}
                return single_json(tool, f"Recorded link metrics for site '{site_id}'", "metrics", result)
            probe = execute("compat.monitor_probe_point_metrics", body={"start_time": end, "interval": LQM_INTERVAL, "metrics": PROBE_METRICS, "filter": {"site": [site_id]}})
            upstream = fail_from_upstream(tool, probe)
            if upstream:
                return upstream
            result = _metric_series(probe) if raw else _pivot_probe(probe)
            return collection_json(tool, f"Recorded probe metrics for site '{site_id}'", "probes", result, cursor=cursor, limit=limit, extra={"window": window, "snapshot_time": end, "recorded_telemetry": True})

        action = {
            "aiops_health": "monitoring_aiops.monitor_aiops_health",
            "aiops_anomaly": "monitoring_aiops.monitor_aiops_anomaly",
            "aiops_forecast": "monitoring_aiops.monitor_aiops_forecast",
            "aiops_aggregates": "monitoring_aiops.monitor_aiops_aggregates",
            "system_metrics": "monitoring_aiops.monitor_sys_metrics",
            "qos_metrics": "monitoring_aiops.monitor_qos_metrics",
            "bandwidth_stats": "monitoring_aiops.monitor_agg_bw_stats",
        }[operation]
        data = execute(action)
        upstream = fail_from_upstream(tool, data)
        if upstream:
            return upstream
        rows = records(data)
        if rows:
            return collection_json(tool, f"Monitoring operation '{operation}'", "items", rows, cursor=cursor, limit=limit)
        return single_json(tool, f"Monitoring operation '{operation}'", "result", data)
    except ValueError as exc:
        return error_json("invalid_argument", str(exc), tool, 400)
    except Exception as exc:
        return handle_error(tool, exc)
