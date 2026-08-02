import base64
import binascii
import json
import logging
from typing import Any, Callable, Iterable

from .config import get_max_response_bytes


LOGGER = logging.getLogger(__name__)


ELEMENT_KEEP_FIELDS = {
    "id",
    "name",
    "description",
    "site_id",
    "serial_number",
    "hw_id",
    "model_name",
    "software_version",
    "role",
    "state",
    "connected",
    "spoke_ha_config",
}
SITE_KEEP_FIELDS = {
    "id",
    "name",
    "description",
    "admin_state",
    "element_cluster_role",
    "city",
    "country",
    "latitude",
    "longitude",
}
MACHINE_KEEP_FIELDS = {
    "id",
    "hw_id",
    "sl_no",
    "model_name",
    "image_version",
    "machine_state",
    "ship_state",
    "suspend_state",
    "connected",
    "em_element_id",
    "tenant_id",
}
INTERFACE_KEEP_FIELDS = {
    "id",
    "name",
    "interface_id",
    "interface_name",
    "type",
    "state",
    "status",
    "ip_address",
    "mac_address",
    "element_id",
    "site_id",
    "admin_up",
}
INTERFACE_STATUS_KEEP_FIELDS = INTERFACE_KEEP_FIELDS | {
    "operational_status",
    "link_state",
    "last_change",
    "reason",
    "health",
    "interface_status",
}
WAN_INTERFACE_KEEP_FIELDS = {
    "id",
    "name",
    "network_id",
    "type",
    "cost",
    "bfd_mode",
    "bwc_enabled",
    "bw_config_mode",
    "lqm_enabled",
    "link_bw_up",
    "link_bw_down",
    "label_id",
}
EVENT_KEEP_FIELDS = {
    "id",
    "event_id",
    "time",
    "timestamp",
    "severity",
    "type",
    "category",
    "message",
    "site_id",
    "element_id",
    "standing",
    "cleared",
    "correlation_id",
    "priority",
}
FLOW_KEEP_FIELDS = {
    "id",
    "flow_id",
    "source_ip",
    "destination_ip",
    "source_port",
    "destination_port",
    "src_ip",
    "dst_ip",
    "src_port",
    "dst_port",
    "protocol",
    "flow_start_time_ms",
    "flow_end_time_ms",
    "app_id",
    "fc_app_id",
    "path_id",
    "path_type",
    "element_id",
    "waninterface_id",
    "flow_direction",
    "flow_action",
    "network_policy_id",
    "network_policy_set_id",
    "priority_policy_id",
    "priority_policy_set_id",
    "sec_policy_actions",
    "is_sec_policy_present",
    "bytes_c2s",
    "bytes_s2c",
    "packets_c2s",
    "packets_s2c",
    "average_rtt",
    "avg_jitter_c2s",
    "avg_packet_loss_c2s",
    "avg_mos_c2s",
    "retransmit_bytes_c2s",
    "retransmit_bytes_s2c",
    "retransmit_pkts_c2s",
    "retransmit_pkts_s2c",
    "reset_c2s",
    "reset_s2c",
    "syn_c2s",
    "syn_s2c",
    "fin_c2s",
    "fin_s2c",
    "application",
    "app_name",
    "bytes",
    "packets",
    "start_time",
    "end_time",
    "site_id",
}


def _clean_response(data):
    """Strip internal metadata (_-prefixed fields) and null values."""
    if isinstance(data, dict):
        return {
            key: _clean_response(value)
            for key, value in data.items()
            if value is not None and not key.startswith("_")
        }
    if isinstance(data, list):
        return [_clean_response(item) for item in data]
    return data


def _extract_response(resp):
    """Extract data from an SDK response object."""
    try:
        if not resp.cgx_status:
            errors = (
                resp.cgx_content.get("_error", [{}])
                if isinstance(resp.cgx_content, dict)
                else [{}]
            )
            message = (
                errors[0].get("message", "Unknown error")
                if errors
                else "Unknown error"
            )
            if message == "Unknown error":
                status_messages = {
                    400: "Bad request",
                    401: "Authentication failed",
                    403: "Permission denied",
                    404: "Resource not found",
                    429: "Rate limit exceeded",
                    500: "Internal server error",
                }
                message = status_messages.get(
                    resp.status_code, f"HTTP {resp.status_code} error"
                )
            return {"error": message, "status_code": resp.status_code}
        data = resp.cgx_content
        if isinstance(data, dict) and "items" in data:
            return _clean_response(data["items"])
        return _clean_response(data)
    except Exception as error:
        return {"error": f"Response parsing error: {str(error)}"}


def compact_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def dumps(data: Any) -> str:
    return compact_json(data)


def as_items(data):
    return data if isinstance(data, list) else [data]


