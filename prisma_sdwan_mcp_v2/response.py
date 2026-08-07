from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from .config import get_default_page_size, get_max_page_size, get_max_response_bytes

CONTRACT_VERSION = "2.0.0"
# Responses smaller than this share of the byte budget are left exactly as they
# were: the disclosure keys compaction adds would cost more than it saves. The
# measured cost of this server sits in the tail above it.
COMPACT_THRESHOLD = 0.25
# A single field carrying more than this share of a record's bytes is treated as
# the record's substance and is never held back.
DOMINANT_FIELD_SHARE = 0.4


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


def _encode_cursor(offset: int, tool: str) -> str:
    raw = compact_json({"v": 3, "offset": offset, "t": tool}).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None, total: int, tool: str) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        offset = data["offset"]
        # The tool tag stops a cursor minted by one tool from silently paging a
        # different tool's unrelated result list.
        if data.get("v") != 3 or data.get("t") != tool or isinstance(offset, bool) or not isinstance(offset, int):
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


# Fields that report condition. An operator's question is usually "is something
# wrong", so these are never held back - the saving is not worth hiding the one
# field that answers the question.
_CONDITION = re.compile(
    r"state|status|error|alarm|severity|connect|enabled|disabled|up$|down|fault|health|"
    r"active|usable|cleared|suppress|expir|licen|reachab|fail|warn|admin_action|mode",
    re.IGNORECASE,
)
# Fields that identify a record or place it in time/scope. Without these the
# caller cannot act on, or ask a follow-up about, the row it just read.
_IDENTITY = re.compile(
    r"^(id|name|display_name|description|code|time|timestamp|created_on|updated_on|"
    r"serial_number|hw_id|model_name|software_version|version|ipv4|ipv6|address|prefix|"
    # what a thing *is* is identity, not configuration detail: a device list
    # without HUB/SPOKE, or events without their type, answers half the question
    r"role|type|kind|category|label|severity)$"
    r"|_id$|_ids$|_time$|_ip$|_role$|_type$",
    re.IGNORECASE,
)


def _keep_field(name: str) -> bool:
    return bool(_IDENTITY.search(name) or _CONDITION.search(name))


