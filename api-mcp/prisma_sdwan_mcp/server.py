import argparse
import logging
import sys

from . import registry
from .client import PrismaSDWANClient


mcp = registry.mcp
client = PrismaSDWANClient()
registry.client = client

from .tools import config_gen, inventory, monitoring, network, policy, resolve, routing  # noqa: E402,F401
from . import resources, prompts  # noqa: E402,F401


class CleanStderr:
    SHUTDOWN_NOISE = (
        "Traceback (most recent call last)",
        "asyncio.exceptions.CancelledError",
        "concurrent.futures._base.CancelledError",
        "starlette.routing",
        "uvicorn.error",
        "anyio._backends",
        "Exception in ASGI application",
        "During handling of the above exception",
        "KeyboardInterrupt",
        "RuntimeError: Event loop is closed",
    )

    def __init__(self, original):
        self._original = original
        self._shutdown = False

    def begin_shutdown(self):
        self._shutdown = True

    def write(self, message):
        if self._shutdown and any(noise in message for noise in self.SHUTDOWN_NOISE):
            return
        self._original.write(message)

    def flush(self):
        self._original.flush()

    def __getattr__(self, name):
        return getattr(self._original, name)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prisma SD-WAN MCP Server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for HTTP/SSE transport (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP/SSE transport (default: 8000)",
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    clean_stderr = CleanStderr(sys.stderr)
    sys.stderr = clean_stderr
    transport = args.transport
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("fastmcp").setLevel(logging.INFO)
    print(f"Prisma SD-WAN MCP Server ({transport})", file=sys.stderr)

    try:
        if transport == "stdio":
            mcp.run(transport="stdio")
        else:
            try:
                mcp.run(
                    transport=transport,
                    host=args.host,
                    port=args.port,
                    show_banner=False,
                )
            except TypeError:
                mcp.run(transport=transport, host=args.host, port=args.port)
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