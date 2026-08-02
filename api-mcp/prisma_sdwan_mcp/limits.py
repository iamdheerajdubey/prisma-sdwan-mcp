"""Central declarations for response and execution limits."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .config import DEFAULT_MAX_RESPONSE_BYTES


MAX_ATTEMPTS = 3
MAX_RETRY_WALL_SECONDS = 8.0
LEG_RESOLUTION_CAP = 100


@dataclass(frozen=True)
class Limit:
    """A bounded operation and how a caller can recover from the bound."""

    kind: str
    value: int | float
    recovery: str | None = None
    reason: str | None = None
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.recovery is None:
            result.pop("recovery")
        if self.reason is None:
            result.pop("reason")
        if not self.source:
            result.pop("source")
        return result


EVENT_LIMIT_CAP = 100
ALARM_LIMIT_CAP = 100
RELATIVE_HOURS_CAP = 168
FLOW_DIGEST_SAMPLE_CAP = 1000
RAW_FLOW_LIMIT_CAP = 200
TOP_TALKERS_LIMIT = 10
IDENTIFYING_VALUE_LIMIT = 128


LIMITS: dict[str, Limit] = {
    "response_bytes": Limit(
        kind="env_tunable_paginated",
        value=DEFAULT_MAX_RESPONSE_BYTES,
        recovery="next_cursor",
        source="api-mcp/prisma_sdwan_mcp/config.py",
    ),
    "events_limit": Limit(
        kind="hard",
        value=EVENT_LIMIT_CAP,
        recovery="explicit_time_window",
        source="api-mcp/prisma_sdwan_mcp/tools/monitoring.py",
    ),
    "alarms_limit": Limit(
        kind="hard",
        value=ALARM_LIMIT_CAP,
        recovery="explicit_time_window",
        source="api-mcp/prisma_sdwan_mcp/tools/monitoring.py",
    ),
    "relative_hours": Limit(
        kind="hard",
        value=RELATIVE_HOURS_CAP,
        recovery="explicit_time_window",
        source="api-mcp/prisma_sdwan_mcp/tools/monitoring.py",
    ),
    "flow_digest_sample": Limit(
        kind="hard",
        value=FLOW_DIGEST_SAMPLE_CAP,
        recovery="raw_page",
        source="api-mcp/prisma_sdwan_mcp/tools/monitoring.py",
    ),
    "raw_flow_limit": Limit(
        kind="hard",
        value=RAW_FLOW_LIMIT_CAP,
        recovery="page",
        source="api-mcp/prisma_sdwan_mcp/tools/monitoring.py",
    ),
    "top_talkers": Limit(
        kind="hard",
        value=TOP_TALKERS_LIMIT,
        reason="ranking, not a collection",
        source="api-mcp/prisma_sdwan_mcp/tools/monitoring.py",
    ),
    "identifying_value": Limit(
        kind="hard",
        value=IDENTIFYING_VALUE_LIMIT,
        reason="oversized-item fallback keeps bounded identifying fields",
        source="api-mcp/prisma_sdwan_mcp/formatting.py",
    ),
    "retry_attempts": Limit(
        kind="hard",
        value=MAX_ATTEMPTS,
        recovery="caller_retry",
        source="api-mcp/prisma_sdwan_mcp/client.py",
    ),
    "retry_wall_seconds": Limit(
        kind="hard",
        value=MAX_RETRY_WALL_SECONDS,
        recovery="caller_retry",
        source="api-mcp/prisma_sdwan_mcp/client.py",
    ),
    "cli_connect_timeout": Limit(
        kind="hard",
        value=10.0,
        recovery="caller_retry",
        source="cli-mcp/prisma_sdwan_cli_mcp/executor.py",
    ),
    "cli_read_timeout": Limit(
        kind="hard",
        value=300.0,
        recovery="caller_retry",
        source="cli-mcp/prisma_sdwan_cli_mcp/executor.py",
    ),
    "cli_pagination_pages": Limit(
        kind="hard",
        value=100,
        reason="device pagination cannot be resumed after the safety ceiling",
        source="cli-mcp/prisma_sdwan_cli_mcp/executor.py",
    ),
    "cli_error_length": Limit(
        kind="hard",
        value=1000,
        reason="error text is bounded to keep failures safe to return",
        source="cli-mcp/prisma_sdwan_cli_mcp/executor.py",
    ),
    "cli_output_bytes": Limit(
        kind="env_tunable",
        value=40960,
        recovery="PRISMA_CLI_MCP_MAX_OUTPUT_BYTES",
        source="cli-mcp/prisma_sdwan_cli_mcp/executor.py",
    ),
    "leg_resolution": Limit(
        kind="hard",
        value=LEG_RESOLUTION_CAP,
        recovery="leg_offset",
        source="api-mcp/prisma_sdwan_mcp/tools/network.py",
    ),
}


def limits_payload() -> dict[str, dict[str, Any]]:
    """Return the registry in a JSON-serializable form for discovery."""
    return {name: limit.as_dict() for name, limit in LIMITS.items()}


def applied_limit(name: str) -> dict[str, Any]:
    """Return the machine-readable form used when a limit was applied."""
    limit = LIMITS[name]
    result: dict[str, Any] = {
        "limit": name,
        "kind": limit.kind,
        "value": limit.value,
        "recoverable": limit.recovery is not None,
    }
    if limit.recovery is not None:
        result["recovery"] = limit.recovery
    if limit.reason is not None:
        result["reason"] = limit.reason
    return result
