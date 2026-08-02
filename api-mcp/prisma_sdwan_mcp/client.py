import logging
import os
import random
import threading
import time
from typing import Any, Callable

import prisma_sase

from .config import get_controller, get_credentials
from .formatting import _extract_response
from .limits import MAX_ATTEMPTS, MAX_RETRY_WALL_SECONDS


LOGGER = logging.getLogger(__name__)
FALLBACK_TOKEN_SECONDS = 839
TOKEN_SAFETY_MARGIN_SECONDS = 60


class PrismaSDWANClient:
    def __init__(self):
        self.controller = get_controller()
        self.sdk = prisma_sase.API(
            controller=self.controller, ssl_verify=True, update_check=False
        )
        self.logged_in = False
        self.token_expiry = 0.0
        self._login_lock = threading.Lock()
        self._region_logged = False
        self._fallback_lifetime_logged = False
        configured_region = os.getenv("PAN_REGION")
        if configured_region:
            LOGGER.warning(
                "PAN_REGION=%s is advisory; the SDK derives the tenant region at login and the controller is not changed.",
                configured_region,
            )

    def _token_lifetime(self, result: Any) -> float | None:
        candidates = [result]
        if isinstance(result, dict):
            candidates.extend(
                result.get(name)
                for name in ("cgx_content", "data", "token", "oauth")
                if result.get(name) is not None
            )
        for candidate in candidates:
            if isinstance(candidate, dict):
                for name in (
                    "expires_in",
                    "expiresIn",
                    "expires",
                    "token_lifetime",
                    "token_lifetime_seconds",
                ):
                    value = candidate.get(name)
                    if isinstance(value, (int, float)) and value > 0:
                        return float(value)
            else:
                for name in ("expires_in", "expiresIn", "expires"):
                    value = getattr(candidate, name, None)
                    if isinstance(value, (int, float)) and value > 0:
                        return float(value)
        for name in ("expires_in", "expiresIn", "token_lifetime"):
            value = getattr(self.sdk, name, None)
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
        return None

    def login(self):
        with self._login_lock:
            if self.logged_in and not self._is_token_expired():
                return

            client_id, client_secret, tsg_id = get_credentials()
            if not all([client_id, client_secret, tsg_id]):
                raise Exception(
                    "Missing credentials. Set PAN_CLIENT_ID, PAN_CLIENT_SECRET, and PAN_TSG_ID."
                )

            LOGGER.info("Authenticating to %s", self.controller)
            try:
                result = self.sdk.interactive.login_secret(
                    client_id=client_id,
                    client_secret=client_secret,
                    tsg_id=tsg_id,
                )
                if not result:
                    raise Exception("Authentication failed. Check credentials and TSG ID.")

                self.sdk.get.profile()
                lifetime = self._token_lifetime(result)
                if lifetime is None:
                    self.token_expiry = time.time() + FALLBACK_TOKEN_SECONDS
                    if not self._fallback_lifetime_logged:
                        LOGGER.warning(
                            "Login response did not expose token lifetime; using %s-second fallback.",
                            FALLBACK_TOKEN_SECONDS,
                        )
                        self._fallback_lifetime_logged = True
                else:
                    self.token_expiry = time.time() + max(
                        1, lifetime - TOKEN_SAFETY_MARGIN_SECONDS
                    )

                self.logged_in = True
                region = getattr(self.sdk, "panw_region", None)
                if region and not self._region_logged:
                    LOGGER.info("SDK-derived Prisma SASE region: %s", region)
                    self._region_logged = True
                LOGGER.info("Authentication successful")
            except Exception:
                LOGGER.exception("Authentication failed")
                self.logged_in = False
                raise

    def _is_token_expired(self):
        return time.time() >= self.token_expiry

    @staticmethod
    def _status_code(response: Any) -> int | None:
        value = getattr(response, "status_code", None)
        return value if isinstance(value, int) else None

    def _invoke(self, sdk_func: Callable, *args, **kwargs):
        """Invoke an SDK method with auth refresh and bounded transient retries."""
        if not self.logged_in or self._is_token_expired():
            self.login()

        started = time.monotonic()
        reauthenticated = False
        last_status = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = sdk_func(*args, **kwargs)
            except Exception as error:
                LOGGER.exception("SDK call failed")
                return {"error": str(error)}

            status_code = self._status_code(response)
            last_status = status_code
            if status_code in (401, 403) and not getattr(response, "cgx_status", False):
                if reauthenticated:
                    return _extract_response(response)
                LOGGER.warning("Session expired; re-authenticating")
                self.logged_in = False
                self.login()
                reauthenticated = True
                continue

            retryable = status_code == 429 or status_code is not None and 500 <= status_code <= 599
            if retryable and attempt < MAX_ATTEMPTS:
                elapsed = time.monotonic() - started
                remaining = MAX_RETRY_WALL_SECONDS - elapsed
                if remaining <= 0:
                    break
                delay = min(0.5 * (2 ** (attempt - 1)) + random.uniform(0, 0.25), remaining)
                time.sleep(delay)
                continue

            if retryable:
                elapsed = time.monotonic() - started
                return {
                    "error": f"Transient API failure after {attempt} attempts ({elapsed:.2f}s)",
                    "status_code": status_code,
                    "retry_count": attempt,
                    "elapsed_seconds": round(elapsed, 2),
                }
            return _extract_response(response)

        elapsed = time.monotonic() - started
        return {
            "error": f"Transient API failure after {MAX_ATTEMPTS} attempts ({elapsed:.2f}s)",
            "status_code": last_status,
            "retry_count": MAX_ATTEMPTS,
            "elapsed_seconds": round(elapsed, 2),
        }

    def call_sdk(self, sdk_func, *args, **kwargs):
        """Compatibility wrapper for SDK GET calls."""
        return self._invoke(sdk_func, *args, **kwargs)

    def call_sdk_post(self, sdk_func, data, **kwargs):
        """Compatibility wrapper for SDK POST calls."""
        return self._invoke(sdk_func, data, **kwargs)
