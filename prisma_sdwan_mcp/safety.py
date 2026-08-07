from __future__ import annotations

import re
from typing import Any


DEFAULT_PATTERNS = (
    "password",
    "passwd",
    "secret",
    "token",
    "session_id",
    "token_session",
    "private_key",
    "privatekey",
    "passphrase",
    "community_string",
    "auth_token",
    "authtoken",
    "client_secret",
)


class ResponseSafety:
    """Central, recursive secret redaction for every v2 response."""

    def __init__(self, patterns: list[str] | tuple[str, ...] | None = None):
        values = patterns or DEFAULT_PATTERNS
        self.patterns = tuple(str(value).lower() for value in values)

    @staticmethod
    def _normalize_key(key: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")

    def is_sensitive_key(self, key: str) -> bool:
        normalized = self._normalize_key(key)
        return any(pattern in normalized for pattern in self.patterns)

    def redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, item in value.items():
                if key is None:
                    continue
                text_key = str(key)
                if text_key.startswith("_"):
                    continue
                if self.is_sensitive_key(text_key):
                    cleaned[text_key] = "[REDACTED]"
                elif item is not None:
                    cleaned[text_key] = self.redact(item)
            return cleaned
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return [self.redact(item) for item in value]
        return value
