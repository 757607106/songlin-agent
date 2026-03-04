"""Smoke test for reporter supervisor graph construction."""

from __future__ import annotations

import asyncio

from src.agents.reporter import SqlReporterAgent


async def main() -> None:
    agent = SqlReporterAgent()
    graph = await agent.get_graph()
    print(f"Graph compiled: {graph is not None}")
    # Cleanly close the async checkpointer connection to avoid loop-close errors.
    if agent._async_conn is not None:
        await agent._async_conn.close()


if __name__ == "__main__":
    asyncio.run(main())
