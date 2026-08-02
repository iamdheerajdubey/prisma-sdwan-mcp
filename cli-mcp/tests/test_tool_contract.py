import asyncio

import prisma_sdwan_cli_mcp_server as server


def test_top_level_entrypoint_exposes_the_same_single_tool():
    tools = asyncio.run(server.mcp.list_tools())

    assert [tool.name for tool in tools] == ["run_commands"]
