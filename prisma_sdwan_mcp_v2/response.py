from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from .config import get_default_page_size, get_max_page_size, get_max_response_bytes

CONTRACT_VERSION = "2.0.0"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def structured_error(
    code: str,
    message: str,
    tool: str,
    status_code: int | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    retryable = code in {"rate_limited", "transient_upstream_error"} or (
        status_code is not None and 500 <= status_code <= 599
    )
    result: dict[str, Any] = {
        "code": code,
        "message": message,
        "tool": tool,
        "retryable": retryable,
    }
    if status_code is not None:
        result["status_code"] = status_code
    if details:
        reserved = set(result)
        result.update({k: v for k, v in details.items() if k not in reserved and v is not None})
    return result


def error_json(code: str, message: str, tool: str, status_code: int | None = None, details: dict[str, Any] | None = None) -> str:
    return compact_json(structured_error(code, message, tool, status_code, details))


def _encode_cursor(offset: int) -> str:
    raw = compact_json({"v": 2, "offset": offset}).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None, total: int) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        offset = data["offset"]
        if data.get("v") != 2 or isinstance(offset, bool) or not isinstance(offset, int):
            raise ValueError
        if offset < 0 or offset > total:
            raise ValueError
        return offset
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeError, binascii.Error) as exc:
        raise ValueError("invalid cursor") from exc


def _identity(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"value": str(item)[:256]}
    keep = (
        "id",
        "name",
        "display_name",
        "site_id",
        "element_id",
        "interface_id",
        "waninterface_id",
        "bgppeer_id",
        "vpnlink_id",
    )
    found = {key: item[key] for key in keep if item.get(key) is not None}
    return found or {"id": "unidentified-item"}


def _payload(tool: str, summary: str, key: str, items: list[Any], total: int, next_offset: int, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "tool": tool,
        "summary": summary,
        key: items,
        "truncated": next_offset < total,
        "total_count": total,
        "returned_count": len(items),
        "retrieved_at": now_iso(),
    }
    if next_offset < total:
        result["next_cursor"] = _encode_cursor(next_offset)
    if extra:
        result.update({k: v for k, v in extra.items() if v is not None})
    return result


def collection_json(
    tool: str,
    summary: str,
    key: str,
    items: Iterable[Any],
    cursor: str | None = None,
    limit: int | None = None,
    extra: dict[str, Any] | None = None,
    budget: int | None = None,
) -> str:
    records = list(items)
    max_limit = get_max_page_size()
    page_limit = get_default_page_size() if limit is None else limit
    if isinstance(page_limit, bool) or not isinstance(page_limit, int) or page_limit < 1 or page_limit > max_limit:
        return error_json("invalid_limit", f"limit must be between 1 and {max_limit}", tool, 400)
    try:
        start = _decode_cursor(cursor, len(records))
    except ValueError:
        return error_json("invalid_cursor", "cursor is malformed or out of range", tool, 400)
    response_budget = budget or get_max_response_bytes()
    end = min(len(records), start + page_limit)
    selected: list[Any] = []
    next_offset = start
    for index in range(start, end):
        candidate = selected + [records[index]]
        test = _payload(tool, summary, key, candidate, len(records), index + 1, extra)
        if len(compact_json(test).encode("utf-8")) > response_budget:
            if not selected:
                minimal = _payload(tool, summary, key, [_identity(records[index])], len(records), index + 1, extra)
                minimal["warning"] = "item exceeded response budget; only identifying fields returned"
                return compact_json(minimal)
            break
        selected = candidate
        next_offset = index + 1
    final = _payload(tool, summary, key, selected, len(records), next_offset, extra)
    if next_offset < len(records):
        final["summary"] = f"{summary}; more results available via next_cursor"
    serialized = compact_json(final)
    if len(serialized.encode("utf-8")) > response_budget:
        return error_json("response_budget_exceeded", "response is larger than the configured byte budget", tool, 413)
    return serialized


def single_json(tool: str, summary: str, key: str, item: Any, extra: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "tool": tool,
        "summary": summary,
        key: item,
        "retrieved_at": now_iso(),
    }
    if extra:
        payload.update({k: v for k, v in extra.items() if v is not None})
    serialized = compact_json(payload)
    if len(serialized.encode("utf-8")) <= get_max_response_bytes():
        return serialized
    return collection_json(tool, summary, key, [item], limit=1, extra=extra)
