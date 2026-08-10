from __future__ import annotations

from typing import Any, Optional

from .. import runtime
from ..cli.address import resolve_device_address
from ..cli.policy import validate_batch
from ..cli.ssh import execute_commands
from ..config import (
    get_ion_connect_timeout,
    get_ion_credentials,
    get_ion_known_hosts,
    get_ion_max_output_bytes,
    get_ion_probe_timeout,
    get_ion_read_timeout,
    get_ion_ssh_port,
    get_max_response_bytes,
)
from ..mcp import ACTIVE_DIAGNOSTIC, mcp
from ..response import error_json, single_json
from .common import handle_error

# A per-command output cap is never driven below this, however many commands
# are in the batch -- a cap so small the output would be unreadable is worse
# than a slightly larger response.
MIN_PER_COMMAND_OUTPUT_BYTES = 1024

_CONNECTION_ERROR_CODES = {
    "unreachable": "device_unreachable",
    "host_key": "host_key_unverified",
    "authentication": "device_authentication_failed",
    "connection": "device_connection_failed",
    "validation": "invalid_argument",
}


def _policy_denied(tool: str, decision) -> str:
    return error_json(
        "policy_denied",
        decision.reason,
        tool,
        400,
        {
            "decisions": [
                {"command": d.command, "allowed": d.allowed, "reason": d.reason}
                for d in decision.decisions
            ]
            or None
        },
    )


def _effective_credentials(
    username: Optional[str],
    password: Optional[str],
    private_key: Optional[str],
    private_key_passphrase: Optional[str],
) -> tuple[str, str | None, str | None, str | None] | str:
    """Return (username, password, private_key, passphrase) or an error_json code string.

    Supplying any per-call credential argument switches the whole credential
    set to this call's arguments instead of the environment -- there is no
    partial merge between the two sources.
    """
    per_call = any(v is not None for v in (username, password, private_key, private_key_passphrase))
    if per_call:
        eff_username, eff_password, eff_private_key, eff_passphrase = username, password, private_key, private_key_passphrase
        source = "call"
    else:
        eff_username, eff_password, eff_private_key, eff_passphrase = get_ion_credentials()
        source = "config"

    if not eff_username or (eff_password is None) == (eff_private_key is None):
        return source
    return (eff_username, eff_password, eff_private_key, eff_passphrase)


