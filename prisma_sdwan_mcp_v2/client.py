from __future__ import annotations

import logging
import os
import random
import threading
import time
from typing import Any, Callable

try:
    import prisma_sase
except ImportError:  # lets catalog/unit tests run without the vendor SDK installed
    prisma_sase = None

from .config import get_controller, get_credentials

LOGGER = logging.getLogger(__name__)
FALLBACK_TOKEN_SECONDS = 839
TOKEN_SAFETY_MARGIN_SECONDS = 60
MAX_ATTEMPTS = 4
MAX_RETRY_WALL_SECONDS = 12.0


class PrismaSDWANClient:
    """Thin, resilient SDK client inherited from the strongest v1 behavior."""

    def __init__(self, sdk: Any | None = None):
        self.controller = get_controller()
        if sdk is not None:
            self.sdk = sdk
        else:
            if prisma_sase is None:
                raise RuntimeError("prisma_sase is not installed; install requirements.txt")
            self.sdk = prisma_sase.API(controller=self.controller, ssl_verify=True, update_check=False)
        self.logged_in = sdk is not None
        self.token_expiry = float("inf") if sdk is not None else 0.0
        self._login_lock = threading.Lock()
        self._region_logged = False
        configured_region = os.getenv("PAN_REGION")
        if configured_region:
            LOGGER.warning("PAN_REGION=%s is advisory; the SDK chooses tenant region during login.", configured_region)

    @staticmethod
    def _status_code(response: Any) -> int | None:
        value = getattr(response, "status_code", None)
        return value if isinstance(value, int) else None

    @staticmethod
    def _clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: PrismaSDWANClient._clean(v) for k, v in value.items() if v is not None and not str(k).startswith("_")}
        if isinstance(value, list):
            return [PrismaSDWANClient._clean(v) for v in value]
        return value

    @classmethod
    def _extract_response(cls, response: Any) -> Any:
        # Test doubles may return plain Python data directly.
        if isinstance(response, (dict, list, str, int, float, bool)) or response is None:
            return cls._clean(response)
        try:
            if not getattr(response, "cgx_status"):
                content = getattr(response, "cgx_content", None)
                errors = content.get("_error", [{}]) if isinstance(content, dict) else [{}]
                message = errors[0].get("message", "Unknown error") if errors else "Unknown error"
                status = getattr(response, "status_code", None)
                if message == "Unknown error":
                    message = {
                        400: "Bad request",
                        401: "Authentication failed",
                        403: "Permission denied",
                        404: "Resource not found",
                        429: "Rate limit exceeded",
                        500: "Internal server error",
                    }.get(status, f"HTTP {status} error")
                return {"error": message, "status_code": status}
            content = getattr(response, "cgx_content", None)
            if isinstance(content, dict) and "items" in content:
                return cls._clean(content["items"])
            return cls._clean(content)
        except Exception as exc:
            return {"error": f"Response parsing error: {exc}"}

    @staticmethod
    def _token_lifetime(result: Any) -> float | None:
        candidates = [result]
        if isinstance(result, dict):
            candidates.extend(result.get(name) for name in ("cgx_content", "data", "token", "oauth") if result.get(name) is not None)
        for candidate in candidates:
            if isinstance(candidate, dict):
                for name in ("expires_in", "expiresIn", "expires", "token_lifetime", "token_lifetime_seconds"):
                    value = candidate.get(name)
                    if isinstance(value, (int, float)) and value > 0:
                        return float(value)
        return None

    def _is_token_expired(self) -> bool:
        return time.time() >= self.token_expiry

    def login(self) -> None:
        with self._login_lock:
            if self.logged_in and not self._is_token_expired():
                return
            client_id, client_secret, tsg_id = get_credentials()
            if not all([client_id, client_secret, tsg_id]):
                raise RuntimeError("Missing PAN_CLIENT_ID, PAN_CLIENT_SECRET, or PAN_TSG_ID")
            result = self.sdk.interactive.login_secret(client_id=client_id, client_secret=client_secret, tsg_id=tsg_id)
            if not result:
                raise RuntimeError("Authentication failed. Check credentials and TSG ID.")
            # v1 used profile as a cheap login validation and region bootstrap.
            self.sdk.get.profile()
            lifetime = self._token_lifetime(result) or FALLBACK_TOKEN_SECONDS
            self.token_expiry = time.time() + max(1.0, lifetime - TOKEN_SAFETY_MARGIN_SECONDS)
            self.logged_in = True
            region = getattr(self.sdk, "panw_region", None)
            if region and not self._region_logged:
                LOGGER.info("SDK-derived Prisma SASE region: %s", region)
                self._region_logged = True

    def invoke(self, sdk_func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if not self.logged_in or self._is_token_expired():
            self.login()
        started = time.monotonic()
        reauthenticated = False
        last_status = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = sdk_func(*args, **kwargs)
            except Exception as exc:
                LOGGER.exception("SDK call failed")
                return {"error": str(exc), "exception_type": type(exc).__name__}
            status = self._status_code(response)
            last_status = status
            if status in (401, 403) and not getattr(response, "cgx_status", False):
                if reauthenticated:
                    return self._extract_response(response)
                self.logged_in = False
                self.login()
                reauthenticated = True
                continue
            retryable = status == 429 or (status is not None and 500 <= status <= 599)
            if retryable and attempt < MAX_ATTEMPTS:
                remaining = MAX_RETRY_WALL_SECONDS - (time.monotonic() - started)
                if remaining <= 0:
                    break
                delay = min(0.5 * (2 ** (attempt - 1)) + random.uniform(0, 0.25), remaining)
                time.sleep(delay)
                continue
            if retryable:
                elapsed = time.monotonic() - started
                return {
                    "error": f"Transient API failure after {attempt} attempts",
                    "status_code": status,
                    "retry_count": attempt,
                    "elapsed_seconds": round(elapsed, 2),
                }
            return self._extract_response(response)
        elapsed = time.monotonic() - started
        return {
            "error": f"Transient API failure after {MAX_ATTEMPTS} attempts",
            "status_code": last_status,
            "retry_count": MAX_ATTEMPTS,
            "elapsed_seconds": round(elapsed, 2),
        }
