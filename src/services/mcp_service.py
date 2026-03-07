"""MCP 服务 - MCP 的统一业务逻辑和状态管理。

职责：
- 服务器配置 CRUD 操作
- 配置同步（数据库 <-> 缓存）
- Agent 工具检索的统一入口（自动过滤 disabled_tools）
- MCP 客户端和工具管理（原 agents/common/mcp.py）
"""

import asyncio
import re
import traceback
from collections.abc import Callable
from typing import Any, cast

from langchain_mcp_adapters.client import MultiServerMCPClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.postgres.models_business import MCPServer
from src.utils import logger

# =============================================================================
# === 全局缓存与状态 ===
# =============================================================================

# MCP 状态的全局锁
_mcp_lock = asyncio.Lock()

# 全局 MCP 工具缓存
_mcp_tools_cache: dict[str, list[Callable[..., Any]]] = {}

# MCP 工具统计信息（用于报告启用/禁用数量）
_mcp_tools_stats: dict[str, dict[str, int]] = {}

# MCP 服务器配置（运行时缓存，从数据库加载）
MCP_SERVERS: dict[str, dict[str, Any]] = {}

# 全局共享 MCP 客户端实例（避免重复初始化）
_mcp_client: MultiServerMCPClient | None = None
_mcp_client_config_hash: str | None = None  # 用于检测配置变更

# 默认 MCP 服务器配置（首次运行时导入数据库）
_DEFAULT_MCP_SERVERS = {
    "sequentialthinking": {
        "url": "https://remote.mcpservers.org/sequentialthinking/mcp",
        "transport": "streamable_http",
        "description": "顺序思考工具，帮助 AI 将复杂问题分解为多个步骤",
        "icon": "🧠",
        "tags": ["内置", "AI"],
    },
    "mcp-server-chart": {
        "command": "npx",
        "args": ["-y", "@antv/mcp-server-chart"],
        "transport": "stdio",
        "description": "图表生成工具，支持生成各类图表（柱状图、折线图、饼图等）",
        "icon": "📊",
        "tags": ["内置", "图表"],
    },
}

# =============================================================================
# === 核心逻辑（从 agents/common/mcp.py 移动） ===
# =============================================================================


async def load_mcp_servers_from_db() -> None:
    """将所有启用的 MCP 服务器配置从数据库加载到 MCP_SERVERS 缓存。"""
    global MCP_SERVERS

    # 延迟导入以避免循环引用
    from src.storage.postgres.manager import pg_manager

    try:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(MCPServer).filter(MCPServer.enabled == 1))
            servers = result.scalars().all()

            async with _mcp_lock:
                MCP_SERVERS.clear()
                for server in servers:
                    MCP_SERVERS[server.name] = server.to_mcp_config()

            logger.info(f"Loaded {len(MCP_SERVERS)} MCP servers from database: {list(MCP_SERVERS.keys())}")
    except Exception as e:
        logger.error(f"Failed to load MCP servers from database: {e}")


async def sync_mcp_server_to_cache(name: str, config: dict[str, Any] | None) -> None:
    """同步单个 MCP 服务器配置到缓存。

    Args:
        name: 服务器名称
        config: 服务器配置，若为 None 则从缓存中移除
    """
    global MCP_SERVERS

    async with _mcp_lock:
        if config is None:
            MCP_SERVERS.pop(name, None)
            logger.info(f"Removed MCP server '{name}' from cache")
        else:
            MCP_SERVERS[name] = config
            logger.info(f"Synced MCP server '{name}' to cache")

        # 清除该服务器的工具缓存
        _mcp_tools_cache.pop(name, None)


