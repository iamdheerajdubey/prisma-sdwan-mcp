from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import registry
from ..formatting import (
    build_envelope,
    collection_response,
    error_json,
    internal_error,
    monitor_body,
    monitor_metrics_body,
    single_response,
)
from ..limits import (
    ALARM_LIMIT_CAP,
    EVENT_LIMIT_CAP,
    FLOW_DIGEST_SAMPLE_CAP,
    RAW_FLOW_LIMIT_CAP,
    RELATIVE_HOURS_CAP,
    TOP_TALKERS_LIMIT,
    applied_limit,
)


mcp = registry.mcp
LQM_INTERVAL = "5min"
LINK_METRICS = [
    {
        "name": "BandwidthUsage",
        "unit": "Mbps",
        "statistics": ["average"],
        "output_key": "utilization",
    }
]
LQM_METRICS = [
    {
        "name": "LqmLatencyPointMetric",
        "unit": "milliseconds",
        "statistics": ["AVG"],
        "output_key": "latency_ms",
        "fields": ["rtt_latency", "sample_completeness"],
    },
    {
        "name": "LqmPktLossPointMetric",
        "unit": "percentage",
        "statistics": ["AVG"],
        "output_key": "packet_loss_pct",
        "fields": [
            "downlink_pkt_loss_avg",
            "uplink_pkt_loss_avg",
            "sample_completeness",
        ],
    },
    {
        "name": "LqmJitterPointMetric",
        "unit": "milliseconds",
        "statistics": ["AVG"],
        "output_key": "jitter_ms",
        "fields": [
            "downlink_jitter_avg",
            "uplink_jitter_avg",
            "sample_completeness",
        ],
    },
    {
        "name": "LqmMosPointMetric",
        "unit": "count",
        "statistics": ["AVG", "MIN", "MAX"],
        "output_key": "mos",
        "fields": [
            "downlink_mos_avg",
            "downlink_mos_min",
            "downlink_mos_max",
            "uplink_mos_avg",
            "uplink_mos_min",
            "uplink_mos_max",
            "sample_completeness",
        ],
    },
]
PROBE_METRICS = [
    {
        "name": "ProbeLatencyPointMetric",
        "unit": "milliseconds",
        "statistics": ["AVG", "MIN", "MAX"],
        "output_key": "latency_ms",
        "fields": ["latency_ms_min", "latency_ms_max", "latency_ms_avg"],
    },
    {
        "name": "ProbeJitterPointMetric",
        "unit": "milliseconds",
        "statistics": ["AVG", "MIN", "MAX"],
        "output_key": "jitter_ms",
        "fields": ["jitter_ms_min", "jitter_ms_max", "jitter_ms_avg"],
    },
    {
        "name": "ProbePktLossPointMetric",
        "unit": "percentage",
        "statistics": ["AVG", "MIN", "MAX"],
        "output_key": "packet_loss_pct",
        "fields": [
            "packet_loss_percent_min",
            "packet_loss_percent_max",
            "packet_loss_percent_avg",
        ],
    },
]


def _validate_limit(limit: int | None, tool: str) -> str | None:
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        return error_json("invalid_limit", "limit must be at least 1", tool, 400)
    return None


def _validate_hours(hours: int | float, tool: str) -> str | None:
    if (
        isinstance(hours, bool)
        or not isinstance(hours, (int, float))
        or hours <= 0
        or hours > RELATIVE_HOURS_CAP
    ):
        return error_json(
            "invalid_argument",
            f"hours must be greater than 0 and no more than {RELATIVE_HOURS_CAP}",
            tool,
            400,
        )
    return None


TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.000Z"


def _window(hours: int | float) -> tuple[str, str, int]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    interval = max(60, int(hours * 3600 / 60))
    return start.strftime(TIME_FORMAT), end.strftime(TIME_FORMAT), interval


