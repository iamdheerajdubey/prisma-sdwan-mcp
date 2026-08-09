import json
import re
import socket

import pytest

from prisma_sdwan_mcp.cli.ssh import (
    DEFAULT_MAX_OUTPUT_BYTES,
    IONUnreachableError,
    build_connection_kwargs,
    execute_commands,
    probe_reachable,
)
from prisma_sdwan_mcp.config import get_ion_max_output_bytes


@pytest.fixture(autouse=True)
def no_real_network_probe(monkeypatch):
    """These tests exercise the Netmiko session layer with a fake connection
    factory and never touch a real device, so the reachability probe (a real
    TCP connect) is stubbed out here. Reachability itself is covered by the
    dedicated tests below."""
    monkeypatch.setattr(
        "prisma_sdwan_mcp.cli.ssh.probe_reachable",
        lambda host, port, timeout: None,
    )


class FakeSession:
    def __init__(self, outputs=None, prompt="I390ION1#"):
        self.outputs = list(outputs or [])
        self.prompt = prompt
        self.commands = []
        self.writes = []
        self.expects = []
        self.disconnected = False

    def find_prompt(self):
        return self.prompt

    def send_command(self, command, **kwargs):
        self.commands.append(command)
        self.expects.append(kwargs.get("expect_string"))
        return self.outputs.pop(0) if self.outputs else "ok"

    def write_channel(self, value):
        self.writes.append(value)

    def read_until_pattern(self, **kwargs):
        return "page 2"

    def disconnect(self):
        self.disconnected = True


def test_single_connection_executes_multiple_commands_and_disconnects():
    session = FakeSession(["interfaces", "routes"])
    calls = []

    def connect(**kwargs):
        calls.append(kwargs)
        return session

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret-password",
        commands=["dump interface status all", "dump routing summary"],
        connection_factory=connect,
    )

    assert response == {
        "status": "ok",
        "results": [
            {
                "command": "dump interface status all",
                "status": "ok",
                "output": "interfaces",
                "truncated": False,
            },
            {
                "command": "dump routing summary",
                "status": "ok",
                "output": "routes",
                "truncated": False,
            },
        ],
    }
    assert session.commands == ["dump interface status all", "dump routing summary"]
    assert session.disconnected is True
    assert calls[0]["device_type"] == "generic"
    assert calls[0]["password"] == "secret-password"
    assert "secret-password" not in json.dumps(response)


def test_pagination_marker_is_advanced_with_a_space():
    session = FakeSession(["page 1 --More--"])

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all"],
        connection_factory=lambda **kwargs: session,
    )

    assert response["results"][0]["output"] == "page 1 page 2"
    assert session.writes == [" "]


PING_OUTPUT = """PING 8.8.8.8 (8.8.8.8) from 156.70.134.86: 56 data bytes
64 bytes from 8.8.8.8: seq=0 ttl=116 time=2.528 ms
64 bytes from 8.8.8.8: seq=1 ttl=116 time=1.253 ms
64 bytes from 8.8.8.8: seq=2 ttl=116 time=1.308 ms
64 bytes from 8.8.8.8: seq=3 ttl=116 time=1.286 ms
64 bytes from 8.8.8.8: seq=4 ttl=116 time=1.360 ms

--- 8.8.8.8 ping statistics ---
5 packets transmitted, 5 packets received, 0% packet loss
round-trip min/avg/max = 1.253/1.547/2.528 ms"""


def test_completion_is_driven_by_the_device_prompt_not_channel_silence():
    # ping emits roughly one line per second, so the channel is quiet for ~1s
    # between packets. The previous silence-based read (send_command_timing,
    # last_read=0.3) treated that gap as "command finished" and returned a
    # single packet marked status ok. Completion must key off the prompt.
    session = FakeSession([PING_OUTPUT])

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["ping 3 8.8.8.8"],
        connection_factory=lambda **kwargs: session,
    )

    assert response["results"][0]["status"] == "ok"
    assert response["results"][0]["output"] == PING_OUTPUT
    assert re.escape(session.prompt) in session.expects[0]


def test_unreachable_ping_is_a_successful_command_with_loss_as_evidence():
    # 100% loss is the answer to the question, not a failure to run.
    session = FakeSession(
        [
            "PING 10.0.0.9 (10.0.0.9) from 156.70.134.86: 56 data bytes\n\n"
            "--- 10.0.0.9 ping statistics ---\n"
            "5 packets transmitted, 0 packets received, 100% packet loss"
        ]
    )

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["ping 3 10.0.0.9"],
        connection_factory=lambda **kwargs: session,
    )

    assert response["results"][0]["status"] == "ok"
    assert "100% packet loss" in response["results"][0]["output"]


def test_missing_prompt_fails_the_command_instead_of_returning_partial_output():
    session = FakeSession(["whatever"], prompt="   ")

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all"],
        connection_factory=lambda **kwargs: session,
    )

    assert response["results"][0]["status"] == "error"
    assert "prompt" in response["results"][0]["error"]


