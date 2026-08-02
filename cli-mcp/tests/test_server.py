import asyncio
import json

import prisma_sdwan_cli_mcp.server as server


def test_only_one_generic_tool_is_registered():
    tools = asyncio.run(server.mcp.list_tools())

    assert [tool.name for tool in tools] == ["run_commands"]
    tool = tools[0]
    assert set(tool.parameters["properties"]) == {
        "host",
        "port",
        "username",
        "commands",
        "password",
        "private_key",
        "private_key_passphrase",
        "known_hosts_file",
    }
    assert set(tool.parameters["required"]) == {"host", "port", "username", "commands"}


def test_policy_denial_happens_before_backend(monkeypatch):
    backend_calls = []

    def backend(**kwargs):
        backend_calls.append(kwargs)
        raise AssertionError("backend must not be called for a denied batch")

    monkeypatch.setattr(server, "execute_commands", backend)
    response = server.run_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all", "config interface eth0"],
    )

    assert response["status"] == "denied"
    assert response["error"]["type"] == "policy"
    assert [result["status"] for result in response["results"]] == ["denied", "denied"]
    assert backend_calls == []
    assert "secret" not in json.dumps(response)


def test_valid_batch_is_forwarded_and_response_stays_structured(monkeypatch):
    calls = []

    def backend(**kwargs):
        calls.append(kwargs)
        return {
            "status": "ok",
            "results": [
                {
                    "command": "dump interface status all",
                    "status": "ok",
                    "output": "interface output",
                },
                {
                    "command": "inspect system arp all",
                    "status": "error",
                    "error": "Invalid command",
                },
            ],
        }

    monkeypatch.setattr(server, "execute_commands", backend)
    response = server.run_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        commands=["dump interface status all", "inspect system arp all"],
    )

    assert calls[0]["host"] == "ion.example"
    assert calls[0]["commands"] == ["dump interface status all", "inspect system arp all"]
    assert response["results"][0]["output"] == "interface output"
    assert response["results"][1]["error"] == "Invalid command"
    assert "interface output" in json.dumps(response)


def test_connection_input_errors_are_structured_without_echoing_credentials():
    response = server.run_commands(
        host="ion.example",
        port=22,
        username="reader",
        password="secret",
        private_key="private-key-material",
        commands=["dump interface status all"],
    )

    assert response == {
        "status": "error",
        "error": {"type": "validation", "message": "provide exactly one of password or private_key"},
        "results": [],
    }
    assert "secret" not in json.dumps(response)