def _parse_iso(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_window(
    hours: int | float,
    start_time: Optional[str],
    end_time: Optional[str],
    tool: str,
) -> str | tuple[str, str, int, dict]:
    """Resolve an explicit window or fall back to the relative ``hours`` lookback.

    Returns ``(start, end, interval, window)`` or an error JSON string.
    """
    if start_time is None and end_time is None:
        invalid = _validate_hours(hours, tool)
        if invalid:
            return invalid
        start, end, interval = _window(hours)
        source = "relative_hours"
    else:
        if start_time is None or end_time is None:
            return error_json(
                "invalid_argument",
                "start_time and end_time must both be provided when either is used",
                tool,
                400,
            )
        parsed_start = _parse_iso(start_time)
        parsed_end = _parse_iso(end_time)
        for label, parsed in (("start_time", parsed_start), ("end_time", parsed_end)):
            if parsed is None:
                return error_json(
                    "invalid_argument",
                    f"{label} must be a parseable ISO 8601 timestamp",
                    tool,
                    400,
                )
        if parsed_start >= parsed_end:
            return error_json("invalid_argument", "start_time must be earlier than end_time", tool, 400)
        start = parsed_start.strftime(TIME_FORMAT)
        end = parsed_end.strftime(TIME_FORMAT)
        interval = max(60, int((parsed_end - parsed_start).total_seconds() / 60))
        source = "explicit"
    return start, end, interval, {"start_time": start, "end_time": end, "source": source}


def _window_phrase(hours: int | float, window: dict) -> str:
    if window["source"] == "explicit":
        return f"from {window['start_time']} to {window['end_time']}"
    return f"over the last {hours} hour(s)"


def _items(data):
    if data is None or data == {}:
        return []
    return data if isinstance(data, list) else [data]


def _interface_id(item: dict) -> str | None:
    for field in ("id", "interface_id", "interfaceId"):
        if item.get(field) is not None:
            return str(item[field])
    return None


def _metric_series(data):
    if not isinstance(data, dict):
        return _items(data)
    series_out = []
    for metric in data.get("metrics", []) or []:
        for series in metric.get("series", []) or []:
            datapoints = []
            for series_data in series.get("data", []) or []:
                datapoints.extend(series_data.get("datapoints", []) or [])
            identity = {
                key: series.get(key)
                for key in (
                    "wan_interface_id",
                    "waninterface_id",
                    "path_id",
                    "element_id",
                    "site_id",
                    "name",
                )
                if series.get(key) is not None
            }
            series_out.append(
                {
                    "metric": metric.get("name"),
                    **identity,
                    "datapoints": datapoints,
                }
            )
    return series_out or _items(data)


def _pivot_lqm_by_path(data: dict) -> list[dict]:
    paths = {}
    for metric in data.get("metrics", []) or []:
        definition = next(
            (item for item in LQM_METRICS if item["name"] == metric.get("name")),
            None,
        )
        if definition is None:
            continue
        for site in metric.get("sites", []) or []:
            for path in site.get("paths", []) or []:
                path_id = path.get("path_id")
                if path_id is None:
                    continue
                entry = paths.setdefault(
                    str(path_id),
                    {
                        "path_id": path_id,
                        "remote_site_id": path.get("remote_site_id"),
                    },
                )
                data_fields = path.get("data", {}) or {}
                entry[definition["output_key"]] = {
                    field: data_fields.get(field) for field in definition["fields"]
                }
    return list(paths.values())


def _pivot_probe_by_config(data: dict) -> list[dict]:
    probes = {}
    for metric in data.get("metrics", []) or []:
        definition = next(
            (item for item in PROBE_METRICS if item["name"] == metric.get("name")),
            None,
        )
        if definition is None:
            continue
        for site in metric.get("sites", []) or []:
            for wan_path in site.get("wn_paths", []) or []:
                for datapoint in wan_path.get("datapoints", []) or []:
                    probe_config_id = datapoint.get("probe_config_id")
                    path_id = datapoint.get("path_id")
                    if probe_config_id is None or path_id is None:
                        continue
                    key = (
                        str(path_id),
                        str(probe_config_id),
                        datapoint.get("endpoint_ipv4"),
                    )
                    entry = probes.setdefault(
                        key,
                        {
                            "path_id": path_id,
                            "probe_config_id": probe_config_id,
                            "endpoint_ipv4": datapoint.get("endpoint_ipv4"),
                            "endpoint_fqdn": datapoint.get("endpoint_fqdn"),
                            "protocol": datapoint.get("protocol"),
                        },
                    )
                    values = datapoint.get("data", {}) or {}
                    entry[definition["output_key"]] = {
                        field: values.get(field) for field in definition["fields"]
                    }
    return list(probes.values())


def _wan_interface_names(site_id: str) -> dict:
    try:
        data = registry.client.call_sdk(registry.client.sdk.get.waninterfaces, site_id)
        if isinstance(data, dict) and "error" in data:
            return {}
        items = _items(data)
        return {
            str(item.get("id")): item.get("name")
            for item in items
            if isinstance(item, dict) and item.get("id") is not None
        }
    except Exception:
        return {}


def _flow_items(data):
    if not isinstance(data, dict):
        return _items(data)
    flows = data.get("flows")
    if isinstance(flows, dict) and isinstance(flows.get("items"), list):
        return flows["items"]
    if isinstance(data.get("items"), list):
        return data["items"]
    return []


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_element_status(element_id: str) -> str:
    """Retrieve operational status for one element.

    Args:
        element_id: Element ID.

    Returns:
        A compact element status response.

    Examples:
        - get_element_status(element_id="elem456")
    """
    tool = "get_element_status"
    element_id = element_id.strip() if element_id else ""
    if not element_id:
        return error_json("invalid_argument", "element_id is required and cannot be empty", tool, 400)
    try:
        data = registry.client.call_sdk(registry.client.sdk.get.element_status, element_id)
        return single_response(tool, f"Operational status for element '{element_id}'", "element_status", data)
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_software_status(element_id: str) -> str:
    """Retrieve software status for one element.

    Args:
        element_id: Element ID.

    Returns:
        A compact software status response.

    Examples:
        - get_software_status(element_id="elem456")
    """
    tool = "get_software_status"
    element_id = element_id.strip() if element_id else ""
    if not element_id:
        return error_json("invalid_argument", "element_id is required and cannot be empty", tool, 400)
    try:
        data = registry.client.call_sdk(registry.client.sdk.get.software_status, element_id)
        return single_response(tool, f"Software status for element '{element_id}'", "software_status", data)
    except Exception as error:
        return internal_error(tool, error)


def _scoping_payload(
    tool: str,
    severities: list[str],
    capped: int,
    site_id: Optional[str],
    element_id: Optional[str],
    severity: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str],
    last: Optional[int],
) -> str | dict:
    if last is not None and (
        isinstance(last, bool)
        or not isinstance(last, int)
        or last < 1
        or last > EVENT_LIMIT_CAP
    ):
        return error_json(
            "invalid_argument",
            f"last must be between 1 and {EVENT_LIMIT_CAP}",
            tool,
            400,
        )
    payload: dict = {
        "severity": severities,
        "limit": {"count": capped, "sort_on": "time", "sort_order": "descending"},
    }
    query: dict = {}
    if site_id is not None:
        value = site_id.strip()
        if not value:
            return error_json("invalid_argument", "site_id cannot be empty", tool, 400)
        query["site"] = [value]
    if element_id is not None:
        value = element_id.strip()
        if not value:
            return error_json("invalid_argument", "element_id cannot be empty", tool, 400)
        query["element"] = [value]
    if severity is not None:
        parts = [part.strip() for part in severity.split(",")]
        parts = [part for part in parts if part]
        if not parts:
            return error_json("invalid_argument", "severity cannot be empty", tool, 400)
        payload["severity"] = parts
    if query:
        payload["query"] = query
    if start_time is not None:
        if not start_time.strip():
            return error_json("invalid_argument", "start_time cannot be empty", tool, 400)
        payload["start_time"] = start_time.strip()
    if end_time is not None:
        if not end_time.strip():
            return error_json("invalid_argument", "end_time cannot be empty", tool, 400)
        payload["end_time"] = end_time.strip()
    if last is not None:
        payload["limit"] = {"count": last, "sort_on": "time", "sort_order": "descending"}
    return payload


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_events(
    limit: int = 20,
    cursor: Optional[str] = None,
    site_id: Optional[str] = None,
    element_id: Optional[str] = None,
    severity: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    last: Optional[int] = None,
) -> str:
    """Fetch recent events, newest first, with optional scoping.

    Args:
        limit: Maximum number of events, from 1 to 100.
        cursor: Opaque cursor for a subsequent page.
        site_id: Scope to events for this site.
        element_id: Scope to events for this element.
        severity: Comma-separated severity values (defaults to
            critical, major, minor).
        start_time: ISO timestamp; earliest event time to include.
        end_time: ISO timestamp; latest event time to include.
        last: Override the requested event count (1 to 100).

    Returns:
        A compact, unprojected event collection. At the 40960-byte default, a
        live capture on 2026-08-02 fit 65 records on the first page and 35 on
        the second for 100 total records; record size varies by event. An
        unwindowed call only returns the most recent ``limit`` records and can
        miss an incident entirely if other events happened since — for
        incident investigation, pass start_time/end_time windowed tightly
        around the time of interest rather than relying on the default limit.

    Examples:
        - get_events()
        - get_events(limit=50)
        - get_events(site_id="site123", severity="critical")
    """
    tool = "get_events"
    if limit < 1:
        return error_json("invalid_limit", "limit must be at least 1", tool, 400)
    capped = min(limit, EVENT_LIMIT_CAP)
    payload = _scoping_payload(
        tool,
        ["critical", "major", "minor"],
        capped,
        site_id,
        element_id,
        severity,
        start_time,
        end_time,
        last,
    )
    if isinstance(payload, str):
        return payload
    try:
        data = registry.client.call_sdk_post(
            registry.client.sdk.post.events_query,
            payload,
        )
        return collection_response(
            tool,
            f"Recent events (up to {capped})",
            "events",
            data,
            cursor=cursor,
            limit=limit,
            extra=(
                {"limits_applied": [applied_limit("events_limit")]}
                if limit > EVENT_LIMIT_CAP and last is None
                else None
            ),
        )
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_alarms(
    limit: int = 20,
    cursor: Optional[str] = None,
    site_id: Optional[str] = None,
    element_id: Optional[str] = None,
    severity: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    last: Optional[int] = None,
) -> str:
    """Fetch recent major and critical alarms, newest first, with scoping.

    Args:
        limit: Maximum number of alarms, from 1 to 100.
        cursor: Opaque cursor for a subsequent page.
        site_id: Scope to alarms for this site.
        element_id: Scope to alarms for this element.
        severity: Comma-separated severity values (defaults to
            major, critical).
        start_time: ISO timestamp; earliest alarm time to include.
        end_time: ISO timestamp; latest alarm time to include.
        last: Override the requested alarm count (1 to 100).

    Returns:
        A compact, unprojected alarm collection. At the 40960-byte default, a
        live capture on 2026-08-02 fit 65 records on the first page and 35 on
        the second for 100 total records; record size varies by alarm. An
        unwindowed call only returns the most recent ``limit`` records and can
        miss an incident entirely — window start_time/end_time tightly around
        the time of interest. An alarm's ``cleared: false`` means it is still
        open as of this query.

    Examples:
        - get_alarms()
        - get_alarms(limit=50)
        - get_alarms(element_id="elem456", severity="critical")
    """
    tool = "get_alarms"
    if limit < 1:
        return error_json("invalid_limit", "limit must be at least 1", tool, 400)
    capped = min(limit, ALARM_LIMIT_CAP)
    payload = _scoping_payload(
        tool,
        ["major", "critical"],
        capped,
        site_id,
        element_id,
        severity,
        start_time,
        end_time,
        last,
    )
    if isinstance(payload, str):
        return payload
    try:
        data = registry.client.call_sdk_post(
            registry.client.sdk.post.events_query,
            payload,
        )
        return collection_response(
            tool,
            f"Recent alarms (up to {capped})",
            "alarms",
            data,
            cursor=cursor,
            limit=limit,
            extra=(
                {"limits_applied": [applied_limit("alarms_limit")]}
                if limit > ALARM_LIMIT_CAP and last is None
                else None
            ),
        )
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_interface_status(
    site_id: str,
    element_id: str,
    interface_id: Optional[str] = None,
) -> str:
    """Retrieve operational status for one or all interfaces on an element.

    Args:
        site_id: Site ID.
        element_id: Element ID.
        interface_id: Optional interface ID. Omit to fan out across all interfaces.

    Returns:
        Projected interface status records; individual failures remain inline.

    Examples:
        - get_interface_status(site_id="site123", element_id="elem456")
        - get_interface_status(site_id="site123", element_id="elem456", interface_id="if789")
    """
    tool = "get_interface_status"
    site_id = site_id.strip() if site_id else ""
    element_id = element_id.strip() if element_id else ""
    interface_id = interface_id.strip() if interface_id else None
    if not site_id:
        return error_json("invalid_argument", "site_id is required and cannot be empty", tool, 400)
    if not element_id:
        return error_json("invalid_argument", "element_id is required and cannot be empty", tool, 400)
    if interface_id is not None and not interface_id:
        return error_json("invalid_argument", "interface_id cannot be empty", tool, 400)
    try:
        if interface_id:
            data = registry.client.call_sdk(
                registry.client.sdk.get.interfaces_status,
                site_id,
                element_id,
                interface_id,
            )
            if isinstance(data, dict) and "error" in data:
                data = {"interface_id": interface_id, "error": data["error"]}
            elif isinstance(data, dict):
                data.setdefault("interface_id", interface_id)
            return collection_response(
                tool,
                f"Interface status for '{interface_id}'",
                "interfaces",
                [data],
            )

        interfaces = registry.client.call_sdk(registry.client.sdk.get.interfaces, site_id, element_id)
        if isinstance(interfaces, dict) and "error" in interfaces:
            return collection_response(tool, "Unable to enumerate interfaces", "interfaces", interfaces)
        records = []
        for interface in _items(interfaces):
            current_id = _interface_id(interface) if isinstance(interface, dict) else None
            if not current_id:
                records.append({"error": "interface record has no id", "interface": interface})
                continue
            status = registry.client.call_sdk(
                registry.client.sdk.get.interfaces_status,
                site_id,
                element_id,
                current_id,
            )
            if isinstance(status, dict) and "error" in status:
                records.append({"interface_id": current_id, "error": status["error"]})
            else:
                if isinstance(status, dict):
                    status.setdefault("interface_id", current_id)
                records.append(status)
        return collection_response(
            tool,
            f"Interface status for element '{element_id}'",
            "interfaces",
            records,
        )
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_flows(
    site_id: str,
    hours: int = 1,
    limit: int = 50,
    cursor: Optional[str] = None,
    raw: bool = False,
    page: Optional[int] = None,
    app: Optional[str] = None,
    element_id: Optional[str] = None,
    path_id: Optional[str] = None,
    waninterface_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> str:
    """Retrieve flow records or a summary digest for a site and time window.

    By default returns a summary digest: total matched, breakdown by
    application/path/action, and top 10 talkers by bytes. The action
    breakdown always shows every distinct ``flow_action`` value, even
    unrecognized literals — a flow is never mislabeled as blocked.
    Pass ``raw=True`` with ``page``/``limit`` for drilled individual
    records. ``app``/``element_id``/``path_id``/``waninterface_id`` are
    server-side filters applied in the request payload.

    Args:
        site_id: Site ID.
        hours: Lookback window in hours, from 0 to 168.
        limit: Maximum raw flow records to return (default 50, max 200).
        cursor: Opaque cursor for a subsequent raw page.
        raw: When True, return individual flow records instead of a digest.
        page: Requested page number for the server-side page (raw mode).
        app: Application ID filter, applied server-side.
        element_id: Element ID filter, applied server-side.
        path_id: Path ID filter, applied server-side.
        waninterface_id: WAN interface ID filter, applied server-side.
        start_time: ISO 8601 start of an exact window. Must be given with
            end_time; takes precedence over ``hours``. The 168-hour ceiling
            does not apply to an explicit window — controller retention is
            the only limit.
        end_time: ISO 8601 end of an exact window. Must be given with
            start_time.

    Returns:
        A summary digest (default) or a compact, budget-capped raw flow
        collection. At the 40960-byte default, a live 200-record sample on
        2026-08-02 fit 14-20 unprojected records per cursor page and completed
        in 13 pages; record shape changes the capacity. The resolved window is
        echoed back under ``window``.
        In digest mode ``digest_complete``/``digest_sample_size``/
        ``digest_sample_limit`` state whether the figures cover the whole
        window or only a truncated sample.

    Examples:
        - get_flows(site_id="site123")
        - get_flows(site_id="site123", start_time="2026-07-30T01:00:00Z", end_time="2026-07-30T03:00:00Z")
        - get_flows(site_id="site123", app="app456")
        - get_flows(site_id="site123", raw=True, limit=50)
        - get_flows(site_id="site123", raw=True, page=2, limit=50)
    """
    tool = "get_flows"
    site_id = site_id.strip() if site_id else ""
    if not site_id:
        return error_json("invalid_argument", "site_id is required and cannot be empty", tool, 400)
    resolved = _resolve_window(hours, start_time, end_time, tool)
    if isinstance(resolved, str):
        return resolved
    start, end, _, window = resolved
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit < 1
        or limit > RAW_FLOW_LIMIT_CAP
    ):
        return error_json(
            "invalid_limit",
            f"limit must be between 1 and {RAW_FLOW_LIMIT_CAP}",
            tool,
            400,
        )
    if page is not None and (isinstance(page, bool) or not isinstance(page, int) or page < 1):
        return error_json("invalid_argument", "page must be a positive integer", tool, 400)
    filters = {"site": [site_id]}
    for arg, key in (
        (app, "app"),
        (element_id, "element"),
        (path_id, "path"),
        (waninterface_id, "wan_interface"),
    ):
        if arg is not None:
            value = arg.strip()
            if not value:
                return error_json("invalid_argument", f"{key} filter cannot be empty", tool, 400)
            filters[key] = [value]
    dest_page = page if page is not None else 1
    request_limit = FLOW_DIGEST_SAMPLE_CAP if not raw else limit
    try:
        data = registry.client.call_sdk_post(
            registry.client.sdk.post.monitor_flows,
            {
                "start_time": start,
                "end_time": end,
                "filter": filters,
                "debug_level": "all",
                "page_size": request_limit,
                "dest_page": dest_page,
            },
        )
        if isinstance(data, dict) and "error" in data:
            return collection_response(
                tool,
                f"Flows unavailable for site '{site_id}'",
                "flows",
                data,
            )
        flow_records = _flow_items(data)
        phrase = _window_phrase(hours, window)
        if not raw:
            return _flow_digest_response(tool, site_id, phrase, flow_records, request_limit, window)
        return collection_response(
            tool,
            f"Flows for site '{site_id}' {phrase}",
            "flows",
            flow_records,
            cursor=cursor,
            limit=limit,
            extra={"raw": True, "page": dest_page, "window": window},
        )
    except Exception as error:
        return internal_error(tool, error)


