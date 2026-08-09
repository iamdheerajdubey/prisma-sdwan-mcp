import asyncio
import json

import pytest

import prisma_sdwan_mcp.tools.cli as cli
from prisma_sdwan_mcp.resolver import ResolutionError


VALID_CREDENTIALS = ("reader", "secret", None, None)


def _no_call(*args, **kwargs):
    raise AssertionError("this stage must not be reached")


# --- Order of operations (task 5.3) -------------------------------------


def test_policy_denial_reaches_no_later_stage(monkeypatch):
    monkeypatch.setattr(cli, "get_ion_credentials", _no_call)
    monkeypatch.setattr(cli, "resolve_device_address", _no_call)
    monkeypatch.setattr(cli, "execute_commands", _no_call)

    response = json.loads(cli.run_commands(commands=["debug reboot"], element="ION-1"))

    assert response["code"] == "policy_denied"
    assert response["decisions"][0]["command"] == "debug reboot"


def test_missing_credential_performs_no_resolution_call(monkeypatch):
    monkeypatch.setattr(cli, "get_ion_credentials", lambda: (None, None, None, None))
    monkeypatch.setattr(cli, "resolve_device_address", _no_call)
    monkeypatch.setattr(cli, "execute_commands", _no_call)

    response = json.loads(cli.run_commands(commands=["dump interface status all"], element="ION-1"))

    assert response["code"] == "configuration_error"
    assert response["results"] == []


def test_resolution_failure_never_reaches_execute_commands(monkeypatch):
    monkeypatch.setattr(cli, "get_ion_credentials", lambda: VALID_CREDENTIALS)

    def failing_resolve(element, site):
        raise ResolutionError("2 elements match", candidates=[{"id": "e1"}, {"id": "e2"}])

    monkeypatch.setattr(cli, "resolve_device_address", failing_resolve)
    monkeypatch.setattr(cli, "execute_commands", _no_call)

    response = json.loads(cli.run_commands(commands=["dump interface status all"], element="ION"))

    assert response["code"] == "ambiguous_match"
    assert response["results"] == []
    assert len(response["candidates"]) == 2


def test_explicit_host_never_calls_resolve_device_address(monkeypatch):
    monkeypatch.setattr(cli, "get_ion_credentials", lambda: VALID_CREDENTIALS)
    monkeypatch.setattr(cli, "resolve_device_address", _no_call)
    monkeypatch.setattr(
        cli,
        "execute_commands",
        lambda **kwargs: {"status": "ok", "results": [{"command": "dump interface status all", "status": "ok", "output": "x", "truncated": False}]},
    )

    response = json.loads(cli.run_commands(commands=["dump interface status all"], host="10.0.0.9"))

    assert response["run"]["target"]["host"] == "10.0.0.9"


def test_explicit_host_wins_over_element_and_is_never_resolved(monkeypatch):
    """A caller-supplied address is authoritative: no resolution, no cross-check."""
    monkeypatch.setattr(cli, "get_ion_credentials", lambda: VALID_CREDENTIALS)
    monkeypatch.setattr(cli, "resolve_device_address", _no_call)
    monkeypatch.setattr(
        cli,
        "execute_commands",
        lambda **kwargs: {"status": "ok", "results": [{"command": "dump interface status all", "status": "ok", "output": "x", "truncated": False}]},
    )

    response = json.loads(cli.run_commands(commands=["dump interface status all"], element="ION-1", host="10.0.0.9"))

    assert response["run"]["target"]["host"] == "10.0.0.9"
    # The element survives only as a label -- nothing was resolved from it.
    assert response["run"]["target"]["element"] == "ION-1"
    assert "element_id" not in response["run"]["target"]


def test_neither_element_nor_host_is_an_input_error(monkeypatch):
    monkeypatch.setattr(cli, "get_ion_credentials", lambda: VALID_CREDENTIALS)
    monkeypatch.setattr(cli, "resolve_device_address", _no_call)
    monkeypatch.setattr(cli, "execute_commands", _no_call)

    response = json.loads(cli.run_commands(commands=["dump interface status all"]))

    assert response["code"] == "invalid_argument"


# --- Tool-level behavior (task 7.1) --------------------------------------


def test_partial_batch_success_keeps_independent_per_command_results(monkeypatch):
    monkeypatch.setattr(cli, "get_ion_credentials", lambda: VALID_CREDENTIALS)
    monkeypatch.setattr(
        cli,
        "execute_commands",
        lambda **kwargs: {
            "status": "ok",
            "results": [
                {"command": "dump interface status all", "status": "ok", "output": "interfaces", "truncated": False},
                {"command": "inspect system arp all", "status": "error", "error": "Invalid command", "truncated": False},
            ],
        },
    )

    response = json.loads(
        cli.run_commands(commands=["dump interface status all", "inspect system arp all"], host="10.0.0.9")
    )

    results = response["run"]["results"]
    assert [r["status"] for r in results] == ["ok", "error"]
    assert results[0]["output"] == "interfaces"
    assert results[1]["error"] == "Invalid command"


