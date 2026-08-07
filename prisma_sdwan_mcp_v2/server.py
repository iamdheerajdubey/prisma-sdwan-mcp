from __future__ import annotations

import argparse
import logging
import sys

from . import runtime
from .mcp import mcp

# Construct the SDK client now; authentication itself remains lazy until the first API call.
runtime.initialize()

# Tool registration.
from .tools import config_gen, core, discovery, domains, monitoring, policies_security, routing_diagnostics  # noqa: E402,F401
from . import prompts, resources  # noqa: E402,F401


class CleanStderr:
    SHUTDOWN_NOISE = (
        "asyncio.exceptions.CancelledError",
        "concurrent.futures._base.CancelledError",
        "RuntimeError: Event loop is closed",
    )

    def __init__(self, original):
        self._original = original
        self._shutdown = False

    def begin_shutdown(self) -> None:
        self._shutdown = True

    def write(self, message: str) -> None:
        if self._shutdown and any(noise in message for noise in self.SHUTDOWN_NOISE):
            return
        self._original.write(message)

    def flush(self) -> None:
        self._original.flush()

    def __getattr__(self, name):
        return getattr(self._original, name)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prisma SD-WAN MCP v2")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    clean_stderr = CleanStderr(sys.stderr)
    sys.stderr = clean_stderr
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("fastmcp").setLevel(logging.INFO)
    print(
        f"Prisma SD-WAN MCP v2 ({args.transport}) - {runtime.catalog.registry_action_count} registry actions + {runtime.catalog.compat_action_count} curated compatibility actions",
        file=sys.stderr,
    )
    try:
        if args.transport == "stdio":
            mcp.run(transport="stdio")
        else:
            try:
                mcp.run(transport=args.transport, host=args.host, port=args.port, show_banner=False)
            except TypeError:
                mcp.run(transport=args.transport, host=args.host, port=args.port)
    except KeyboardInterrupt:
        clean_stderr.begin_shutdown()
        print("Server stopped by user.", file=sys.stderr)
        return 0
    except Exception:
        logging.exception("Server stopped because of an unexpected error")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
