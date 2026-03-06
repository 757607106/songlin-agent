from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.services.task_service import tasker
from src.services.mcp_service import init_mcp_servers
from src.storage.postgres.manager import pg_manager
from src.storage.postgres.checkpointer import checkpointer_manager
from src.storage.redis.client import redis_manager
from src.knowledge import knowledge_base
from src.utils import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan事件管理器"""
    # 初始化数据库连接
    try:
        pg_manager.initialize()
        await pg_manager.create_business_tables()
        await pg_manager.ensure_knowledge_schema()
    except Exception as e:
        logger.error(f"Failed to initialize database during startup: {e}")

    # 初始化共享 checkpointer (LangGraph 状态持久化)
    try:
        await checkpointer_manager.initialize()
        # 注入到所有 Agent
        from src.agents import agent_manager

        agent_manager.set_shared_checkpointer(checkpointer_manager.get_checkpointer())
    except Exception as e:
        logger.warning(f"Failed to initialize shared checkpointer: {e}")

    # 初始化 Redis 连接 (可选，用于任务队列持久化)
    try:
        await redis_manager.initialize()
    except Exception as e:
        logger.warning(f"Failed to initialize Redis (task queue will use in-memory): {e}")

    # 初始化 MCP 服务器配置
    try:
        await init_mcp_servers()
    except Exception as e:
        logger.error(f"Failed to initialize MCP servers during startup: {e}")

    # 初始化知识库管理器
    try:
        await knowledge_base.initialize()
    except Exception as e:
        logger.error(f"Failed to initialize knowledge base manager: {e}")

    await tasker.start()
    yield
    await tasker.shutdown()
    await redis_manager.close()
    await checkpointer_manager.close()
    await pg_manager.close()
