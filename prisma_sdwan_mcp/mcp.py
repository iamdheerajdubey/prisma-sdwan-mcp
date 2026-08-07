from __future__ import annotations

import functools
import inspect

from fastmcp import FastMCP

mcp = FastMCP("Prisma SD-WAN MCP v2")


def _full_docstrings(original):
    """Preserve the whole operational docstring in the MCP tool description."""
    @functools.wraps(original)
    def tool(name_or_fn=None, **kwargs):
        def register(fn):
            if kwargs.get("description") is None:
                kwargs["description"] = inspect.getdoc(fn)
            return original(fn, **kwargs)
        if callable(name_or_fn):
            return register(name_or_fn)
        if name_or_fn is not None:
            kwargs.setdefault("name", name_or_fn)
        return register
    return tool


mcp.tool = _full_docstrings(mcp.tool)

READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
