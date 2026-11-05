"""End to end: start the server as a subprocess and talk MCP to it over stdio."""

import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def _session(log_dir):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "loglens.server"],
        env={**os.environ, "LOGLENS_LOG_DIR": str(log_dir)},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool(
            "correlate_errors", {"anchor": "TDR timeout", "run": "nightly-1042"}
        )
        return [t.name for t in tools.tools], json.loads(result.content[0].text)


def test_stdio_round_trip(log_dir):
    names, payload = asyncio.run(asyncio.wait_for(_session(log_dir), timeout=60))
    assert "correlate_errors" in names
    assert payload["occurrences"] == 13
    assert payload["related"][0]["signature"].startswith("Shader compilation")
