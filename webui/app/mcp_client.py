"""MCP stdio client for the console.

Speaks the Model Context Protocol to ``prisma-sdwan-mcp`` exactly like any
other MCP host (Claude Desktop included) -- no import of the server package,
no access to its internals. One session is opened on a background asyncio
event loop and shared across the stdlib HTTP server's request threads.
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
import threading
import time
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .trace import TRACE

DEFAULT_COMMAND = "prisma-sdwan-mcp"
DEFAULT_ARGS = ("--transport", "stdio")
_CONNECT_TIMEOUT = 30
_CALL_TIMEOUT = 120

# The four keys the server's structured_error() always sets together
# (prisma_sdwan_mcp/response.py). Their joint presence -- not any one key
# alone -- is what marks a parsed response as our error envelope rather than
# an ordinary payload that happens to use one of these names.
_ERROR_ENVELOPE_KEYS = ("code", "message", "tool", "retryable")


class TransportError(Exception):
    """The MCP session could not be established, or was lost mid-call."""


class ToolError(Exception):
    """The tool ran and returned the server's own structured error."""

    def __init__(self, error: dict[str, Any]):
        self.error = error
        super().__init__(str(error.get("message") or "tool call failed"))


def _looks_like_error_envelope(value: Any) -> bool:
    return isinstance(value, dict) and all(key in value for key in _ERROR_ENVELOPE_KEYS)


class McpClient:
    """One MCP stdio session, opened lazily and reused for every call."""

    def __init__(
        self,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._command = command or os.getenv("PRISMA_CONSOLE_MCP_COMMAND", DEFAULT_COMMAND)
        if args is not None:
            self._args = list(args)
        else:
            configured = os.getenv("PRISMA_CONSOLE_MCP_ARGS")
            self._args = shlex.split(configured) if configured else list(DEFAULT_ARGS)
        self._env = env
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: ClientSession | None = None
        self._session_cm: Any = None
        self._stdio_cm: Any = None
        self._ready = threading.Event()
        self._start_error: BaseException | None = None
        self._lock = threading.Lock()

    # -- lifecycle -----------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="mcp-client-loop")
            self._thread.start()
        if not self._ready.wait(timeout=_CONNECT_TIMEOUT):
            raise TransportError("timed out starting the MCP server subprocess")
        if self._start_error is not None:
            raise TransportError(f"could not start MCP session: {self._start_error}") from self._start_error

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._connect())
        except BaseException as exc:  # noqa: BLE001 - reported to the waiting start() caller
            self._start_error = exc
            self._ready.set()
            return
        self._ready.set()
        loop.run_forever()

    async def _connect(self) -> None:
        params = StdioServerParameters(command=self._command, args=self._args, env=self._env)
        self._stdio_cm = stdio_client(params)
        read, write = await self._stdio_cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()

    def close(self) -> None:
        loop = self._loop
        if loop is None:
            return

        async def _shutdown() -> None:
            if self._session_cm is not None:
                await self._session_cm.__aexit__(None, None, None)
            if self._stdio_cm is not None:
                await self._stdio_cm.__aexit__(None, None, None)

        try:
            future = asyncio.run_coroutine_threadsafe(_shutdown(), loop)
            future.result(timeout=10)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._loop = None
        self._session = None

    @property
    def connected(self) -> bool:
        return self._session is not None and self._start_error is None

    # -- calls -----------------------------------------------------------

    def _run(self, coro_factory: Any) -> Any:
        if self._loop is None or self._session is None:
            raise TransportError("MCP session is not connected")
        future = asyncio.run_coroutine_threadsafe(coro_factory(), self._loop)
        try:
            return future.result(timeout=_CALL_TIMEOUT)
        except TransportError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalized into TransportError for the caller
            raise TransportError(str(exc)) from exc

    def list_tools(self) -> list[dict[str, Any]]:
        return self._run(self._list_tools)

    async def _list_tools(self) -> list[dict[str, Any]]:
        listing = await self._session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema or {},
                # An active diagnostic (run_commands) is the one tool whose annotations
                # mark it not read-only; the assistant surfaces it before running it.
                "read_only": tool.annotations.readOnlyHint if tool.annotations and tool.annotations.readOnlyHint is not None else True,
            }
            for tool in listing.tools
        ]

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        question_id: str | None = None,
        on_record: Any = None,
    ) -> dict[str, Any]:
        """`on_record`, if given, is called with the `TraceRecord` written for this
        call -- the assistant loop uses it to link its own call chain to the trace
        without a second, racy lookup into the shared trace ring."""
        arguments = arguments or {}
        started = time.monotonic()
        try:
            raw_text, parsed, is_protocol_error = self._run(lambda: self._call_tool(name, arguments))
        except TransportError as exc:
            record = TRACE.record(
                tool=name,
                arguments=arguments,
                elapsed_ms=(time.monotonic() - started) * 1000,
                outcome="transport_error",
                error={"code": "transport_error", "message": str(exc)},
                question_id=question_id,
            )
            if on_record:
                on_record(record)
            raise

        elapsed_ms = (time.monotonic() - started) * 1000
        raw_bytes = len(raw_text.encode("utf-8")) if raw_text else 0

        if is_protocol_error:
            error = parsed if isinstance(parsed, dict) else {}
            error.setdefault("code", "protocol_error")
            error.setdefault("message", raw_text or "tool call failed")
            record = TRACE.record(
                tool=name,
                arguments=arguments,
                elapsed_ms=elapsed_ms,
                outcome="tool_error",
                raw_bytes=raw_bytes,
                error=error,
                question_id=question_id,
            )
            if on_record:
                on_record(record)
            raise ToolError(error)

        if _looks_like_error_envelope(parsed):
            record = TRACE.record(
                tool=name,
                arguments=arguments,
                elapsed_ms=elapsed_ms,
                outcome="tool_error",
                raw_bytes=raw_bytes,
                error=parsed,
                question_id=question_id,
            )
            if on_record:
                on_record(record)
            raise ToolError(parsed)

        record = TRACE.record(
            tool=name,
            arguments=arguments,
            elapsed_ms=elapsed_ms,
            outcome="ok",
            response=parsed if isinstance(parsed, dict) else {},
            raw_bytes=raw_bytes,
            question_id=question_id,
        )
        if on_record:
            on_record(record)
        return parsed

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> tuple[str, Any, bool]:
        result = await self._session.call_tool(name, arguments)
        text_parts = [block.text for block in result.content if getattr(block, "type", None) == "text"]
        raw_text = "\n".join(text_parts)
        try:
            parsed: Any = json.loads(raw_text) if raw_text else {}
        except (json.JSONDecodeError, TypeError):
            parsed = {"text": raw_text}
        return raw_text, parsed, bool(result.isError)


def default_command() -> list[str]:
    """What `start()` will spawn, for display in Administration."""
    command = os.getenv("PRISMA_CONSOLE_MCP_COMMAND", DEFAULT_COMMAND)
    configured_args = os.getenv("PRISMA_CONSOLE_MCP_ARGS")
    args = shlex.split(configured_args) if configured_args else list(DEFAULT_ARGS)
    return [command, *args]