@mcp.tool(annotations=ACTIVE_DIAGNOSTIC)
def run_commands(
    commands: list[str],
    element: Optional[str] = None,
    host: Optional[str] = None,
    site: Optional[str] = None,
    port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    private_key: Optional[str] = None,
    private_key_passphrase: Optional[str] = None,
    known_hosts_file: Optional[str] = None,
) -> str:
    """Run a batch of policy-approved commands on one Prisma SD-WAN ION over SSH.

    Approved: the display-only `dump` and `inspect` families, plus the exact
    active-diagnostic forms `ping`, `tcpping`, and `dig` -- see the
    `prisma-cli://policy` resource. The diagnostics send real packets from
    the device; everything else is denied fail-closed, with no deny list --
    an unmatched command is refused by construction. One denied command
    rejects the whole batch before any connection is opened.

    Call order is fixed and load-bearing: policy validation, then credential
    availability, then device address resolution, then a bounded TCP
    reachability probe, then the SSH session itself. A policy denial never
    reaches address resolution; a missing credential never triggers a
    resolution call.

    Args:
        commands: One or more ION CLI commands. See the `prisma-cli://policy`
            resource for the exact approved forms. The whole batch is
            rejected if any single command fails the policy.
        element: Element name or controller ID to target, resolved to an SSH
            address via the same resolver every other tool uses. Required
            unless `host` is given.
        host: Explicit device address. Always wins: when it is given, no
            resolution happens and the address is used exactly as supplied.
            Use it whenever you already know the address, or for a management
            network the controller API cannot see. Supplying `element`
            alongside it is allowed -- the element is then only a label on
            the response, and nothing is resolved or cross-checked.
        site: Optional site name/ID to disambiguate `element`, as in every
            other semantic tool. Ignored when `host` is given.
        port: SSH port. Defaults to the server's configured ION SSH port
            (PRISMA_ION_SSH_PORT, default 22).
        username: Overrides the configured PRISMA_ION_USERNAME for this
            call only. Supplying any of username/password/private_key/
            private_key_passphrase switches the whole credential set to
            this call's arguments instead of the environment.
        password: Per-call password override. Exactly one of password or
            private_key is required when overriding.
        private_key: Per-call inline PEM private key override.
        private_key_passphrase: Passphrase for `private_key`, if any.
        known_hosts_file: Optional alternate known_hosts path. SSH host-key
            checking is always strict -- an unknown or mismatched key fails
            the call before credentials are sent, with error code
            `host_key_unverified`.

    Credentials normally come from PRISMA_ION_USERNAME / PRISMA_ION_PASSWORD /
    PRISMA_ION_PRIVATE_KEY / PRISMA_ION_PRIVATE_KEY_PASSPHRASE, never from a
    tool argument that would land in the conversation transcript. If none
    are configured and none are supplied per call, the call fails closed
    with `configuration_error` before any resolution, probe, or connection.

    Each command's output is capped independently (the server's configured
    cap divided across the batch, floored), and every result declares
    whether it was truncated. A device rejection is that command's own
    status "error"; sibling commands keep their own status and output.
    Completion is decided by the device's prompt reappearing, never by
    elapsed time -- a slow `ping` is read to completion, not cut short.
    """
    tool = "run_commands"

    # 1. Policy validation, before anything else.
    policy_decision = validate_batch(commands)
    if not policy_decision.allowed:
        return _policy_denied(tool, policy_decision)

    # 2. Credential availability, before any resolution call.
    credentials = _effective_credentials(username, password, private_key, private_key_passphrase)
    if isinstance(credentials, str):
        if credentials == "config":
            return error_json(
                "configuration_error",
                "ION SSH credentials are not configured: set PRISMA_ION_USERNAME and exactly one of "
                "PRISMA_ION_PASSWORD or PRISMA_ION_PRIVATE_KEY, or supply them for this call",
                tool,
                400,
                {"missing_setting": "PRISMA_ION_USERNAME/PRISMA_ION_PASSWORD/PRISMA_ION_PRIVATE_KEY", "results": []},
            )
        return error_json(
            "invalid_argument",
            "username is required, and exactly one of password or private_key",
            tool,
            400,
            {"results": []},
        )
    eff_username, eff_password, eff_private_key, eff_passphrase = credentials

    # 3. Address resolution. An explicit host always wins and is never
    # second-guessed -- if the caller already knows the address, resolution has
    # nothing to add and refusing it would only block a device the controller
    # cannot see. Name resolution runs only when no host was given.
    if not element and not host:
        return error_json("invalid_argument", "provide element or host", tool, 400)
    resolved_port = port or get_ion_ssh_port()
    if host:
        resolved_host = host
        element_name = element
        element_id = resolved_site_id = interface_id = interface_name = None
    else:
        try:
            resolution = resolve_device_address(element, site)
        except Exception as exc:
            return handle_error(tool, exc, {"results": []})
        resolved_host = resolution["host"]
        element_name = resolution["element_name"]
        element_id = resolution["element_id"]
        resolved_site_id = resolution["site_id"]
        interface_id = resolution["interface_id"]
        interface_name = resolution["interface_name"]

    # 4/5. Reachability probe, then the SSH session -- both inside execute_commands.
    per_command_cap = max(
        MIN_PER_COMMAND_OUTPUT_BYTES,
        min(get_ion_max_output_bytes(), get_max_response_bytes() // max(1, len(commands))),
    )
    result = execute_commands(
        host=resolved_host,
        port=resolved_port,
        username=eff_username,
        commands=commands,
        password=eff_password,
        private_key=eff_private_key,
        private_key_passphrase=eff_passphrase,
        connect_timeout=get_ion_connect_timeout(),
        read_timeout=get_ion_read_timeout(),
        known_hosts_file=known_hosts_file or get_ion_known_hosts(),
        max_output_bytes=per_command_cap,
        probe_timeout=get_ion_probe_timeout(),
    )

    if result["status"] != "ok":
        error = result["error"]
        error_type = error.get("type", "connection")
        code = _CONNECTION_ERROR_CODES.get(error_type, "device_connection_failed")
        # status_code is deliberately omitted (None): structured_error() only
        # marks a result retryable for a 5xx status or a rate-limit code, so
        # these SSH-layer failures come back non-retryable without needing a
        # redundant override.
        details: dict[str, Any] = {"results": []}
        if error_type == "unreachable":
            details.update({"host": resolved_host, "port": resolved_port})
        return error_json(code, error["message"], tool, None, details)

    payload = runtime.safety.redact(
        {
            "target": {
                "host": resolved_host,
                "port": resolved_port,
                "element": element_name,
                "element_id": element_id,
                "site_id": resolved_site_id,
                "interface_id": interface_id,
                "interface_name": interface_name,
            },
            "results": result["results"],
        }
    )
    return single_json(
        tool,
        f"Ran {len(commands)} command(s) on '{resolved_host}'",
        "run",
        payload,
        extra={"per_command_output_cap_bytes": per_command_cap},
    )
