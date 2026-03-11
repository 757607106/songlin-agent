#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict

from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.agent_platform.constants import AGENT_PLATFORM_AGENT_ID, AGENT_PLATFORM_CONFIG_VERSION
from src.storage.postgres.manager import pg_manager
from src.storage.postgres.models_business import AgentConfig


def _is_legacy_agent_platform_config(config: AgentConfig) -> bool:
    if config.agent_id != AGENT_PLATFORM_AGENT_ID:
        return False
    payload = config.config_json if isinstance(config.config_json, dict) else {}
    return payload.get("version") != AGENT_PLATFORM_CONFIG_VERSION


async def _load_candidates(*, department_id: int | None = None) -> list[AgentConfig]:
    pg_manager.initialize()
    async with pg_manager.get_async_session_context() as session:
        stmt = select(AgentConfig).where(AgentConfig.agent_id == AGENT_PLATFORM_AGENT_ID).order_by(AgentConfig.id.asc())
        if department_id is not None:
            stmt = stmt.where(AgentConfig.department_id == department_id)
        result = await session.execute(stmt)
        items = list(result.scalars().all())
        return [item for item in items if _is_legacy_agent_platform_config(item)]


def _print_summary(items: list[AgentConfig]) -> None:
    print("=" * 80)
    print("Legacy AgentPlatformAgent 配置检查")
    print("=" * 80)
    if not items:
        print("未发现 legacy 自定义 Agent 配置。")
        return

    grouped: dict[int, list[AgentConfig]] = defaultdict(list)
    for item in items:
        grouped[item.department_id].append(item)

    print(f"共发现 {len(items)} 条 legacy 配置，涉及 {len(grouped)} 个部门。")
    for department, configs in sorted(grouped.items()):
        print(f"\n部门 {department}: {len(configs)} 条")
        for item in configs:
            payload = item.config_json if isinstance(item.config_json, dict) else {}
            keys = sorted(payload.keys())
            print(
                f"  - id={item.id} name={item.name!r} default={bool(item.is_default)} "
                f"version={payload.get('version')!r} keys={keys}"
            )


async def _promote_valid_default(session, *, department_id: int) -> None:
    stmt = (
        select(AgentConfig)
        .where(
            AgentConfig.department_id == department_id,
            AgentConfig.agent_id == AGENT_PLATFORM_AGENT_ID,
        )
        .order_by(AgentConfig.is_default.desc(), AgentConfig.id.asc())
    )
    result = await session.execute(stmt)
    items = list(result.scalars().all())
    valid_items = [item for item in items if not _is_legacy_agent_platform_config(item)]
    if not valid_items:
        return

    if any(item.is_default for item in valid_items):
        return

    valid_items[0].is_default = True
    print(f"  -> 已将 id={valid_items[0].id} name={valid_items[0].name!r} 提升为默认配置")


async def _delete_candidates(items: list[AgentConfig]) -> int:
    if not items:
        return 0

    target_ids = {item.id for item in items}
    affected_departments = sorted({item.department_id for item in items if item.is_default})

    pg_manager.initialize()
    async with pg_manager.get_async_session_context() as session:
        result = await session.execute(
            select(AgentConfig).where(
                AgentConfig.agent_id == AGENT_PLATFORM_AGENT_ID,
            )
        )
        db_items = [item for item in result.scalars().all() if item.id in target_ids]

        for item in db_items:
            print(f"删除: id={item.id} department={item.department_id} name={item.name!r}")
            await session.delete(item)

        await session.flush()

        for department_id in affected_departments:
            await _promote_valid_default(session, department_id=department_id)

    return len(target_ids)


async def _main() -> int:
    parser = argparse.ArgumentParser(description="清理 AgentPlatformAgent 的 legacy 自定义配置。")
    parser.add_argument("--department-id", type=int, default=None, help="仅检查指定部门。")
    parser.add_argument(
        "--delete",
        action="store_true",
        help="执行删除。默认仅预览，不做任何改动。",
    )
    args = parser.parse_args()

    items = await _load_candidates(department_id=args.department_id)
    _print_summary(items)

    if not args.delete:
        print("\n当前为预览模式。若要实际删除，请追加 --delete。")
        return 0

    if not items:
        return 0

    print("\n开始删除 legacy 配置...")
    deleted = await _delete_candidates(items)
    print(f"\n删除完成，共处理 {deleted} 条 legacy 配置。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