async def init_mcp_servers() -> None:
    """初始化 MCP 服务器配置。

    首次运行时，如果数据库为空，则导入默认配置。
    然后从数据库加载配置到 MCP_SERVERS 缓存。
    同时确保所有内置 MCP 服务器都存在于数据库中。
    """
    # 延迟导入以避免循环引用
    from src.storage.postgres.manager import pg_manager

    try:
        async with pg_manager.get_async_session_context() as session:
            # 检查数据库是否有 MCP 配置
            result = await session.execute(select(func.count(MCPServer.name)))
            count = result.scalar()

            if count == 0:
                # 数据库为空，导入默认配置
                logger.info("No MCP servers in database, importing default configurations...")
                for name, config in _DEFAULT_MCP_SERVERS.items():
                    server = MCPServer(
                        name=name,
                        description=config.get("description"),
                        transport=config["transport"],
                        url=config.get("url"),
                        command=config.get("command"),
                        args=config.get("args"),
                        headers=config.get("headers"),
                        timeout=config.get("timeout"),
                        sse_read_timeout=config.get("sse_read_timeout"),
                        tags=config.get("tags"),
                        icon=config.get("icon"),
                        enabled=1,
                        created_by="system",
                        updated_by="system",
                    )
                    session.add(server)
                await session.commit()
                logger.info(f"Imported {len(_DEFAULT_MCP_SERVERS)} default MCP servers to database")
            else:
                # 确保所有内置 MCP 服务器都存在于数据库中
                for name, config in _DEFAULT_MCP_SERVERS.items():
                    result = await session.execute(select(MCPServer).filter(MCPServer.name == name))
                    existing = result.scalar_one_or_none()
                    if not existing:
                        server = MCPServer(
                            name=name,
                            description=config.get("description"),
                            transport=config["transport"],
                            url=config.get("url"),
                            command=config.get("command"),
                            args=config.get("args"),
                            headers=config.get("headers"),
                            timeout=config.get("timeout"),
                            sse_read_timeout=config.get("sse_read_timeout"),
                            tags=config.get("tags"),
                            icon=config.get("icon"),
                            enabled=1,
                            created_by="system",
                            updated_by="system",
                        )
                        session.add(server)
                        logger.info(f"Added built-in MCP server '{name}' to database")
                # 如果添加了新服务器则提交（检查会话状态）
                if session.new:
                    await session.commit()

        # 从数据库加载配置到缓存
        await load_mcp_servers_from_db()

        # 初始化共享 MCP 客户端
        await _init_shared_mcp_client()

    except Exception as e:
        logger.error(f"Failed to initialize MCP servers: {e}, traceback: {traceback.format_exc()}")


async def get_mcp_client(
    server_configs: dict[str, Any] | None = None,
) -> MultiServerMCPClient | None:
    """使用给定的服务器配置初始化 MCP 客户端。"""
    try:
        client = MultiServerMCPClient(server_configs)  # pyright: ignore[reportArgumentType]
        logger.info(f"Initialized MCP client with servers: {list(server_configs.keys())}")
        return client
    except Exception as e:
        logger.error("Failed to initialize MCP client: {}", e)
        return None


def _compute_config_hash() -> str:
    """计算当前 MCP 配置的哈希值，用于检测配置变更。"""
    import hashlib
    import json

    config_str = json.dumps(MCP_SERVERS, sort_keys=True, default=str)
    return hashlib.md5(config_str.encode()).hexdigest()


async def _init_shared_mcp_client() -> None:
    """初始化或重建共享 MCP 客户端。

    官方文档推荐：创建一次 MultiServerMCPClient，复用多次。
    https://github.com/langchain-ai/langchain-mcp-adapters
    """
    global _mcp_client, _mcp_client_config_hash

    if not MCP_SERVERS:
        logger.info("No MCP servers configured, skipping client initialization")
        return

    new_hash = _compute_config_hash()

    # 如果配置未变更且客户端已存在，跳过
    if _mcp_client is not None and _mcp_client_config_hash == new_hash:
        logger.debug("MCP client already initialized with current config")
        return

    # 构建客户端配置（排除 disabled_tools 等非连接参数）
    client_configs = {}
    for name, config in MCP_SERVERS.items():
        client_configs[name] = {k: v for k, v in config.items() if k not in ("disabled_tools",)}

    try:
        _mcp_client = MultiServerMCPClient(client_configs)
        _mcp_client_config_hash = new_hash
        logger.info(f"✅ Initialized shared MCP client with {len(client_configs)} servers")
    except Exception as e:
        logger.error(f"Failed to initialize shared MCP client: {e}")
        _mcp_client = None
        _mcp_client_config_hash = None


async def get_shared_mcp_client() -> MultiServerMCPClient | None:
    """获取共享 MCP 客户端实例。

    如果配置已变更，会自动重建客户端。
    """
    global _mcp_client, _mcp_client_config_hash

    if not MCP_SERVERS:
        return None

    new_hash = _compute_config_hash()
    if _mcp_client is None or _mcp_client_config_hash != new_hash:
        await _init_shared_mcp_client()

    return _mcp_client


