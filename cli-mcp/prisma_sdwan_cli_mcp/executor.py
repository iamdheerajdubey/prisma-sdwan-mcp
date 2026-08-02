"""Stateless Netmiko execution backend for ION CLI read commands."""

from __future__ import annotations

import io
import os
import re
from typing import Any, Callable


DEFAULT_CONNECT_TIMEOUT = 10.0
# A hang ceiling, not a pacing knob. Completion is decided by the device
# prompt reappearing, so a command is free to take as long as it takes; this
# only bounds a session that has stopped responding entirely (no prompt is
# ever coming back). Hitting it is an error, never a truncated success --
# most MCP clients give the caller no way to cancel an in-flight call, so
# without some ceiling a wedged session would hang the tool forever.
DEFAULT_READ_TIMEOUT = 300.0
MAX_PAGINATION_PAGES = 100
MAX_ERROR_LENGTH = 1000
# Size ceiling, unrelated to the read timeout above: a single `dump` can emit
# megabytes, and an MCP client has to fit the reply in its context window.
# Matches the sibling api-mcp default (PRISMA_MCP_MAX_RESPONSE_BYTES).
DEFAULT_MAX_OUTPUT_BYTES = 40960


def get_max_output_bytes() -> int:
    raw_value = os.getenv("PRISMA_CLI_MCP_MAX_OUTPUT_BYTES")
    if raw_value is None:
        return DEFAULT_MAX_OUTPUT_BYTES
    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_MAX_OUTPUT_BYTES
    return value if value > 0 else DEFAULT_MAX_OUTPUT_BYTES


