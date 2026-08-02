import json

from prisma_sdwan_cli_mcp.executor import build_connection_kwargs, execute_commands


class FakeSession:
    def __init__(self, outputs=None):
        self.outputs = list(outputs or [])
        self.commands = []
        self.writes = []
        self.disconnected = False

    def send_command_timing(self, command, **kwargs):
        self.commands.append(command)
        return self.outputs.pop(0) if self.outputs else "ok"

    def send_command(self, command):
        self.commands.append(command)
        return "ok"

    def write_channel(self, value):
        self.writes.append(value)

    def read_channel_timing(self, **kwargs):
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
            {"command": "dump interface status all", "status": "ok", "output": "interfaces"},
            {"command": "dump routing summary", "status": "ok", "output": "routes"},
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