def structured_error(
    code: str,
    message: str,
    tool: str,
    status_code: int | None = None,
) -> dict:
    result = {"code": code, "message": message, "tool": tool}
    if status_code is not None:
        result["status_code"] = status_code
    return result


def error_json(
    code: str,
    message: str,
    tool: str,
    status_code: int | None = None,
) -> str:
    return compact_json(structured_error(code, message, tool, status_code))


def internal_error(tool: str, error: Exception) -> str:
    LOGGER.exception("Unhandled exception in tool %s: %s", tool, error)
    return error_json("internal_error", "an unexpected server error occurred", tool, 500)


def bounded_response(
    tool: str,
    payload: dict,
    budget: int | None = None,
) -> str:
    response_budget = get_max_response_bytes() if budget is None else budget
    serialized = compact_json(payload)
    if len(serialized.encode("utf-8")) <= response_budget:
        return serialized
    return error_json(
        "response_budget_exceeded",
        "the response is larger than the configured byte budget",
        tool,
        413,
    )


def project_record(record: Any, fields: set[str] | None) -> Any:
    if fields is None or not isinstance(record, dict):
        return _clean_response(record)
    projected = {key: record.get(key) for key in fields}
    projected.update(
        {
            key: record[key]
            for key in ("code", "error", "message", "status_code")
            if key in record
        }
    )
    return _clean_response(projected)


def project_items(items: Iterable[Any], fields: set[str] | None) -> list[Any]:
    return [project_record(item, fields) for item in items]


def encode_cursor(offset: int) -> str:
    payload = json.dumps({"v": 1, "offset": offset}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None, total_count: int, tool: str) -> tuple[int, str | None]:
    if cursor is None or cursor == "":
        return 0, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        offset = payload["offset"]
        if payload.get("v") != 1 or not isinstance(offset, int) or isinstance(offset, bool):
            raise ValueError("invalid cursor payload")
        if offset < 0 or offset > total_count:
            raise ValueError("cursor is out of range")
        return offset, None
    except (
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        UnicodeError,
        binascii.Error,
    ):
        return 0, error_json(
            "invalid_cursor",
            "cursor is malformed or out of range; start again with a cursor returned by the tool",
            tool,
            400,
        )


def _identifying_fields(item: Any) -> dict:
    if not isinstance(item, dict):
        return {"value": str(item)[:128]}
    names = (
        "id",
        "name",
        "display_name",
        "site_id",
        "element_id",
        "interface_id",
        "flow_id",
        "bgppeer_id",
    )
    result = {
        name: str(item[name])[:128]
        for name in names
        if name in item and item[name] is not None
    }
    return result or {"id": "unidentified-item"}


def _envelope(
    tool: str,
    summary: str,
    key: str,
    items: list[Any],
    start: int,
    next_offset: int,
    total_count: int,
    error: dict | None = None,
    extra: dict | None = None,
) -> dict:
    truncated = next_offset < total_count
    withheld = max(total_count - next_offset, 0)
    effective_summary = summary
    if truncated:
        effective_summary = f"{summary}; {withheld} item(s) withheld; use next_cursor to continue"
    payload = {
        "tool": tool,
        "summary": effective_summary,
        key: items,
        "truncated": truncated,
        "total_count": total_count,
        "returned_count": len(items),
    }
    if extra:
        payload.update(extra)
    if truncated:
        payload["next_cursor"] = encode_cursor(next_offset)
    if error is not None:
        payload["error"] = error
    return payload


def _oversized_item_response(
    tool: str,
    summary: str,
    key: str,
    item: Any,
    start: int,
    total_count: int,
    budget: int,
) -> str:
    error = structured_error(
        "item_too_large",
        "one item exceeds the response budget; only identifying fields are returned",
        tool,
        413,
    )
    identifying = _identifying_fields(item)
    payload = _envelope(
        tool,
        summary,
        key,
        [identifying],
        start,
        start + 1,
        total_count,
        error,
    )
    if len(compact_json(payload).encode("utf-8")) <= budget:
        return compact_json(payload)
    minimal = {
        "tool": tool,
        "summary": "item exceeds response budget",
        key: [{"id": identifying.get("id", "unidentified-item")}],
        "truncated": start + 1 < total_count,
        "total_count": total_count,
        "returned_count": 1,
        "error": error,
    }
    if start + 1 < total_count:
        minimal["next_cursor"] = encode_cursor(start + 1)
    return compact_json(minimal)