def test_device_reported_error_is_kept_on_its_command():
    session = FakeSession(["Invalid command: nope"])

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all"],
        connection_factory=lambda **kwargs: session,
    )

    assert response["results"] == [
        {
            "command": "dump interface status all",
            "status": "error",
            "error": "Invalid command: nope",
            "truncated": False,
        }
    ]


def test_authentication_failure_has_no_command_results():
    class NetmikoAuthenticationException(Exception):
        pass

    def connect(**kwargs):
        raise NetmikoAuthenticationException("Authentication failed for secret")

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all"],
        connection_factory=connect,
    )

    assert response["status"] == "error"
    assert response["error"]["type"] == "authentication"
    assert response["results"] == []
    assert "secret" not in json.dumps(response)


def test_connection_failure_is_distinct_from_authentication_failure():
    class NetmikoTimeoutException(Exception):
        pass

    def connect(**kwargs):
        raise NetmikoTimeoutException("timed out")

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all"],
        connection_factory=connect,
    )

    assert response["error"]["type"] == "connection"
    assert response["results"] == []


def test_interior_error_like_text_does_not_flip_a_successful_command_to_error():
    session = FakeSession(["State   Failed: 0\ninterface up\nAll good"])

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all"],
        connection_factory=lambda **kwargs: session,
    )

    assert response["results"][0]["status"] == "ok"
    assert response["results"][0]["output"] == "State   Failed: 0\ninterface up\nAll good"


def test_leading_error_text_is_still_classified_as_a_device_error():
    session = FakeSession(["Unknown command: nope"])

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all"],
        connection_factory=lambda **kwargs: session,
    )

    assert response["results"][0]["status"] == "error"


def test_host_key_failure_is_classified_distinctly_and_credentials_are_not_sent():
    class SSHHostKeyException(Exception):
        pass

    def connect(**kwargs):
        raise SSHHostKeyException("Host key for ion.example did not match")

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all"],
        connection_factory=connect,
    )

    assert response["error"]["type"] == "host_key"
    assert response["results"] == []
    assert "secret" not in json.dumps(response)


def test_default_connection_kwargs_enforce_strict_host_key_checking():
    kwargs = build_connection_kwargs(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
    )

    assert kwargs["ssh_strict"] is True
    assert kwargs["system_host_keys"] is True


def test_connection_credentials_require_exactly_one_material():
    kwargs = build_connection_kwargs(
        host="ion.example",
        port=2222,
        username="reader",
        password="secret",
    )

    assert kwargs["device_type"] == "generic"
    assert kwargs["port"] == 2222

    result = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        commands=["dump interface status all"],
        connection_factory=lambda **kwargs: FakeSession(),
    )
    assert result["error"]["type"] == "validation"
    assert result["results"] == []


def _run(outputs, commands, **kwargs):
    session = FakeSession(outputs)
    return execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=commands,
        connection_factory=lambda **_: session,
        **kwargs,
    )


def test_output_within_the_cap_is_returned_untouched_and_marked_complete():
    output = "line\n" * 10

    response = _run([output], ["dump interface status all"], max_output_bytes=1000)

    assert response["results"][0]["output"] == output
    assert response["results"][0]["truncated"] is False
    assert "output_bytes" not in response["results"][0]
    assert "output_bytes_total" not in response["results"][0]


def test_oversized_output_is_truncated_to_the_cap_and_says_so():
    output = "x" * 5000

    response = _run([output], ["dump interface status all"], max_output_bytes=100)

    result = response["results"][0]
    assert result["status"] == "ok"
    assert result["truncated"] is True
    assert result["output"] == "x" * 100
    assert result["output_bytes"] == 100
    assert result["output_bytes_total"] == 5000
    assert len(result["output"].encode("utf-8")) <= 100


def test_truncation_prefers_a_line_boundary_near_the_cap():
    output = "\n".join("row %02d" % index for index in range(100))

    response = _run([output], ["dump interface status all"], max_output_bytes=100)

    kept = response["results"][0]["output"]
    assert kept.endswith("row 13")
    assert not kept.endswith("\n")
    assert response["results"][0]["truncated"] is True


def test_truncation_never_splits_a_multi_byte_character():
    # 3 bytes per character: the cap lands mid-character on purpose.
    output = "あ" * 100

    response = _run([output], ["dump interface status all"], max_output_bytes=50)

    kept = response["results"][0]["output"]
    assert kept == "あ" * 16
    assert len(kept.encode("utf-8")) == 48
    assert response["results"][0]["output_bytes"] == 48
    assert response["results"][0]["output_bytes_total"] == 300


def test_cap_is_applied_per_command_not_per_batch():
    response = _run(
        ["y" * 5000, "small output"],
        ["dump interface status all", "dump routing summary"],
        max_output_bytes=100,
    )

    oversized, sibling = response["results"]
    assert oversized["truncated"] is True
    assert oversized["output_bytes_total"] == 5000
    assert sibling["truncated"] is False
    assert sibling["output"] == "small output"


