from __future__ import annotations

import json
from collections import Counter
from typing import Any

from .. import runtime
from ..executor import CapabilityExecutionError
from ..resolver import ResolutionError
from ..response import collection_json, compact_json, error_json, single_json


def records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        for key in ("items", "data", "results"):
            if isinstance(value.get(key), list):
                return [x for x in value[key] if isinstance(x, dict)]
        if "error" not in value:
            return [value]
    return []


def fail_from_upstream(tool: str, value: Any) -> str | None:
    if isinstance(value, dict) and "error" in value:
        status = value.get("status_code")
        code = "rate_limited" if status == 429 else "upstream_error"
        details = {k: value[k] for k in ("retry_count", "elapsed_seconds") if k in value}
        return error_json(code, str(value["error"]), tool, status, details)
    return None


def handle_error(tool: str, exc: Exception) -> str:
    if isinstance(exc, ResolutionError):
        code = "ambiguous_match" if exc.candidates else "not_found"
        return error_json(code, str(exc), tool, 409 if exc.candidates else 404, {"candidates": exc.candidates or None})
    if isinstance(exc, CapabilityExecutionError):
        return error_json("invalid_capability_request", str(exc), tool, 400)
    return error_json("internal_error", "unexpected server error", tool, 500, {"exception": type(exc).__name__})


def execute(action_id: str, paths: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> Any:
    executor, _ = runtime.ensure_initialized()
    return executor.execute(action_id, path_parameters=paths, body=body)


def resolve(kind: str, value: str, paths: dict[str, Any] | None = None) -> dict[str, Any]:
    _, resolver = runtime.ensure_initialized()
    return resolver.require_one(kind, value, path_parameters=paths)


def site_element(site: str | None, element: str | None) -> tuple[str | None, str | None, dict[str, Any] | None]:
    _, resolver = runtime.ensure_initialized()
    return resolver.site_element(site, element)


def project(items: list[dict[str, Any]], fields: set[str] | tuple[str, ...] | list[str]) -> list[dict[str, Any]]:
    return [{key: item[key] for key in fields if item.get(key) is not None} for item in items]


def summarize_states(items: list[dict[str, Any]], fields: tuple[str, ...] = ("state", "status", "operational_state")) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        value = None
        for field in fields:
            if item.get(field) is not None:
                value = str(item[field])
                break
        counts[value or "unknown"] += 1
    return dict(sorted(counts.items()))
