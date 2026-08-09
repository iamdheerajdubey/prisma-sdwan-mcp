"""In-memory call trace: what the console asked for, and what came back.

Captured from inside `mcp_client.McpClient.call_tool`, so a page call and an
assistant call produce identical records through the one code path that both
of them share. Nothing here is written to disk, and the ring is bounded --
long sessions drop their oldest records rather than growing without limit.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

MAX_RECORDS = 500

# Mirrors prisma_sdwan_mcp/safety.py's pattern list. Duplicated rather than
# imported: webui may not import the server package (see tests/test_webui_mcp_client.py).
_SENSITIVE_PATTERNS = (
    "password", "passwd", "secret", "token", "session_id", "token_session",
    "private_key", "privatekey", "passphrase", "community_string",
    "auth_token", "authtoken", "client_secret",
)


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return any(pattern in normalized for pattern in _SENSITIVE_PATTERNS)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _is_sensitive_key(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


@dataclass
class TraceRecord:
    id: int
    tool: str
    arguments: dict[str, Any]
    elapsed_ms: float
    bytes: int
    outcome: str  # "ok" | "tool_error" | "transport_error"
    truncated: bool
    has_more: bool
    fanout_capped: bool
    compacted: bool
    complete: bool
    error: dict[str, Any] | None
    question_id: str | None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "arguments": self.arguments,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "bytes": self.bytes,
            "outcome": self.outcome,
            "truncated": self.truncated,
            "has_more": self.has_more,
            "fanout_capped": self.fanout_capped,
            "compacted": self.compacted,
            "complete": self.complete,
            "error": self.error,
            "question_id": self.question_id,
            "created_at": self.created_at,
        }


class CallTrace:
    def __init__(self, max_records: int = MAX_RECORDS) -> None:
        self._max = max_records
        self._records: list[TraceRecord] = []
        self._dropped = False
        self._next_id = 1
        self._lock = threading.Lock()

    def record(
        self,
        *,
        tool: str,
        arguments: dict[str, Any],
        elapsed_ms: float,
        outcome: str,
        response: dict[str, Any] | None = None,
        raw_bytes: int = 0,
        error: dict[str, Any] | None = None,
        question_id: str | None = None,
    ) -> TraceRecord:
        response = response or {}
        truncated = bool(response.get("truncated"))
        has_more = "next_cursor" in response
        fanout_capped = any(
            isinstance(key, str) and key.lower().endswith("capped") and response.get(key)
            for key in response
        )
        compacted = bool(response.get("omitted_fields") or response.get("omitted_empty_fields"))
        complete = outcome == "ok" and not (truncated or has_more or fanout_capped)
        record = TraceRecord(
            id=0,
            tool=tool,
            arguments=redact(arguments),
            elapsed_ms=elapsed_ms,
            bytes=raw_bytes,
            outcome=outcome,
            truncated=truncated,
            has_more=has_more,
            fanout_capped=fanout_capped,
            compacted=compacted,
            complete=complete,
            error=redact(error) if error else None,
            question_id=question_id,
        )
        with self._lock:
            record.id = self._next_id
            self._next_id += 1
            self._records.append(record)
            if len(self._records) > self._max:
                self._records.pop(0)
                self._dropped = True
        return record

    def list(self) -> dict[str, Any]:
        with self._lock:
            return {
                "records": [record.to_dict() for record in self._records],
                "dropped_older_records": self._dropped,
                "count": len(self._records),
            }

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._dropped = False


TRACE = CallTrace()