def _truncate_output(output: str, max_bytes: int) -> tuple[str, int, bool]:
    """Return (kept head, total byte size, whether anything was dropped).

    Keeps the head: the start of a dump carries the header and column
    context. Cuts on a line boundary when one is close to the cap, and
    decodes with errors="ignore" so a multi-byte character is never split.
    """
    encoded = output.encode("utf-8")
    total_bytes = len(encoded)
    if total_bytes <= max_bytes:
        return output, total_bytes, False
    head = encoded[:max_bytes]
    newline = head.rfind(b"\n")
    if newline >= max_bytes - max(1, max_bytes // 10):
        head = head[:newline]
    return head.decode("utf-8", errors="ignore"), total_bytes, True

_PAGINATION_MARKER = re.compile(r"--More--|\(q\)uit", re.IGNORECASE)
# Anchored to the first line only (no re.MULTILINE/search over the whole
# output): a real ION CLI rejection is the immediate response to a bad
# command, whereas legitimate multi-line dump/inspect data can contain these
# words on an interior line (e.g. a "Failed: 0" counter) without the command
# having failed at all.
_DEVICE_ERROR = re.compile(
    r"^\s*(?:error|invalid|unknown|unrecognized|incomplete|failed|"
    r"permission denied|command not found)\b",
    re.IGNORECASE,
)


def _is_device_error(output: str) -> bool:
    first_line = output.lstrip().split("\n", 1)[0]
    return bool(_DEVICE_ERROR.match(first_line))


ConnectionFactory = Callable[..., Any]


class IONConnectionError(Exception):
    """Raised internally when an SSH session cannot be established."""


class IONAuthenticationError(IONConnectionError):
    """Raised internally when SSH authentication is rejected."""


class IONCommandError(Exception):
    """Raised internally when a command cannot be read to completion."""


def _default_connection_factory(**connection_kwargs: Any) -> Any:
    from netmiko import ConnectHandler

    return ConnectHandler(**connection_kwargs)


def _load_private_key(key_material: str, passphrase: str | None = None) -> Any:
    if not key_material.startswith("-----BEGIN "):
        raise ValueError("private_key must contain inline PEM key material")

    from paramiko import DSSKey, ECDSAKey, Ed25519Key, RSAKey

    key_types = (RSAKey, ECDSAKey, Ed25519Key, DSSKey)
    for key_type in key_types:
        try:
            return key_type.from_private_key(io.StringIO(key_material), password=passphrase)
        except Exception:
            continue
    raise ValueError("private_key could not be parsed")


def build_connection_kwargs(
    *,
    host: str,
    port: int,
    username: str,
    password: str | None = None,
    private_key: str | None = None,
    private_key_passphrase: str | None = None,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    read_timeout: float = DEFAULT_READ_TIMEOUT,
    known_hosts_file: str | None = None,
) -> dict[str, Any]:
    if not host or not username:
        raise ValueError("host and username are required")
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if (password is None) == (private_key is None):
        raise ValueError("exactly one of password or private_key is required")
    if private_key is None and private_key_passphrase is not None:
        raise ValueError("private_key_passphrase requires private_key")

    connection_kwargs: dict[str, Any] = {
        "device_type": "generic",
        "host": host,
        "port": port,
        "username": username,
        "conn_timeout": connect_timeout,
        "auth_timeout": connect_timeout,
        "banner_timeout": connect_timeout,
        "read_timeout_override": read_timeout,
        "allow_agent": False,
        # Strict host-key checking: unknown/mismatched host keys abort the
        # connection before credentials are sent. Requires the host key to
        # already be present in the known_hosts file (system default, or
        # known_hosts_file if given) -- e.g. via one prior `ssh` login or a
        # pre-provisioned known_hosts entry. This is deliberate: silently
        # trusting an unverified host key would hand credentials to anyone
        # on-path claiming to be the device.
        "ssh_strict": True,
        "system_host_keys": known_hosts_file is None,
        "verbose": False,
    }
    if known_hosts_file is not None:
        connection_kwargs["alt_key_file"] = known_hosts_file
    if password is not None:
        connection_kwargs["password"] = password
    else:
        connection_kwargs["use_keys"] = True
        connection_kwargs["pkey"] = _load_private_key(private_key, private_key_passphrase)
    return connection_kwargs


def _safe_error_message(error: BaseException, secrets: tuple[str | None, ...]) -> str:
    return _safe_error_message_details(error, secrets)[0]


def _safe_error_message_details(
    error: BaseException,
    secrets: tuple[str | None, ...],
) -> tuple[str, bool]:
    message = str(error) or error.__class__.__name__
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    truncated = len(message) > MAX_ERROR_LENGTH
    return message[:MAX_ERROR_LENGTH], truncated


def _is_authentication_error(error: BaseException) -> bool:
    error_name = error.__class__.__name__.lower()
    error_text = str(error).lower()
    return "auth" in error_name or "authentication" in error_text


def _is_host_key_error(error: BaseException) -> bool:
    error_name = error.__class__.__name__.lower()
    error_text = str(error).lower()
    return (
        "hostkey" in error_name
        or "host key" in error_text
        or "not found in known_hosts" in error_text
    )


def _has_pagination_marker(output: str) -> bool:
    return bool(_PAGINATION_MARKER.search(output))


def _completion_pattern(connection: Any) -> str:
    """Regex matching every way the device can signal 'your turn again'.

    Either the shell prompt is back (command finished) or a pager is waiting
    (more output pending). Reading until one of these -- rather than until
    the channel happens to fall quiet -- is what makes command duration
    irrelevant: `ping` emits a line per second and `dump` answers instantly,
    and both are read to completion by the same rule.
    """
    prompt = str(connection.find_prompt()).strip()
    if not prompt:
        raise IONCommandError("device did not present a shell prompt")
    return rf"(?:{re.escape(prompt)}|{_PAGINATION_MARKER.pattern})"


def _send_command_with_pagination(
    connection: Any,
    command: str,
    *,
    read_timeout: float,
) -> str:
    expect = _completion_pattern(connection)
    output = str(
        connection.send_command(
            command,
            expect_string=expect,
            read_timeout=read_timeout,
            strip_prompt=True,
            strip_command=True,
        )
    )
    page_count = 0
    while _has_pagination_marker(output):
        if page_count >= MAX_PAGINATION_PAGES:
            raise IONCommandError("CLI output pagination exceeded the safety limit")
        output = _PAGINATION_MARKER.sub("", output)
        connection.write_channel(" ")
        output += str(
            connection.read_until_pattern(pattern=expect, read_timeout=read_timeout)
        )
        page_count += 1
    return output


def _command_result(
    connection: Any,
    command: str,
    *,
    read_timeout: float,
    max_output_bytes: int,
    secrets: tuple[str | None, ...],
) -> dict[str, Any]:
    try:
        output = _send_command_with_pagination(
            connection,
            command,
            read_timeout=read_timeout,
        )
    except Exception as error:
        message, error_truncated = _safe_error_message_details(error, secrets)
        result = {
            "command": command,
            "status": "error",
            "error": message,
        }
        if error_truncated:
            result["error_truncated"] = True
        return result

    # Per command, so one oversized command cannot starve its batch siblings.
    output, total_bytes, truncated = _truncate_output(output, max_output_bytes)
    if _is_device_error(output):
        result: dict[str, Any] = {"command": command, "status": "error", "error": output}
    else:
        result = {"command": command, "status": "ok", "output": output}
    result["truncated"] = truncated
    if truncated:
        result["output_bytes"] = len(output.encode("utf-8"))
        result["output_bytes_total"] = total_bytes
    return result


def execute_commands(
    *,
    host: str,
    port: int,
    username: str,
    commands: list[str],
    password: str | None = None,
    private_key: str | None = None,
    private_key_passphrase: str | None = None,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    read_timeout: float = DEFAULT_READ_TIMEOUT,
    known_hosts_file: str | None = None,
    max_output_bytes: int | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> dict[str, Any]:
    if max_output_bytes is None or max_output_bytes <= 0:
        max_output_bytes = get_max_output_bytes()
    secrets = (password, private_key, private_key_passphrase)
    connection_kwargs: dict[str, Any] = {}
    connection = None
    try:
        connection_kwargs = build_connection_kwargs(
            host=host,
            port=port,
            username=username,
            password=password,
            private_key=private_key,
            private_key_passphrase=private_key_passphrase,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            known_hosts_file=known_hosts_file,
        )
        factory = connection_factory or _default_connection_factory
        try:
            connection = factory(**connection_kwargs)
        except Exception as error:
            if _is_host_key_error(error):
                error_type = "host_key"
            elif _is_authentication_error(error):
                error_type = "authentication"
            else:
                error_type = "connection"
            message, error_truncated = _safe_error_message_details(error, secrets)
            error_payload = {
                "type": error_type,
                "message": message,
            }
            if error_truncated:
                error_payload["error_truncated"] = True
            return {
                "status": "error",
                "error": error_payload,
                "results": [],
            }

        return {
            "status": "ok",
            "results": [
                _command_result(
                    connection,
                    command,
                    read_timeout=read_timeout,
                    max_output_bytes=max_output_bytes,
                    secrets=secrets,
                )
                for command in commands
            ],
        }
    except ValueError as error:
        return {
            "status": "error",
            "error": {"type": "validation", "message": str(error)},
            "results": [],
        }
    finally:
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass
        connection_kwargs.clear()