async def close_shared_mcp_client() -> None:
    """关闭共享 MCP 客户端（应用关闭时调用）。"""
    global _mcp_client, _mcp_client_config_hash
    _mcp_client = None
    _mcp_client_config_hash = None
    logger.info("Closed shared MCP client")


def to_camel_case(s: str) -> str:
    """将字符串转换为小写驼峰命名（lowerCamelCase）。"""

    # 处理 - 和 _
    s = re.sub(r"[-_]+(.)", lambda m: m.group(1).upper(), s)
    # 首字母小写
    if len(s) > 0:
        s = s[0].lower() + s[1:]
    return s


async def get_mcp_tools(
    server_name: str,
    additional_servers: dict[str, dict] = None,
    disabled_tools: list[str] = None,
    cache: bool = True,
    force_refresh: bool = False,
) -> list[Callable[..., Any]]:
    """获取指定服务器的 MCP 工具。

    架构：
    1. 获取：连接到 MCP 服务器以获取所有工具。
    2. 缓存：将完整、未过滤的工具列表存储在 `_mcp_tools_cache` 中。
    3. 过滤：根据 `disabled_tools` 参数过滤返回值。

    Args:
        server_name: 服务器名称
        additional_servers: 额外的服务器配置
        disabled_tools: 要从返回值中过滤掉的工具名称列表（不影响缓存）
        cache: 是否使用/更新缓存（默认：True）
        force_refresh: 是否强制从服务器刷新（默认：False）
    """
    global _mcp_tools_cache

    # 1. 准备服务器配置
    async with _mcp_lock:
        mcp_servers = MCP_SERVERS | (additional_servers or {})

    all_processed_tools = []

    # 2. 检查缓存 / 获取策略
    # 如果缓存中有且不需要强制刷新，则使用缓存。
    if not force_refresh and cache and server_name in _mcp_tools_cache:
        all_processed_tools = _mcp_tools_cache[server_name]
    else:
        # 需要从服务器获取
        try:
            assert server_name in mcp_servers, f"Server {server_name} not found in ({list(mcp_servers.keys())})"

            # 使用共享客户端（官方推荐：复用而非重建）
            client = await get_shared_mcp_client()
            if client is None:
                # 回退：如果共享客户端不可用，创建临时客户端
                server_config = mcp_servers[server_name]
                client_config = {k: v for k, v in server_config.items() if k not in ("disabled_tools",)}
                client = await get_mcp_client({server_name: client_config})
                if client is None:
                    return []

            # 获取所有工具（原始）
            raw_tools = cast(list[Any], await client.get_tools())

            # 为所有工具生成 ID
            server_cc = to_camel_case(server_name)
            for tool in raw_tools:
                # 生成唯一 ID 规则：mcp__[camelCaseServer]__[camelCaseTool]
                original_name = tool.name
                tool_cc = to_camel_case(original_name)
                unique_id = f"mcp__{server_cc}__{tool_cc}"

                # 使用元数据存储
                if tool.metadata is None:
                    tool.metadata = {}
                tool.metadata["id"] = unique_id

                all_processed_tools.append(tool)

            # 更新缓存（存储完整列表）
            if cache:
                _mcp_tools_cache[server_name] = all_processed_tools

                # 更新统计信息
                # 统计信息应反映全局配置状态
                # （存储配置中禁用了多少，而不是临时参数）
                global_config_disabled = mcp_servers.get(server_name, {}).get("disabled_tools") or []
                enabled_count = len([t for t in all_processed_tools if t.name not in global_config_disabled])

                _mcp_tools_stats[server_name] = {
                    "total": len(all_processed_tools),
                    "enabled": enabled_count,
                    "disabled": len(all_processed_tools) - enabled_count,
                }

                logger.info(f"Refreshed MCP tools cache for '{server_name}': {len(all_processed_tools)} tools loaded.")

        except AssertionError as e:
            logger.warning(f"[assert] Failed to load tools from MCP server '{server_name}': {e}")
            return []
        except Exception as e:
            logger.error(
                f"Failed to load tools from MCP server '{server_name}': {e}, traceback: {traceback.format_exc()}"
            )
            return []

    # 3. 过滤（仅应用于返回值）
    if disabled_tools:
        filtered_tools = [t for t in all_processed_tools if t.name not in disabled_tools]
        logger.debug(
            f"Returning {len(filtered_tools)}/{len(all_processed_tools)} tools for '{server_name}' "
            f"(filtered {len(disabled_tools)} by argument)"
        )
        return filtered_tools

    return all_processed_tools


