import base64
import binascii
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from .config import get_max_response_bytes
from .limits import IDENTIFYING_VALUE_LIMIT, applied_limit


LOGGER = logging.getLogger(__name__)

ERROR_CODES = frozenset(
    {
        "invalid_argument",
        "invalid_limit",
        "invalid_cursor",
        "invalid_budget",
        "invalid_filename",
        "invalid_element",
        "not_found",
        "schema_not_found",
        "schema_validation_failed",
        "upstream_error",
        "internal_error",
        "response_budget_exceeded",
        "response_budget_too_small",
        "item_too_large",
        "historical_data_unavailable",
        "rate_limited",
        "unresolved_relationship",
        "partial_response",
    }
)
FROZEN_ENVELOPE_KEYS = (
    "tool",
    "summary",
    "<typed_collection_key>",
    "truncated",
    "total_count",
    "returned_count",
    "retrieved_at",
    "next_cursor",
)
CONTRACT_VERSION = "1.0.0"


def _now_iso() -> str:
    """ISO 8601 UTC, fixed width so it never changes an envelope's byte size."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
# Verified against a live tenant 2026-08-02. The previous list promised
# city/country/latitude/longitude, none of which the controller sends -- the
# real location data is in `address` and `location`. The policy-set-stack
# bindings were being dropped despite being the site's actual policy attachment.
SITE_KEEP_FIELDS = {
    "id",
    "name",
    "description",
    "admin_state",
    "element_cluster_role",
    "address",
    "location",
    "service_binding",
    "vrf_context_profile_id",
    "network_policysetstack_id",
    "priority_policysetstack_id",
    "nat_policysetstack_id",
    "perfmgmt_policysetstack_id",
    "prefer_lan_default_over_wan_default_route",
    "app_acceleration_enabled",
    "branch_gateway",
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
WAN_INTERFACE_KEEP_FIELDS = {
    "id",
    "name",
    "description",
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
    details: dict[str, Any] | None = None,
) -> dict:
    if code not in ERROR_CODES:
        raise ValueError(f"unknown error code: {code}")
    if code == "upstream_error" and status_code == 429:
        code = "rate_limited"
    if code == "rate_limited":
        retryable = True
    elif code.startswith("invalid_") or code in {
        "not_found",
        "historical_data_unavailable",
        "unresolved_relationship",
        "partial_response",
        "response_budget_exceeded",
        "response_budget_too_small",
        "item_too_large",
    }:
        retryable = False
    else:
        retryable = status_code is not None and 500 <= status_code <= 599
    result = {
        "code": code,
        "message": message,
        "tool": tool,
        "retryable": retryable,
    }
    if status_code is not None:
        result["status_code"] = status_code
    if details:
        # Reserved keys are never overwritable by caller-supplied details: an
        # error object whose own code or retryable flag could be clobbered by
        # an upstream payload is worse than no detail at all.
        reserved = {"code", "message", "tool", "retryable", "status_code"}
        result.update(
            {
                key: value
                for key, value in details.items()
                if value is not None and key not in reserved
            }
        )
    return result


def error_json(
    code: str,
    message: str,
    tool: str,
    status_code: int | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    return compact_json(structured_error(code, message, tool, status_code, details))


def retry_details(data: Any) -> dict[str, Any]:
    """Preserve retry accounting returned by the controller client."""
    if not isinstance(data, dict):
        return {}
    return {
        key: data[key]
        for key in ("retry_count", "elapsed_seconds")
        if key in data
    }


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
        return {"value": str(item)[:IDENTIFYING_VALUE_LIMIT]}
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
        name: str(item[name])[:IDENTIFYING_VALUE_LIMIT]
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
        "retrieved_at": _now_iso(),
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
    error: dict | None = None,
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
    budget_limited = False
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
            error=error,
            extra=extra,
        )
        if len(compact_json(candidate_payload).encode("utf-8")) > response_budget:
            if not selected:
                return _oversized_item_response(
                    tool, summary, key, records[index], start, len(records), response_budget
                )
            budget_limited = True
            break
        selected = candidate
        next_offset = index + 1

    final_extra = dict(extra or {})
    if budget_limited:
        applied = list(final_extra.get("limits_applied", []))
        if not any(item.get("limit") == "response_bytes" for item in applied):
            applied.append(applied_limit("response_bytes"))
        final_extra["limits_applied"] = applied
    payload = _envelope(
        tool,
        summary,
        key,
        selected,
        start,
        next_offset,
        len(records),
        error=error,
        extra=final_extra or None,
    )
    serialized = compact_json(payload)
    if len(serialized.encode("utf-8")) <= response_budget:
        return serialized
    # only recurse while the retry limit stays valid; len(selected) == 1 would recurse
    # with limit=0 and surface a confusing invalid_limit error instead of a budget one.
    if len(selected) > 1:
        return build_envelope(
            tool,
            summary,
            key,
            records,
            response_budget,
            cursor,
            len(selected) - 1,
            final_extra or None,
            error,
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
                "upstream_error",
                data["error"],
                tool_name,
                data.get("status_code"),
                retry_details(data),
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
            None if projection is None else {"projected_fields": sorted(projection)},
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
    error: dict | None = None,
) -> str:
    if isinstance(data, dict) and "error" in data:
        return error_json(
            "upstream_error",
            data["error"],
            tool,
            data.get("status_code"),
            retry_details(data),
        )
    records = as_items(data)
    if projection is not None:
        extra = {**(extra or {}), "projected_fields": sorted(projection)}
    return build_envelope(
        tool,
        summary,
        key,
        project_items(records, projection),
        get_max_response_bytes() if budget is None else budget,
        cursor,
        limit,
        extra,
        error,
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
            retry_details(data),
        )
    payload = {
        "tool": tool,
        "summary": summary,
        key: _clean_response(data),
        "truncated": False,
        "total_count": 1,
        "returned_count": 1,
        "retrieved_at": _now_iso(),
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