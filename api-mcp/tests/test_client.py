import threading
import time
from types import SimpleNamespace

from prisma_sdwan_mcp.client import PrismaSDWANClient
import prisma_sdwan_mcp.client as client_module


def _response(status_code, content=None, cgx_status=False):
    return SimpleNamespace(
        status_code=status_code,
        cgx_status=cgx_status,
        cgx_content=content or {"_error": [{"message": f"HTTP {status_code}"}]},
    )


def _ready_client():
    client = PrismaSDWANClient()
    client.logged_in = True
    client.token_expiry = client_module.time.time() + 60
    return client


def test_invoke_retries_rate_limit_then_succeeds(monkeypatch):
    client = _ready_client()
    responses = iter(
        [
            _response(429),
            _response(200, {"items": [{"id": "ok"}]}, cgx_status=True),
        ]
    )
    calls = []
    monkeypatch.setattr(client_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(client_module.random, "uniform", lambda *_: 0)

    def sdk_call():
        calls.append(True)
        return next(responses)

    result = client._invoke(sdk_call)

    assert result == [{"id": "ok"}]
    assert len(calls) == 2


def test_invoke_does_not_retry_bad_request(monkeypatch):
    client = _ready_client()
    calls = []

    def sdk_call():
        calls.append(True)
        return _response(400)

    result = client._invoke(sdk_call)

    assert result["status_code"] == 400
    assert len(calls) == 1


def test_login_is_single_flight_and_uses_response_lifetime(monkeypatch):
    client = PrismaSDWANClient()
    login_calls = []
    monkeypatch.setattr(
        client_module,
        "get_credentials",
        lambda: ("client", "secret", "tsg"),
    )
    client.sdk = SimpleNamespace(
        interactive=SimpleNamespace(
            login_secret=lambda **_: login_calls.append(True) or {"expires_in": 900}
        ),
        get=SimpleNamespace(profile=lambda: True),
        panw_region="americas",
    )

    threads = [threading.Thread(target=client.login) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(login_calls) == 1
    assert time.time() + 830 < client.token_expiry < time.time() + 850