async def get_tools_from_all_servers() -> list[Callable[..., Any]]:
    """获取所有已配置 MCP 服务器的所有工具。"""
    all_tools = []
    for server_name in MCP_SERVERS.keys():
        tools = await get_mcp_tools(server_name)
        all_tools.extend(tools)
    return all_tools


def add_mcp_server(name: str, config: dict[str, Any]) -> None:
    """添加新的 MCP 服务器配置。"""
    MCP_SERVERS[name] = config
    # 清除客户端以强制使用新配置重新初始化
    clear_mcp_cache()


def clear_mcp_cache() -> None:
    """清除 MCP 工具缓存（用于测试）。"""
    global _mcp_tools_cache, _mcp_tools_stats
    _mcp_tools_cache = {}
    _mcp_tools_stats = {}


def clear_mcp_server_tools_cache(server_name: str) -> None:
    """清除特定 MCP 服务器的工具缓存。"""
    global _mcp_tools_cache, _mcp_tools_stats
    _mcp_tools_cache.pop(server_name, None)
    _mcp_tools_stats.pop(server_name, None)
    logger.info(f"Cleared tools cache for MCP server '{server_name}'")


def get_mcp_tools_stats(server_name: str) -> dict[str, int] | None:
    """获取 MCP 服务器的工具统计信息。

    Returns:
        包含 'total', 'enabled', 'disabled' 计数的字典，如果不可用则返回 None
    """
    return _mcp_tools_stats.get(server_name)


# =============================================================================
# === 服务器配置 CRUD（mcp_service.py 中已存在） ===
# =============================================================================


async def get_mcp_server(db: AsyncSession, name: str) -> MCPServer | None:
    """获取单个服务器配置。"""
    result = await db.execute(select(MCPServer).filter(MCPServer.name == name))
    return result.scalar_one_or_none()


async def get_all_mcp_servers(db: AsyncSession) -> list[MCPServer]:
    """获取所有服务器配置。"""
    result = await db.execute(select(MCPServer))
    return list(result.scalars().all())


