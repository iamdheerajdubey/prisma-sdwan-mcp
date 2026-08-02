import json

import pytest

import prisma_sdwan_cli_mcp.executor as executor
from prisma_sdwan_cli_mcp.server import run_commands


class IntegrationSession:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.commands = []
        self.disconnected = False

    def send_command_timing(self, command, **kwargs):
        self.commands.append(command)
        return self.outputs.pop(0)

    def disconnect(self):
        self.disconnected = True


@pytest.fixture
def install_fake_connection(monkeypatch):
    sessions = []

    def install(outputs):
        session = IntegrationSession(outputs)
        sessions.append(session)
        monkeypatch.setattr(executor, "_default_connection_factory", lambda **kwargs: session)
        return session

    return install


def test_single_multi_and_mixed_status_batches(install_fake_connection):
    session = install_fake_connection(["interface output", "Invalid command: nope"])

    response = run_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all", "inspect system arp all"],
    )

    assert response["status"] == "ok"
    assert [result["status"] for result in response["results"]] == ["ok", "error"]
    assert response["results"][0]["output"] == "interface output"
    assert response["results"][1]["error"] == "Invalid command: nope"
    assert session.commands == ["dump interface status all", "inspect system arp all"]
    assert session.disconnected is True


def test_denied_command_prevents_connection_and_all_execution(monkeypatch):
    connection_calls = []

    def connection(**kwargs):
        connection_calls.append(kwargs)
        raise AssertionError("denied batch must not open a connection")

    monkeypatch.setattr(executor, "_default_connection_factory", connection)
    response = run_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all", "config interface eth0"],
    )

    assert response["status"] == "denied"
    assert len(response["results"]) == 2
    assert all(result["status"] == "denied" for result in response["results"])
    assert connection_calls == []


def test_connection_and_auth_failures_are_batch_level_errors(monkeypatch):
    class NetmikoTimeoutException(Exception):
        pass

    class NetmikoAuthenticationException(Exception):
        pass

    monkeypatch.setattr(
        executor,
        "_default_connection_factory",
        lambda **kwargs: (_ for _ in ()).throw(NetmikoTimeoutException("timeout")),
    )
    connection_response = run_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all"],
    )

    monkeypatch.setattr(
        executor,
        "_default_connection_factory",
        lambda **kwargs: (_ for _ in ()).throw(
            NetmikoAuthenticationException("authentication failed")
        ),
    )
    auth_response = run_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all"],
    )

    assert connection_response["error"]["type"] == "connection"
    assert auth_response["error"]["type"] == "authentication"
    assert connection_response["results"] == []
    assert auth_response["results"] == []


def test_realistic_multi_command_response_remains_bounded(install_fake_connection):
    install_fake_connection(["interface status\n" * 40] * 8)
    commands = ["dump interface status all"] * 8

    response = run_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=commands,
    )

    encoded = json.dumps(response)
    assert len(response["results"]) == len(commands)
    assert len(encoded) < 50_000
