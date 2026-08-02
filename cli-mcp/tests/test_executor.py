import json
import re

from prisma_sdwan_cli_mcp.executor import (
    DEFAULT_MAX_OUTPUT_BYTES,
    build_connection_kwargs,
    execute_commands,
    get_max_output_bytes,
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
    output = "\u3042" * 100

    response = _run([output], ["dump interface status all"], max_output_bytes=50)

    kept = response["results"][0]["output"]
    assert kept == "\u3042" * 16
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


def test_max_output_bytes_env_var_falls_back_to_the_default_on_garbage(monkeypatch):
    for garbage in ("", "lots", "0", "-1", "40960.5"):
        monkeypatch.setenv("PRISMA_CLI_MCP_MAX_OUTPUT_BYTES", garbage)
        assert get_max_output_bytes() == DEFAULT_MAX_OUTPUT_BYTES

    monkeypatch.delenv("PRISMA_CLI_MCP_MAX_OUTPUT_BYTES", raising=False)
    assert get_max_output_bytes() == DEFAULT_MAX_OUTPUT_BYTES

    monkeypatch.setenv("PRISMA_CLI_MCP_MAX_OUTPUT_BYTES", "128")
    assert get_max_output_bytes() == 128


def test_env_var_bounds_output_when_no_explicit_override_is_given(monkeypatch):
    monkeypatch.setenv("PRISMA_CLI_MCP_MAX_OUTPUT_BYTES", "64")

    response = _run(["w" * 5000], ["dump interface status all"])

    assert response["results"][0]["output"] == "w" * 64
    assert response["results"][0]["output_bytes_total"] == 5000