async def create_mcp_server(
    db: AsyncSession,
    name: str,
    transport: str,
    url: str = None,
    command: str = None,
    args: list = None,
    description: str = None,
    headers: dict = None,
    timeout: int = None,
    sse_read_timeout: int = None,
    tags: list = None,
    icon: str = None,
    created_by: str = None,
) -> MCPServer:
    """创建服务器。"""
    # 检查名称是否存在
    existing = await get_mcp_server(db, name)
    if existing:
        raise ValueError(f"Server name '{name}' already exists")

    server = MCPServer(
        name=name,
        description=description,
        transport=transport,
        url=url,
        command=command,
        args=args,
        headers=headers,
        timeout=timeout,
        sse_read_timeout=sse_read_timeout,
        tags=tags,
        icon=icon,
        enabled=1,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(server)
    await db.commit()
    await db.refresh(server)

    # 同步到缓存
    await sync_mcp_server_to_cache(name, server.to_mcp_config())

    logger.info(f"Created MCP server '{name}'")
    return server


async def update_mcp_server(
    db: AsyncSession,
    name: str,
    description: str = None,
    transport: str = None,
    url: str = None,
    command: str = None,
    args: list = None,
    headers: dict = None,
    timeout: int = None,
    sse_read_timeout: int = None,
    tags: list = None,
    icon: str = None,
    updated_by: str = None,
) -> MCPServer:
    """更新服务器配置。"""
    server = await get_mcp_server(db, name)
    if not server:
        raise ValueError(f"Server '{name}' does not exist")

    if description is not None:
        server.description = description
    if transport is not None:
        server.transport = transport
    if url is not None:
        server.url = url
    if command is not None:
        server.command = command
    if args is not None:
        server.args = args
    if headers is not None:
        server.headers = headers
    if timeout is not None:
        server.timeout = timeout
    if sse_read_timeout is not None:
        server.sse_read_timeout = sse_read_timeout
    if tags is not None:
        server.tags = tags
    if icon is not None:
        server.icon = icon
    if updated_by is not None:
        server.updated_by = updated_by

    await db.commit()
    await db.refresh(server)

    # 同步到缓存（如果已启用）
    if server.enabled:
        await sync_mcp_server_to_cache(name, server.to_mcp_config())

    logger.info(f"Updated MCP server '{name}'")
    return server


async def delete_mcp_server(db: AsyncSession, name: str) -> bool:
    """删除服务器。"""
    server = await get_mcp_server(db, name)
    if not server:
        return False

    await db.delete(server)
    await db.commit()

    # 从缓存中移除
    await sync_mcp_server_to_cache(name, None)

    logger.info(f"Deleted MCP server '{name}'")
    return True


# =============================================================================
# === 工具管理 ===
# =============================================================================


async def toggle_server_enabled(db: AsyncSession, name: str, updated_by: str = None) -> tuple[bool, MCPServer]:
    """切换服务器启用状态。"""
    server = await get_mcp_server(db, name)
    if not server:
        raise ValueError(f"Server '{name}' does not exist")

    server.enabled = 0 if server.enabled else 1
    if updated_by is not None:
        server.updated_by = updated_by
    await db.commit()

    # 同步到缓存
    is_enabled = bool(server.enabled)
    server_config = server.to_mcp_config() if is_enabled else None
    await sync_mcp_server_to_cache(name, server_config)

    logger.info(f"Toggled MCP server '{name}' enabled={is_enabled}")
    return is_enabled, server


async def toggle_tool_enabled(
    db: AsyncSession,
    server_name: str,
    tool_name: str,
    updated_by: str = None,
) -> tuple[bool, MCPServer]:
    """切换单个工具的启用状态。

    Args:
        db: 数据库会话
        server_name: 服务器名称
        tool_name: 工具名称
        updated_by: 更新者

    Returns:
        (enabled, server): 工具启用状态和更新后的服务器对象
    """
    server = await get_mcp_server(db, server_name)
    if not server:
        raise ValueError(f"Server '{server_name}' does not exist")

    disabled_tools = list(server.disabled_tools or [])

    if tool_name in disabled_tools:
        disabled_tools.remove(tool_name)
        enabled = True
    else:
        disabled_tools.append(tool_name)
        enabled = False

    server.disabled_tools = disabled_tools
    if updated_by is not None:
        server.updated_by = updated_by
    await db.commit()

    # 清除工具缓存（下次获取时重新过滤）
    clear_mcp_server_tools_cache(server_name)

    logger.info(f"Toggled tool '{tool_name}' for server '{server_name}' enabled={enabled}")
    return enabled, server


# =============================================================================
# === 统一入口点（包装器） ===
# =============================================================================


def get_mcp_server_names() -> list[str]:
    """获取已加载的 MCP 服务器名称列表。

    Returns a copy of keys to avoid runtime modification issues during iteration.
    """
    return list(MCP_SERVERS.keys())


async def get_enabled_mcp_tools(server_name: str) -> list:
    """获取 MCP 服务器工具（自动过滤 disabled_tools）。

    Agent 的统一入口点，自动执行：
    1. 从缓存获取服务器配置
    2. 获取所有工具
    3. 过滤掉 disabled_tools

    Args:
        server_name: 服务器名称

    Returns:
        启用工具的列表
    """
    config = MCP_SERVERS.get(server_name)
    if not config:
        logger.warning(f"MCP server '{server_name}' not found in cache")
        return []

    disabled_tools = config.get("disabled_tools") or []
    return await get_mcp_tools(server_name, disabled_tools=disabled_tools)


async def get_servers_config(names: list[str]) -> dict[str, dict[str, Any]]:
    """批量获取服务器配置。

    Args:
        names: 服务器名称列表

    Returns:
        {name: config} 字典，仅包含找到的服务器
    """
    return {name: MCP_SERVERS[name] for name in names if name in MCP_SERVERS}


async def get_all_mcp_tools(server_name: str) -> list:
    """获取 MCP 服务器的所有工具（不过滤）。

    用于管理 UI 显示工具列表，支持查看所有工具及其启用状态。
    不会更新全局工具缓存，以免污染 Agent 的过滤视图。

    Args:
        server_name: 服务器名称

    Returns:
        所有工具的列表（未过滤）
    """
    config = MCP_SERVERS.get(server_name)
    if not config:
        logger.warning(f"MCP server '{server_name}' not found in cache")
        return []

    # Get all tools (no filtering, force refresh, no cache update)
    return await get_mcp_tools(server_name, disabled_tools=[], cache=False, force_refresh=True)