def _compact_records(records: list[Any], budget_fits: Any) -> tuple[list[Any], dict[str, Any]]:
    """Shrink wide records without making anything unreachable.

    Three passes, cheapest and most conservative first. Each one reports what it
    did, so the caller can always see what it is not being shown and ask again
    with ``detail="full"``:

    1. drop fields that are empty in *every* record - they carry no information
       in this response at all (lossless);
    2. hoist fields whose value is identical in *every* record into one shared
       block instead of repeating them per row (lossless - the value is kept);
    3. only if the response still will not fit, hold back fields that neither
       identify the record nor report its condition (lossy, and named).
    """
    if not records or not all(isinstance(r, dict) for r in records):
        return records, {}
    keys: set[str] = set()
    for record in records:
        keys.update(record)

    empty = {k for k in keys if all(r.get(k) in (None, "", [], {}) for r in records)}
    live = keys - empty
    shared: dict[str, Any] = {}
    if len(records) > 1:
        for k in live:
            values = {compact_json(r.get(k)) for r in records}
            if len(values) == 1 and records[0].get(k) is not None:
                shared[k] = records[0][k]
    trimmed = [{k: v for k, v in r.items() if k not in empty and k not in shared} for r in records]
    notes: dict[str, Any] = {}
    if empty:
        notes["omitted_empty_fields"] = sorted(empty)
    if shared:
        notes["shared_fields"] = shared

    if budget_fits(trimmed, notes):
        return trimmed, notes

    remaining = {k for r in trimmed for k in r}
    # A field that is most of the record IS the record. For a config object the
    # substance is neither an identifier nor a condition flag - holding it back
    # would return an index entry instead of an answer (a service binding map
    # stripped to {id, name} is not a smaller answer, it is no answer). Protect
    # anything that dominates, and let paging handle the size instead.
    weight = {k: sum(len(compact_json(r.get(k))) for r in trimmed) for k in remaining}
    body = sum(weight.values()) or 1
    dominant = {k for k, v in weight.items() if v / body > DOMINANT_FIELD_SHARE}
    held = sorted(k for k in remaining if not _keep_field(k) and k not in dominant)
    kept = {k for k in remaining if k not in held}
    # Holding back fields is only defensible when what survives still answers
    # "what is this, and how is it doing". If nothing left reports condition, the
    # caller is reading an object's content rather than its health, and trimming
    # content is deletion rather than compression - a WAN path or an application
    # definition reduced to its identifiers answers nothing. Stop at the lossless
    # passes and let paging handle the size.
    if not held or not any(_CONDITION.search(k) for k in kept):
        return trimmed, notes
    selected = [{k: v for k, v in r.items() if _keep_field(k)} for r in trimmed]
    notes["omitted_fields"] = held
    notes["omitted_fields_reason"] = (
        "held back to fit more records in one response; these neither identify the record nor "
        "report its condition. Re-request with detail='full' to get every field"
    )
    return selected, notes


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
        result["next_cursor"] = _encode_cursor(next_offset, tool)
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
    detail: str | None = None,
) -> str:
    records = list(items)
    max_limit = get_max_page_size()
    page_limit = get_default_page_size() if limit is None else limit
    if isinstance(page_limit, bool) or not isinstance(page_limit, int) or page_limit < 1 or page_limit > max_limit:
        return error_json("invalid_limit", f"limit must be between 1 and {max_limit}", tool, 400)
    try:
        start = _decode_cursor(cursor, len(records), tool)
    except ValueError:
        return error_json(
            "invalid_cursor",
            f"cursor is malformed, out of range, or was issued by a different tool - reuse only a next_cursor returned by {tool}",
            tool,
            400,
        )
    response_budget = budget or get_max_response_bytes()
    extra = dict(extra) if extra else {}
    # Try the page exactly as asked for first. Only if the records the caller
    # wants will not fit is anything compacted - responses that already fit are
    # returned byte-identical to before.
    if detail != "full":
        page = records[start:min(len(records), start + page_limit)]

        def _size(candidate_records: list[Any], notes: dict[str, Any]) -> int:
            trial = _payload(tool, summary, key, candidate_records, len(records), start + len(candidate_records), {**extra, **notes})
            return len(compact_json(trial).encode("utf-8"))

        def _fits(candidate_records: list[Any], notes: dict[str, Any]) -> bool:
            return _size(candidate_records, notes) <= response_budget * COMPACT_THRESHOLD

        # Paging already guarantees a response fits, so "does it fit" would never
        # trigger. The real choice is fewer full records versus more compact ones,
        # so compaction engages once a response is big enough for that trade to be
        # worth making - which is also where the measured cost actually sits.
        if page and not _fits(page, {}):
            compacted, notes = _compact_records(page, _fits)
            if notes:
                records = records[:start] + compacted + records[start + len(page):]
                extra.update(notes)
    end = min(len(records), start + page_limit)
    selected: list[Any] = []
    next_offset = start
    for index in range(start, end):
        candidate = selected + [records[index]]
        test = _payload(tool, summary, key, candidate, len(records), index + 1, extra)
        if len(compact_json(test).encode("utf-8")) > response_budget:
            if not selected:
                minimal = _payload(tool, summary, key, [_identity(records[index])], len(records), index + 1, extra)
                # The item's contents were dropped. _payload computes truncated from
                # the offset, which is False when this is the only/last record - so
                # say it explicitly rather than reporting a complete result.
                minimal["truncated"] = True
                minimal["returned_count"] = 0
                minimal["warning"] = (
                    "item exceeded the response byte budget; its contents were dropped and only identifying "
                    "fields are shown. Paging cannot recover it - request a narrower read (a semantic tool "
                    "scoped to one site/element, or a shorter time window), or raise MCP_MAX_RESPONSE_BYTES"
                )
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