def build_envelope(
    tool: str,
    summary: str,
    key: str,
    items: Iterable[Any],
    budget: int | None = None,
    cursor: str | None = None,
    limit: int | None = None,
    extra: dict | None = None,
) -> str:
    """Serialize a collection into a compact, budgeted, cursor-paginated envelope."""
    records = list(items)
    response_budget = get_max_response_bytes() if budget is None else budget
    if response_budget < 1:
        return error_json("invalid_budget", "response budget must be positive", tool, 400)
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        return error_json("invalid_limit", "limit must be at least 1", tool, 400)

    start, cursor_error = decode_cursor(cursor, len(records), tool)
    if cursor_error is not None:
        return cursor_error
    requested_end = len(records) if limit is None else min(len(records), start + limit)
    selected: list[Any] = []
    next_offset = start
    for index in range(start, requested_end):
        candidate = selected + [records[index]]
        candidate_payload = _envelope(
            tool,
            summary,
            key,
            candidate,
            start,
            index + 1,
            len(records),
            extra=extra,
        )
        if len(compact_json(candidate_payload).encode("utf-8")) > response_budget:
            if not selected:
                return _oversized_item_response(
                    tool, summary, key, records[index], start, len(records), response_budget
                )
            break
        selected = candidate
        next_offset = index + 1

    payload = _envelope(
        tool,
        summary,
        key,
        selected,
        start,
        next_offset,
        len(records),
        extra=extra,
    )
    serialized = compact_json(payload)
    if len(serialized.encode("utf-8")) <= response_budget:
        return serialized
    if selected:
        return build_envelope(
            tool,
            summary,
            key,
            records,
            response_budget,
            cursor,
            len(selected) - 1,
            extra,
        )
    return error_json("response_budget_too_small", "response budget is too small for an envelope", tool, 413)


def simple_collection_tool(
    tool_name: str,
    key: str,
    fetch_all: Callable[[], Any],
    fetch_one: Callable[[str], Any] | None = None,
    projection: set[str] | None = None,
    summary: str = "Collection retrieved",
) -> Callable[..., str]:
    """Build the common list-or-single collection behavior used by inventory tools."""
    def collection_tool(
        item_id: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> str:
        if item_id is not None and not item_id.strip():
            return error_json("invalid_argument", "item_id cannot be empty", tool_name, 400)
        data = fetch_one(item_id) if item_id and fetch_one else fetch_all()
        if isinstance(data, dict) and "error" in data:
            return error_json(
                "upstream_error", data["error"], tool_name, data.get("status_code")
            )
        if item_id and fetch_one:
            payload = {"tool": tool_name, "summary": summary, "item": _clean_response(data)}
            serialized = compact_json(payload)
            if len(serialized.encode("utf-8")) <= get_max_response_bytes():
                return serialized
            return build_envelope(tool_name, summary, "items", [data], get_max_response_bytes())
        records = as_items(data)
        return build_envelope(
            tool_name,
            summary,
            key,
            project_items(records, projection),
            get_max_response_bytes(),
            cursor,
            limit,
        )

    collection_tool.__name__ = tool_name
    collection_tool.__doc__ = f"Retrieve {key.replace('_', ' ')}."
    return collection_tool


def collection_response(
    tool: str,
    summary: str,
    key: str,
    data: Any,
    projection: set[str] | None = None,
    cursor: str | None = None,
    limit: int | None = None,
    budget: int | None = None,
    extra: dict | None = None,
) -> str:
    if isinstance(data, dict) and "error" in data:
        return error_json(
            "upstream_error",
            data["error"],
            tool,
            data.get("status_code"),
        )
    records = as_items(data)
    return build_envelope(
        tool,
        summary,
        key,
        project_items(records, projection),
        get_max_response_bytes() if budget is None else budget,
        cursor,
        limit,
        extra,
    )


def single_response(
    tool: str,
    summary: str,
    key: str,
    data: Any,
    budget: int | None = None,
) -> str:
    if isinstance(data, dict) and "error" in data:
        return error_json(
            "upstream_error",
            data["error"],
            tool,
            data.get("status_code"),
        )
    payload = {
        "tool": tool,
        "summary": summary,
        key: _clean_response(data),
        "truncated": False,
        "total_count": 1,
        "returned_count": 1,
    }
    response_budget = get_max_response_bytes() if budget is None else budget
    serialized = compact_json(payload)
    if len(serialized.encode("utf-8")) <= response_budget:
        return serialized
    return _oversized_item_response(tool, summary, key, data, 0, 1, response_budget)


def monitor_body(start: str, interval: int | str, metrics: list[str], filters: dict) -> dict:
    return {
        "start_time": start,
        "interval": interval,
        "metrics": metrics,
        "filter": filters,
    }


def monitor_metrics_body(
    start: str,
    end: str,
    metrics: list[str],
    filters: dict,
) -> dict:
    return {
        "start_time": start,
        "end_time": end,
        "interval": "5min",
        "metrics": metrics,
        "filter": filters,
    }