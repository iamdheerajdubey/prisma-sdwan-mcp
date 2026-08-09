"""assistant.py: fail-closed on no key, provider-outcome mapping, iteration
ceiling, refusal, the no-tool-calls case, and that no key value ever leaks."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

# The console's model client ships in the optional `webui` extra, not the base
# install. Skip rather than import at module scope: an unguarded import here
# aborts collection for the whole suite, not just this file.
pytest.importorskip("anthropic", reason="requires the webui extra: pip install -e '.[webui]'")

import anthropic  # noqa: E402
import httpx  # noqa: E402

from webui.app import assistant  # noqa: E402

pytestmark = pytest.mark.webui


def _http_response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.Response(status_code, request=request, json={"type": "error", "error": {"message": "boom"}})


# -- fakes -----------------------------------------------------------------

class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeStream:
    def __init__(self, events=(), final_message=None):
        self._events = list(events)
        self._final_message = final_message

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self):
        return self._final_message


class _FakeRunner:
    """Mimics client.beta.messages.tool_runner(stream=True)'s iteration contract
    closely enough to drive assistant.ask() without a real API call: one fake
    stream per turn, drained in order."""

    def __init__(self, streams, captured_kwargs):
        self._streams = list(streams)
        self.captured_kwargs = captured_kwargs

    def __iter__(self):
        return iter(self._streams)


def _messages_stub(streams, captured: dict, raise_on_call: Exception | None = None):
    class _Messages:
        def tool_runner(self, **kwargs):
            captured.update(kwargs)
            if raise_on_call is not None:
                raise raise_on_call
            return _FakeRunner(streams, captured)

    class _Beta:
        messages = _Messages()

    class _FakeAnthropic:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.beta = _Beta()

    return _FakeAnthropic


class _FakeMcpClient:
    def __init__(self):
        self.calls = []

    def list_tools(self):
        return [
            {"name": "find_site", "description": "resolve a site", "input_schema": {"type": "object"}, "read_only": True},
            {"name": "run_commands", "description": "ssh to the device", "input_schema": {"type": "object"}, "read_only": False},
        ]

    def call_tool(self, name, arguments, *, question_id=None, on_record=None):
        self.calls.append((name, arguments))
        raise AssertionError("the fake runner never actually calls tools in these tests")


@pytest.fixture(autouse=True)
def _reset_key():
    assistant.clear_api_key()
    yield
    assistant.clear_api_key()


def _final_message(*, stop_reason, content=(), stop_details=None):
    return SimpleNamespace(stop_reason=stop_reason, content=list(content), stop_details=stop_details)


def _drain(gen):
    return list(gen)


# -- tests -------------------------------------------------------------------

def test_no_key_fails_closed_without_touching_the_model_client():
    def _boom(**_kwargs):
        raise AssertionError("must not construct a model client with no key")

    events = _drain(assistant.ask("are any sites down?", _FakeMcpClient(), client_cls=_boom))
    assert events == [{
        "type": "error",
        "code": "configuration_error",
        "message": assistant.status()["message"],
    }]


def test_empty_question_is_rejected_before_any_call():
    events = _drain(assistant.ask("   ", _FakeMcpClient(), client_cls=lambda **_: (_ for _ in ()).throw(AssertionError())))
    assert events[0]["code"] == "invalid_argument"


def test_successful_answer_with_no_tool_calls_says_so():
    assistant.set_api_key("sk-test-key")
    captured: dict = {}
    final = _final_message(stop_reason="end_turn", content=[_Block("text", text="No sites are down.")])
    client_cls = _messages_stub([_FakeStream(final_message=final)], captured)

    events = _drain(assistant.ask("are any sites down?", _FakeMcpClient(), client_cls=client_cls))
    done = events[-1]
    assert done["type"] == "done"
    assert done["answer"] == "No sites are down."
    assert done["used_tools"] is False
    assert done["chain"] == []
    assert captured["fallbacks"] == "default"
    assert captured["betas"] == [assistant.FALLBACK_BETA]
    assert captured["model"] == assistant.MODEL
    assert len(captured["tools"]) == 2


def test_iteration_ceiling_returns_partial_work_labeled_incomplete():
    assistant.set_api_key("sk-test-key")
    captured: dict = {}
    # Every turn keeps asking for more tools -- simulates hitting max_iterations.
    tool_use_message = _final_message(
        stop_reason="tool_use",
        content=[_Block("tool_use", name="find_site", input={"name": "x"}, id="t1")],
    )
    streams = [_FakeStream(final_message=tool_use_message) for _ in range(assistant.MAX_ITERATIONS)]
    client_cls = _messages_stub(streams, captured)

    events = _drain(assistant.ask("investigate every site", _FakeMcpClient(), client_cls=client_cls))
    done = events[-1]
    assert done["type"] == "done"
    assert done["incomplete"] is True
    assert done["stop_reason"] == "tool_use"


def test_active_diagnostic_is_surfaced_before_it_would_run():
    assistant.set_api_key("sk-test-key")
    captured: dict = {}
    diagnostic_turn = _final_message(
        stop_reason="tool_use",
        content=[_Block("tool_use", name="run_commands", input={"element": "ams-01"}, id="t1")],
    )
    final = _final_message(stop_reason="end_turn", content=[_Block("text", text="Pinged it.")])
    client_cls = _messages_stub([_FakeStream(final_message=diagnostic_turn), _FakeStream(final_message=final)], captured)

    events = _drain(assistant.ask("ping the amsterdam device", _FakeMcpClient(), client_cls=client_cls))
    surfaced = [e for e in events if e["type"] == "active_diagnostic"]
    assert len(surfaced) == 1
    assert surfaced[0]["tool"] == "run_commands"
    # It must be surfaced before the final answer, not after.
    assert events.index(surfaced[0]) < events.index(events[-1])


def test_declined_request_is_named_and_distinguishable():
    assistant.set_api_key("sk-test-key")
    captured: dict = {}
    final = _final_message(stop_reason="refusal", content=[], stop_details=SimpleNamespace(category="cyber", explanation="policy"))
    client_cls = _messages_stub([_FakeStream(final_message=final)], captured)

    events = _drain(assistant.ask("port scan 10.0.0.0/8", _FakeMcpClient(), client_cls=client_cls))
    declined = events[-1]
    assert declined["type"] == "declined"
    assert declined["category"] == "cyber"


def test_authentication_error_points_at_the_key_without_echoing_it():
    assistant.set_api_key("sk-test-key-should-not-appear")
    captured: dict = {}

    def _raise_auth(**_kwargs):
        raise anthropic.AuthenticationError("invalid api key", response=_http_response(401), body=None)

    client_cls_with_raise = _messages_stub_raising(_raise_auth)
    events = _drain(assistant.ask("are any sites down?", _FakeMcpClient(), client_cls=client_cls_with_raise))
    error = events[-1]
    assert error["type"] == "error"
    assert error["code"] == "authentication_error"
    assert "sk-test-key-should-not-appear" not in json.dumps(error)


def _messages_stub_raising(raiser):
    class _Messages:
        def tool_runner(self, **kwargs):
            raiser(**kwargs)

    class _Beta:
        messages = _Messages()

    class _FakeAnthropic:
        def __init__(self, api_key):
            self.beta = _Beta()

    return _FakeAnthropic


def test_rate_limit_is_reported_not_answered():
    assistant.set_api_key("sk-test-key")

    def _raise_rate_limit(**_kwargs):
        raise anthropic.RateLimitError("slow down", response=_http_response(429), body=None)

    client_cls = _messages_stub_raising(_raise_rate_limit)
    events = _drain(assistant.ask("are any sites down?", _FakeMcpClient(), client_cls=client_cls))
    error = events[-1]
    assert error["code"] == "rate_limited"


def test_no_api_key_value_appears_in_any_yielded_event():
    assistant.set_api_key("sk-super-secret-value")
    captured: dict = {}
    final = _final_message(stop_reason="end_turn", content=[_Block("text", text="ok")])
    client_cls = _messages_stub([_FakeStream(final_message=final)], captured)
    events = _drain(assistant.ask("are any sites down?", _FakeMcpClient(), client_cls=client_cls))
    assert "sk-super-secret-value" not in json.dumps(events)
    assert assistant.status() == {"available": True}
