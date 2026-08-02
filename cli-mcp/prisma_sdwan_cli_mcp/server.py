"""FastMCP entrypoint for the read-only ION CLI passthrough."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from fastmcp import FastMCP

from .executor import execute_commands
from .policy import validate_batch


mcp = FastMCP("Prisma SD-WAN ION CLI MCP Server")


def _validation_response(message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": {"type": "validation", "message": message},
        "results": [],
    }


def _policy_response(decision) -> dict[str, Any]:
    return {
        "status": "denied",
        "error": {"type": "policy", "message": decision.reason},
        "results": [
            {
                "command": command_decision.command,
                "status": "denied",
                "error": command_decision.reason,
            }
            for command_decision in decision.decisions
        ],
    }


def _validate_connection_inputs(
    *,
    host: object,
    port: object,
    username: object,
    password: object,
    private_key: object,
    private_key_passphrase: object,
) -> str | None:
    if not isinstance(host, str) or not host.strip():
        return "host is required"
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        return "port must be between 1 and 65535"
    if not isinstance(username, str) or not username.strip():
        return "username is required"
    if password is not None and not isinstance(password, str):
        return "password must be a string"
    if private_key is not None and not isinstance(private_key, str):
        return "private_key must be a string"
    if password is not None and private_key is not None:
        return "provide exactly one of password or private_key"
    if password is None and private_key is None:
        return "one of password or private_key is required"
    if private_key_passphrase is not None and private_key is None:
        return "private_key_passphrase requires private_key"
    if private_key_passphrase is not None and not isinstance(private_key_passphrase, str):
        return "private_key_passphrase must be a string"
    return None


@mcp.tool()
def run_commands(
    host: str,
    port: int,
    username: str,
    commands: list[str],
    password: str | None = None,
    private_key: str | None = None,
    private_key_passphrase: str | None = None,
    known_hosts_file: str | None = None,
) -> dict[str, Any]:
    """Run a batch of read-only commands on one Prisma SD-WAN ION device.

    The policy gate validates every command before a Netmiko session is opened.
    Credentials are accepted only for this call and are never returned.

    SSH host-key checking is strict: the device's host key must already be
    present in the known_hosts file (system default, or known_hosts_file if
    given), otherwise the call fails with error type "host_key" and no
    credentials are sent. Populate that known_hosts entry out of band (e.g. one
    prior `ssh` login, or `ssh-keyscan`) before calling this tool.
    """
    policy_decision = validate_batch(commands)
    if not policy_decision.allowed:
        return _policy_response(policy_decision)

    invalid_input = _validate_connection_inputs(
        host=host,
        port=port,
        username=username,
        password=password,
        private_key=private_key,
        private_key_passphrase=private_key_passphrase,
    )
    if invalid_input:
        return _validation_response(invalid_input)

    return execute_commands(
        host=host,
        port=port,
        username=username,
        commands=commands,
        password=password,
        private_key=private_key,
        private_key_passphrase=private_key_passphrase,
        known_hosts_file=known_hosts_file,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prisma SD-WAN ION CLI MCP Server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for HTTP/SSE transport (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP/SSE transport (default: 8000)",
    )
    args = parser.parse_args(argv)
    print(
        f"Prisma SD-WAN ION CLI MCP Server ({args.transport})",
        file=sys.stderr,
    )
    try:
        if args.transport == "stdio":
            mcp.run(transport="stdio")
        else:
            try:
                mcp.run(
                    transport=args.transport,
                    host=args.host,
                    port=args.port,
                    show_banner=False,
                )
            except TypeError:
                mcp.run(transport=args.transport, host=args.host, port=args.port)
    except KeyboardInterrupt:
        print("Server stopped by user.", file=sys.stderr)
        return 0
    except Exception:
        print("Server stopped because of an unexpected error.", file=sys.stderr)
        return 1
    return 0