@pytest.mark.parametrize(
    "error_type,expected_code",
    [
        ("unreachable", "device_unreachable"),
        ("host_key", "host_key_unverified"),
        ("authentication", "device_authentication_failed"),
        ("connection", "device_connection_failed"),
    ],
)
def test_batch_level_ssh_failures_map_to_the_right_code_with_empty_results(monkeypatch, error_type, expected_code):
    monkeypatch.setattr(cli, "get_ion_credentials", lambda: VALID_CREDENTIALS)
    monkeypatch.setattr(
        cli,
        "execute_commands",
        lambda **kwargs: {"status": "error", "error": {"type": error_type, "message": "boom"}, "results": []},
    )

    response = json.loads(cli.run_commands(commands=["dump interface status all"], host="10.0.0.9"))

    assert response["code"] == expected_code
    assert response["results"] == []
    assert response["retryable"] is False


def test_unreachable_error_names_the_host_and_port_tried(monkeypatch):
    monkeypatch.setattr(cli, "get_ion_credentials", lambda: VALID_CREDENTIALS)
    monkeypatch.setattr(
        cli,
        "execute_commands",
        lambda **kwargs: {"status": "error", "error": {"type": "unreachable", "message": "no route"}, "results": []},
    )

    response = json.loads(cli.run_commands(commands=["dump interface status all"], host="10.0.0.9", port=2222))

    assert response["host"] == "10.0.0.9"
    assert response["port"] == 2222


def test_device_error_first_line_classification_passes_through_untouched(monkeypatch):
    """The tool trusts ssh.py's own first-line-only device-error detection
    verbatim rather than re-classifying results itself."""
    monkeypatch.setattr(cli, "get_ion_credentials", lambda: VALID_CREDENTIALS)
    monkeypatch.setattr(
        cli,
        "execute_commands",
        lambda **kwargs: {
            "status": "ok",
            "results": [
                {
                    "command": "dump interface status all",
                    "status": "ok",
                    "output": "State   Failed: 0\ninterface up\nAll good",
                    "truncated": False,
                }
            ],
        },
    )

    response = json.loads(cli.run_commands(commands=["dump interface status all"], host="10.0.0.9"))

    assert response["run"]["results"][0]["status"] == "ok"
    assert response["run"]["results"][0]["output"] == "State   Failed: 0\ninterface up\nAll good"


def test_per_command_truncation_byte_counts_pass_through(monkeypatch):
    monkeypatch.setattr(cli, "get_ion_credentials", lambda: VALID_CREDENTIALS)
    monkeypatch.setattr(
        cli,
        "execute_commands",
        lambda **kwargs: {
            "status": "ok",
            "results": [
                {
                    "command": "dump interface status all",
                    "status": "ok",
                    "output": "x" * 100,
                    "truncated": True,
                    "output_bytes": 100,
                    "output_bytes_total": 5000,
                }
            ],
        },
    )

    response = json.loads(cli.run_commands(commands=["dump interface status all"], host="10.0.0.9"))

    result = response["run"]["results"][0]
    assert result["truncated"] is True
    assert result["output_bytes"] == 100
    assert result["output_bytes_total"] == 5000


# --- Tool-level (task 7.2/7.3) --------------------------------------------


def test_run_commands_is_registered_not_read_only_not_idempotent_non_destructive():
    import prisma_sdwan_mcp.server as server

    tools = asyncio.run(server.mcp.list_tools())
    run_commands_tool = next(t for t in tools if t.name == "run_commands")

    assert run_commands_tool.annotations.readOnlyHint is False
    assert run_commands_tool.annotations.idempotentHint is False
    assert run_commands_tool.annotations.destructiveHint is False
    assert len(tools) == 27


def test_no_credential_value_appears_in_any_response(monkeypatch):
    monkeypatch.setattr(cli, "get_ion_credentials", lambda: ("reader", "s3cr3t-value", None, None))

    # configuration-adjacent success path
    monkeypatch.setattr(
        cli,
        "execute_commands",
        lambda **kwargs: {
            "status": "ok",
            "results": [{"command": "dump interface status all", "status": "ok", "output": "clean", "truncated": False}],
        },
    )
    ok_response = cli.run_commands(commands=["dump interface status all"], host="10.0.0.9")
    assert "s3cr3t-value" not in ok_response

    # every connection-stage failure path
    for error_type in ("unreachable", "host_key", "authentication", "connection", "validation"):
        def fake_execute_commands(et=error_type, **kwargs):
            return {
                "status": "error",
                "error": {"type": et, "message": f"boom for {et}"},
                "results": [],
            }

        monkeypatch.setattr(cli, "execute_commands", fake_execute_commands)
        error_response = cli.run_commands(commands=["dump interface status all"], host="10.0.0.9")
        assert "s3cr3t-value" not in error_response

    # policy denial path (credentials never even looked at)
    monkeypatch.setattr(cli, "get_ion_credentials", _no_call)
    denied_response = cli.run_commands(commands=["debug reboot"], host="10.0.0.9")
    assert "s3cr3t-value" not in denied_response
