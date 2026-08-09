"""The question box: a real model with the MCP tool set, not a keyword router.

The model is Claude, driven by the Anthropic SDK's tool runner over tools
converted from the live MCP session. There is no keyword-to-capability table
here -- every tool call is the model's own choice against the tool's declared
schema, exactly as it would be in Claude Desktop.

Every tool invocation the model makes goes through `mcp_client.McpClient.call_tool`
-- the same call path a page uses -- so it lands in the one shared trace. This
is why the MCP tool set is converted by hand here instead of with the SDK's
`mcp_tool`/`async_mcp_tool` helpers: those bind directly to the raw MCP
session and would give the assistant a second call path that never touches
our trace or redaction.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from typing import Any, Iterator

import anthropic
from anthropic import beta_tool
from anthropic.lib.tools import ToolError as SdkToolError

from .mcp_client import McpClient, ToolError, TransportError

MODEL = "claude-opus-5"
MAX_TOKENS = 64000
DEFAULT_EFFORT = os.getenv("PRISMA_CONSOLE_ASSISTANT_EFFORT", "xhigh")
MAX_ITERATIONS = int(os.getenv("PRISMA_CONSOLE_ASSISTANT_MAX_ITERATIONS", "12"))
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = (
    "You are the network assistant embedded in a Prisma SD-WAN operator console. "
    "Answer the operator's question using the tools available to you -- they cover site "
    "and device inventory, routing, WAN/VPN state, monitoring, policy, and the other "
    "controller domains, plus one tool that runs read-only diagnostics and active pings "
    "directly against a device over SSH. Call whatever tools the question actually needs; "
    "do not answer from general knowledge or guess at data you have not retrieved. If "
    "nothing in the tool set can answer the question, say so plainly and name what is "
    "missing. Keep the final answer grounded in what the tools returned and reasonably "
    "concise -- the operator can see every tool call and its full result separately in "
    "the console's trace panel."
)

_lock = threading.Lock()
_api_key: str | None = None


def set_api_key(value: str) -> None:
    global _api_key
    value = (value or "").strip()
    with _lock:
        _api_key = value or None


def clear_api_key() -> None:
    global _api_key
    with _lock:
        _api_key = None


def _resolve_key() -> str | None:
    with _lock:
        if _api_key:
            return _api_key
    # Fallback for local development. Read-only -- never assigned into os.environ
    # ourselves, since that would hand the key to the MCP server subprocess too.
    return os.environ.get("ANTHROPIC_API_KEY") or None


def status() -> dict[str, Any]:
    if _resolve_key():
        return {"available": True}
    return {
        "available": False,
        "reason": "configuration_error",
        "message": "No Anthropic API key is configured. Paste one in Administration, or set ANTHROPIC_API_KEY before starting the console.",
    }


def _make_tool(tool_def: dict[str, Any], client: McpClient, question_id: str, chain: list[dict[str, Any]]):
    name = tool_def["name"]

    def call_mcp(**kwargs: Any) -> str:
        def _link(record: Any) -> None:
            chain.append({
                "trace_id": record.id,
                "tool": record.tool,
                "arguments": record.arguments,
                "outcome": record.outcome,
            })

        try:
            result = client.call_tool(name, kwargs, question_id=question_id, on_record=_link)
            return json.dumps(result)
        except ToolError as exc:
            raise SdkToolError(json.dumps(exc.error)) from exc
        except TransportError as exc:
            raise SdkToolError(json.dumps({"code": "transport_error", "message": str(exc)})) from exc

    return beta_tool(call_mcp, name=name, description=tool_def["description"], input_schema=tool_def["input_schema"])


def _build_tools(client: McpClient, question_id: str, chain: list[dict[str, Any]]) -> tuple[list[Any], dict[str, bool]]:
    tool_defs = sorted(client.list_tools(), key=lambda item: item["name"])
    read_only = {item["name"]: item.get("read_only", True) for item in tool_defs}
    tools = [_make_tool(item, client, question_id, chain) for item in tool_defs]
    return tools, read_only


def ask(question: str, client: McpClient, *, client_cls: Any = anthropic.Anthropic) -> Iterator[dict[str, Any]]:
    """Answer one question. Yields NDJSON-ready event dicts; never raises."""
    question = (question or "").strip()
    if not question:
        yield {"type": "error", "code": "invalid_argument", "message": "Ask a question first."}
        return

    key = _resolve_key()
    if not key:
        yield {"type": "error", "code": "configuration_error", "message": status()["message"]}
        return

    question_id = uuid.uuid4().hex[:12]
    chain: list[dict[str, Any]] = []
    try:
        tools, read_only = _build_tools(client, question_id, chain)
    except (ToolError, TransportError) as exc:
        yield {"type": "error", "code": "transport_error", "message": f"Could not reach the MCP session: {exc}"}
        return

    model_client = client_cls(api_key=key)
    yield {"type": "started", "question_id": question_id}

    try:
        runner = model_client.beta.messages.tool_runner(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            # cache breakpoint: tools + system are byte-identical across questions in
            # a session; the question is the only volatile content, and it comes after.
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": DEFAULT_EFFORT},
            fallbacks="default",
            betas=[FALLBACK_BETA],
            max_iterations=MAX_ITERATIONS,
            tools=tools,
            messages=[{"role": "user", "content": question}],
            stream=True,
        )

        iterations = 0
        flushed = 0
        final_message = None
        for stream in runner:
            iterations += 1
            for entry in chain[flushed:]:
                yield {"type": "tool_result", **entry}
            flushed = len(chain)

            for event in stream:
                if event.type != "content_block_delta":
                    continue
                delta = event.delta
                if getattr(delta, "type", None) == "text_delta":
                    yield {"type": "answer_delta", "text": delta.text}
                elif getattr(delta, "type", None) == "thinking_delta":
                    yield {"type": "thinking_delta", "text": delta.thinking}

            final_message = stream.get_final_message()

            if final_message.stop_reason == "refusal":
                break

            for block in final_message.content:
                if block.type == "tool_use" and not read_only.get(block.name, True):
                    yield {"type": "active_diagnostic", "tool": block.name, "arguments": block.input}

        for entry in chain[flushed:]:
            yield {"type": "tool_result", **entry}

        if final_message is None:
            yield {"type": "error", "code": "empty_response", "message": "The model returned nothing."}
            return

        # Refusals are checked before content is read anywhere above and here.
        if final_message.stop_reason == "refusal":
            details = final_message.stop_details
            yield {
                "type": "declined",
                "category": getattr(details, "category", None) if details else None,
                "message": (getattr(details, "explanation", None) if details else None) or "The model declined to answer this question.",
                "chain": chain,
            }
            return

        answer_text = "".join(block.text for block in final_message.content if block.type == "text")
        incomplete = final_message.stop_reason == "tool_use" and iterations >= MAX_ITERATIONS
        yield {
            "type": "done",
            "answer": answer_text,
            "incomplete": incomplete,
            "stop_reason": final_message.stop_reason,
            "chain": chain,
            "used_tools": bool(chain),
        }
    except anthropic.AuthenticationError:
        yield {"type": "error", "code": "authentication_error", "message": "The Anthropic API key was rejected. Replace it in Administration."}
    except anthropic.RateLimitError:
        yield {"type": "error", "code": "rate_limited", "message": "The model provider is rate-limiting requests. Try again shortly."}
    except anthropic.APIConnectionError as exc:
        yield {"type": "error", "code": "provider_unavailable", "message": f"Could not reach the model provider: {exc}"}
    except anthropic.APIStatusError as exc:
        code = "provider_unavailable" if exc.status_code >= 500 else "provider_error"
        yield {"type": "error", "code": code, "message": str(exc)}
