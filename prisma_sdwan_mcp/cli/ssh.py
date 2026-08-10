"""Stateless Netmiko execution backend for ION CLI read commands."""

from __future__ import annotations

import io
import re
import socket
from typing import Any, Callable

from ..config import get_ion_max_output_bytes


DEFAULT_CONNECT_TIMEOUT = 10.0
# A hang ceiling, not a pacing knob. Completion is decided by the device
# prompt reappearing, so a command is free to take as long as it takes; this
# only bounds a session that has stopped responding entirely (no prompt is
# ever coming back). Hitting it is an error, never a truncated success --
# most MCP clients give the caller no way to cancel an in-flight call, so
# without some ceiling a wedged session would hang the tool forever.
DEFAULT_READ_TIMEOUT = 300.0
# Bounds the reachability probe below, not the SSH handshake itself.
DEFAULT_PROBE_TIMEOUT = 3.0
MAX_PAGINATION_PAGES = 100
MAX_ERROR_LENGTH = 1000
# Size ceiling, unrelated to the read timeout above: a single `dump` can emit
# megabytes, and an MCP client has to fit the reply in its context window.
DEFAULT_MAX_OUTPUT_BYTES = 40960


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


def _is_device_error(output: str, prompt: str | None = None) -> bool:
    """Decide whether the device rejected the command.

    A real ION rejection does not start on the first line. It echoes the
    prompt and the command first, twice, and only then says what was wrong::

        AEDXB01-SDE01# dump zzznosuch
        AEDXB01-SDE01# dump zzznosuch
        unknown keyword <<zzznosuch>>

    Reading literally the first line therefore inspects the echo, matches
    nothing, and reports a rejected command as a successful one -- the same
    failure Cisco IOS produced with a caret marker above its error. The
    vocabulary below already contains "unknown"; the detector simply never
    read far enough to see it.

    Echo lines are skipped by prompt, not by counting: the prompt is the one
    reliable marker of "this line is the device repeating itself", and a fixed
    line count would be wrong on the next firmware. Beyond the echo, only the
    first line that says something is examined -- deliberately not a search of
    the whole output, because legitimate `dump` data contains words like
    "Failed: 0" on interior lines without the command having failed.
    """
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if prompt and prompt in line:
            continue  # the device echoing the prompt and the command back
        return bool(_DEVICE_ERROR.match(stripped))
    return False


ConnectionFactory = Callable[..., Any]
ProbeFactory = Callable[[str, int, float], None]


class IONConnectionError(Exception):
    """Raised internally when an SSH session cannot be established."""


class IONUnreachableError(IONConnectionError):
    """Raised internally when the TCP reachability probe fails."""

    def __init__(self, host: str, port: int, detail: str):
        self.host = host
        self.port = port
        super().__init__(
            f"could not open a TCP connection to {host}:{port} ({detail}); "
            "this server may have no network path to the device"
        )


class IONAuthenticationError(IONConnectionError):
    """Raised internally when SSH authentication is rejected."""


class IONCommandError(Exception):
    """Raised internally when a command cannot be read to completion."""


def probe_reachable(host: str, port: int, timeout: float) -> None:
    """Fail fast, before Netmiko is invoked, when there is no route to the device.

    Without this, a deployment with no network path to branch management
    addresses produces a ~10s Netmiko connect timeout whose exception text is
    indistinguishable from a device-side connection failure. This turns that
    into a specific, fast, actionable error.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return
    except OSError as error:
        raise IONUnreachableError(host, port, str(error)) from error


def _default_connection_factory(**connection_kwargs: Any) -> Any:
    from netmiko import ConnectHandler

    connection = ConnectHandler(**connection_kwargs)
    # An ION colours its prompt: find_prompt() returns
    # '\x1b[31mAEDXB01-SDE01#\x1b[0m  \x08'. That string becomes the
    # expect pattern that decides when a command has finished, and the escape
    # sequences make it match against the command echo instead of the prompt
    # that follows the output -- so send_command returned the echo and stopped,
    # reporting status "ok" with the real answer never read. A caller received
    # its own command back as the device's reply.
    #
    # netmiko strips these itself when the flag is set (base_connection reads
    # `if self.ansi_escape_codes` on every channel read), but the "generic"
    # driver leaves it False and it is not a constructor argument, so it has to
    # be set on the instance. Fixes prompt matching and removes terminal
    # control bytes from what reaches the model, in one place.
    connection.ansi_escape_codes = True
    return connection


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
        # Both flags are required. Netmiko loads the alternate file only under
        # `if self.alt_host_keys and path.isfile(self.alt_key_file)`, so
        # alt_key_file on its own is silently ignored -- and because
        # system_host_keys is False whenever a file is supplied, that left NO
        # host keys loaded at all and every connection failed as "not found in
        # known_hosts". Fails closed, so it was never a security hole, but it
        # made PRISMA_ION_KNOWN_HOSTS and the known_hosts_file argument
        # completely non-functional: the only configuration that ever worked
        # was the ~/.ssh/known_hosts default.
        connection_kwargs["alt_host_keys"] = True
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
    try:
        device_prompt = str(connection.find_prompt()).strip() or None
    except Exception:  # noqa: BLE001 — a missing prompt only costs echo-skipping
        device_prompt = None
    if _is_device_error(output, device_prompt):
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
    probe_timeout: float = DEFAULT_PROBE_TIMEOUT,
    connection_factory: ConnectionFactory | None = None,
    probe_factory: ProbeFactory | None = None,
) -> dict[str, Any]:
    if max_output_bytes is None or max_output_bytes <= 0:
        max_output_bytes = get_ion_max_output_bytes()
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

        prober = probe_factory or probe_reachable
        try:
            prober(host, port, probe_timeout)
        except IONUnreachableError as error:
            return {
                "status": "error",
                "error": {"type": "unreachable", "message": str(error)},
                "results": [],
            }

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