def test_truncated_device_error_is_still_reported_as_an_error():
    response = _run(
        ["Invalid command: " + "z" * 5000],
        ["dump interface status all"],
        max_output_bytes=100,
    )

    result = response["results"][0]
    assert result["status"] == "error"
    assert result["truncated"] is True
    assert result["error"].startswith("Invalid command: ")


def test_long_command_error_is_redacted_clipped_and_signalled():
    class LongErrorSession(FakeSession):
        def send_command(self, command, **kwargs):
            raise RuntimeError("sentinel-password-" + "x" * 1200)

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="sentinel-password",
        commands=["dump interface status all"],
        connection_factory=lambda **kwargs: LongErrorSession(),
    )

    result = response["results"][0]
    assert result["status"] == "error"
    assert result["error_truncated"] is True
    assert len(result["error"]) == 1000
    assert "sentinel-password" not in result["error"]


def test_max_output_bytes_env_var_is_read_through_the_shared_config_accessor(monkeypatch):
    # ssh.py no longer owns its own env parsing (task 3.2); config.py's
    # shared _int_env accessor now decides the default, consistent with
    # every other MCPv2 byte-budget setting.
    monkeypatch.delenv("PRISMA_ION_MAX_OUTPUT_BYTES", raising=False)
    assert get_ion_max_output_bytes() == DEFAULT_MAX_OUTPUT_BYTES

    monkeypatch.setenv("PRISMA_ION_MAX_OUTPUT_BYTES", "128")
    assert get_ion_max_output_bytes() == 128


def test_env_var_bounds_output_when_no_explicit_override_is_given(monkeypatch):
    monkeypatch.setenv("PRISMA_ION_MAX_OUTPUT_BYTES", "64")

    response = _run(["w" * 5000], ["dump interface status all"])

    assert response["results"][0]["output"] == "w" * 64
    assert response["results"][0]["output_bytes_total"] == 5000


# --- Reachability probe (task 3.3/3.4/3.5) -----------------------------


def test_probe_failure_is_reported_as_unreachable_before_any_connection_attempt():
    connection_calls = []

    def connect(**kwargs):
        connection_calls.append(kwargs)
        raise AssertionError("connection factory must not run when the probe fails")

    def failing_probe(host, port, timeout):
        raise IONUnreachableError(host, port, "connection refused")

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all"],
        connection_factory=connect,
        probe_factory=failing_probe,
    )

    assert response["status"] == "error"
    assert response["error"]["type"] == "unreachable"
    assert "ion.example" in response["error"]["message"]
    assert "22" in response["error"]["message"]
    assert response["results"] == []
    assert connection_calls == []


def test_unreachable_is_distinct_from_authentication_host_key_and_connection():
    def unreachable_probe(host, port, timeout):
        raise IONUnreachableError(host, port, "timed out")

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all"],
        connection_factory=lambda **kwargs: FakeSession(),
        probe_factory=unreachable_probe,
    )

    assert response["error"]["type"] not in {"authentication", "host_key", "connection"}
    assert response["error"]["type"] == "unreachable"


def test_a_reachable_device_that_refuses_the_handshake_is_a_connection_error_not_unreachable():
    def connect(**kwargs):
        raise ConnectionRefusedError("refused")

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all"],
        connection_factory=connect,
        probe_factory=lambda host, port, timeout: None,
    )

    assert response["error"]["type"] == "connection"


@pytest.mark.parametrize(
    "error_type,connect_error",
    [
        ("host_key", "SSHHostKeyException"),
        ("authentication", "NetmikoAuthenticationException"),
        ("connection", "NetmikoTimeoutException"),
    ],
)
def test_no_connection_stage_failure_ever_retries(error_type, connect_error):
    """No automatic retry with host-key checking relaxed, a different
    credential, or a different address -- for any of the four connection-
    stage failure types."""
    attempts = []

    def connect(**kwargs):
        attempts.append(kwargs)
        raise type(connect_error, (Exception,), {})("boom")

    response = execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all"],
        connection_factory=connect,
    )

    assert response["error"]["type"] == error_type
    assert len(attempts) == 1


def test_real_probe_succeeds_against_a_reachable_local_listener():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()
    try:
        probe_reachable(host, port, timeout=1.0)
    finally:
        server.close()


def test_real_probe_raises_unreachable_against_a_closed_local_port():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    host, port = server.getsockname()
    server.close()  # bound then immediately closed: nothing is listening

    with pytest.raises(IONUnreachableError) as exc:
        probe_reachable(host, port, timeout=1.0)
    assert host in str(exc.value)
    assert str(port) in str(exc.value)


def test_unreachable_probe_failure_is_never_retried():
    attempts = []

    def probe(host, port, timeout):
        attempts.append((host, port))
        raise IONUnreachableError(host, port, "no route")

    execute_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all"],
        connection_factory=lambda **kwargs: FakeSession(),
        probe_factory=probe,
    )

    assert len(attempts) == 1