def _flow_digest_response(
    tool: str,
    site_id: str,
    phrase: str,
    records: list,
    fetched: int,
    window: dict,
) -> str:
    by_app = Counter()
    by_path = Counter()
    by_action = Counter()
    talkers = {}
    sample_size = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        sample_size += 1
        by_app[str(record.get("app_id") or record.get("fc_app_id") or "unknown")] += 1
        by_path[str(record.get("path_id") or "unknown")] += 1
        by_action[str(record.get("flow_action") or "unknown")] += 1
        src = record.get("src_ip") or record.get("source_ip") or "unknown"
        dst = record.get("dst_ip") or record.get("destination_ip") or "unknown"
        key = (str(src), str(dst))
        c2s = record.get("bytes_c2s") or 0
        s2c = record.get("bytes_s2c") or 0
        try:
            c2s = int(c2s)
            s2c = int(s2c)
        except (TypeError, ValueError):
            c2s = 0
            s2c = 0
        entry = talkers.setdefault(key, {"src_ip": key[0], "dst_ip": key[1], "bytes_c2s": 0, "bytes_s2c": 0, "total_bytes": 0})
        entry["bytes_c2s"] += c2s
        entry["bytes_s2c"] += s2c
        entry["total_bytes"] += c2s + s2c
    top_talkers = sorted(
        talkers.values(), key=lambda item: item["total_bytes"], reverse=True
    )[:TOP_TALKERS_LIMIT]
    digest = {
        "total": len(records),
        "by_app": dict(sorted(by_app.items(), key=lambda pair: pair[1], reverse=True)),
        "by_path": dict(sorted(by_path.items(), key=lambda pair: pair[1], reverse=True)),
        "by_action": dict(sorted(by_action.items(), key=lambda pair: pair[1], reverse=True)),
        "top_talkers": top_talkers,
        "top_talkers_limit": TOP_TALKERS_LIMIT,
    }
    complete = len(records) < fetched
    limits_applied = []
    if not complete:
        limits_applied.append(applied_limit("flow_digest_sample"))
    if len(talkers) > TOP_TALKERS_LIMIT:
        limits_applied.append(applied_limit("top_talkers"))
    extra = {
        "digest_mode": True,
        "digest": digest,
        "digest_complete": complete,
        "digest_sample_size": sample_size,
        "digest_sample_limit": fetched,
        "window": window,
    }
    if limits_applied:
        extra["limits_applied"] = limits_applied
    summary = f"Flow digest for site '{site_id}' {phrase}: {len(records)} flow(s)"
    if not complete:
        extra["digest_more_pages"] = True
        summary += (
            f". Truncated sample: the fetch returned the maximum {fetched} flow(s), so total,"
            " by_app, by_path, by_action and the top_talkers ranking are computed from those"
            f" {sample_size} flow(s) only and are not totals for the window"
        )
    return build_envelope(
        tool,
        summary,
        "flows",
        [],
        extra=extra,
    )


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_link_metrics(
    site_id: str,
    hours: int = 1,
    element_id: Optional[str] = None,
    raw: bool = False,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> str:
    """Retrieve bandwidth and link-quality metrics for a site.

    Args:
        site_id: Site ID.
        hours: Lookback window in hours.
        element_id: Scope bandwidth utilization to this element (the
            link-quality endpoint rejects element filters and stays
            site-wide).
        raw: When True, return raw per-series datapoints for the
            link-quality metrics (capped to the response budget) instead
            of the pivoted snapshots.
        start_time: ISO 8601 start of an exact window. Must be given with
            end_time; takes precedence over ``hours``. The 168-hour ceiling
            does not apply to an explicit window — controller retention is
            the only limit.
        end_time: ISO 8601 end of an exact window. Must be given with
            start_time. The link-quality snapshot is anchored at this time.

    Returns:
        Bandwidth series and per-WAN link-quality snapshots. This is
        continuous background LQM telemetry the controller already
        recorded, not a live test — for "is it still bad right now" on one
        specific interface, or a target not covered by LQM/probes, use
        cli-mcp's ``ping``/``tcpping`` instead (if deployed alongside this
        server). Cross-check against get_probe_metrics, which measures
        different configured targets and can corroborate or contradict this.

    Examples:
        - get_link_metrics(site_id="site123")
        - get_link_metrics(site_id="site123", element_id="elem456")
        - get_link_metrics(site_id="site123", raw=True)
    """
    tool = "get_link_metrics"
    site_id = site_id.strip() if site_id else ""
    if not site_id:
        return error_json("invalid_argument", "site_id is required and cannot be empty", tool, 400)
    resolved = _resolve_window(hours, start_time, end_time, tool)
    if isinstance(resolved, str):
        return resolved
    start, end, _, window = resolved
    element_value = None
    if element_id is not None:
        element_value = element_id.strip()
        if not element_value:
            return error_json("invalid_argument", "element_id cannot be empty", tool, 400)
    bandwidth_filter = {"site": [site_id]}
    if element_value:
        bandwidth_filter["element"] = [element_value]
    errors = {}
    try:
        bandwidth_result = registry.client.call_sdk_post(
            registry.client.sdk.post.monitor_metrics,
            monitor_metrics_body(
                start,
                end,
                [
                    {
                        "name": LINK_METRICS[0]["name"],
                        "statistics": LINK_METRICS[0]["statistics"],
                        "unit": LINK_METRICS[0]["unit"],
                    }
                ],
                bandwidth_filter,
            ),
        )
        if isinstance(bandwidth_result, dict) and "error" in bandwidth_result:
            errors["bandwidth"] = bandwidth_result
            bandwidth_items = []
        else:
            bandwidth_items = _metric_series(bandwidth_result)

        lqm_result = registry.client.call_sdk_post(
            registry.client.sdk.post.monitor_lqm_point_metrics,
            monitor_body(
                end,
                LQM_INTERVAL,
                [
                    {
                        "name": metric["name"],
                        "unit": metric["unit"],
                        "statistics": metric["statistics"],
                    }
                    for metric in LQM_METRICS
                ],
                {"site": [site_id]},
            ),
        )
        if isinstance(lqm_result, dict) and "error" in lqm_result:
            errors["link_quality"] = lqm_result
            link_quality = []
        else:
            if raw:
                link_quality = _metric_series(lqm_result)
            else:
                link_quality = _pivot_lqm_by_path(lqm_result)
                wan_names = _wan_interface_names(site_id)
                for entry in link_quality:
                    path_id = str(entry.get("path_id"))
                    if path_id in wan_names:
                        entry["wan_interface_id"] = entry["path_id"]
                        entry["wan_interface_name"] = wan_names[path_id]

        return build_envelope(
            tool,
            f"Link metrics for site '{site_id}' {_window_phrase(hours, window)}",
            "bandwidth",
            bandwidth_items,
            extra={
                "link_quality": link_quality,
                "window": window,
                "snapshot_time": end,
                "interval": LQM_INTERVAL,
                "raw_datapoints": raw,
                "errors": errors or None,
            },
        )
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_probe_metrics(
    site_id: str,
    hours: int = 1,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> str:
    """Retrieve synthetic endpoint-probe metrics for a site.

    Args:
        site_id: Site ID.
        hours: Lookback window in hours.
        start_time: ISO 8601 start of an exact window. Must be given with
            end_time; takes precedence over ``hours``. The 168-hour ceiling
            does not apply to an explicit window — controller retention is
            the only limit.
        end_time: ISO 8601 end of an exact window. Must be given with
            start_time. The probe snapshot is anchored at this time.

    Returns:
        Probe latency, jitter, and packet-loss snapshots, or an explanatory
        empty result when no probes are configured. Probes only cover their
        pre-configured targets — for an arbitrary destination, or to confirm
        a symptom is happening right now on one interface, use cli-mcp's
        ``ping``/``tcpping``/``dig`` instead (if deployed alongside this
        server). Cross-check against get_link_metrics, which measures the
        underlying WAN path itself rather than a configured target.

    Examples:
        - get_probe_metrics(site_id="site123")
    """
    tool = "get_probe_metrics"
    site_id = site_id.strip() if site_id else ""
    if not site_id:
        return error_json("invalid_argument", "site_id is required and cannot be empty", tool, 400)
    resolved = _resolve_window(hours, start_time, end_time, tool)
    if isinstance(resolved, str):
        return resolved
    _, end, _, window = resolved
    try:
        probe_result = registry.client.call_sdk_post(
            registry.client.sdk.post.monitor_probe_point_metrics,
            monitor_body(
                end,
                LQM_INTERVAL,
                [
                    {
                        "name": metric["name"],
                        "unit": metric["unit"],
                        "statistics": metric["statistics"],
                    }
                    for metric in PROBE_METRICS
                ],
                {"site": [site_id]},
            ),
        )
        if isinstance(probe_result, dict) and "error" in probe_result:
            return build_envelope(
                tool,
                f"Probe metrics unavailable for site '{site_id}'",
                "probes",
                [],
                extra={
                    "window": window,
                    "snapshot_time": end,
                    "interval": LQM_INTERVAL,
                    "errors": {"probes": probe_result},
                },
            )
        probes = _pivot_probe_by_config(probe_result)
        summary = (
            f"No probes configured for site '{site_id}'"
            if not probes
            else f"Found {len(probes)} probe measurement series for site '{site_id}'"
        )
        return build_envelope(
            tool,
            summary,
            "probes",
            probes,
            extra={"window": window, "snapshot_time": end, "interval": LQM_INTERVAL},
        )
    except Exception as error:
        return internal_error(tool, error)
