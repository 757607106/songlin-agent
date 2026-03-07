"""
共享 PostgreSQL Checkpointer 管理器

根据 LangChain 官方最佳实践，在应用生命周期内共享单一 checkpointer 实例，
避免每个 Agent 独立创建连接导致的性能问题。
"""

import importlib
import inspect
import os

from src import config as sys_config
from src.utils import logger


class CheckpointerManager:
    """PostgreSQL Checkpointer 单例管理器"""

    def __init__(self):
        self._checkpointer = None
        self._store = None
        self._checkpointer_cm = None
        self._store_cm = None
        self._initialized = False

    @staticmethod
    def _normalize_postgres_conninfo(url: str) -> str:
        """将 asyncpg URL 转换为 psycopg 兼容格式"""
        if url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql+asyncpg://", "postgresql://")
        return url

    @staticmethod
    def _resolve_postgres_url() -> str:
        postgres_url = (
            str(getattr(sys_config, "checkpointer_postgres_url", "") or "").strip()
            or os.getenv("CHECKPOINTER_POSTGRES_URL")
            or os.getenv("POSTGRES_URL")
        )
        if not postgres_url:
            raise RuntimeError("未配置 CHECKPOINTER_POSTGRES_URL/POSTGRES_URL")
        return CheckpointerManager._normalize_postgres_conninfo(postgres_url)

    async def initialize(self) -> bool:
        """初始化共享 checkpointer，应用启动时调用一次"""
        if self._initialized:
            return True

        try:
            postgres_url = self._resolve_postgres_url()

            # 动态导入 langgraph-checkpoint-postgres
            module_name = "langgraph.checkpoint.postgres.aio"
            try:
                module = importlib.import_module(module_name)
            except ImportError as e:
                logger.warning(f"{module_name} 导入失败，跳过 checkpointer 初始化: {e}")
                return False

            saver_cls = getattr(module, "AsyncPostgresSaver", None)
            if saver_cls is None:
                logger.error(f"{module_name} 不包含 AsyncPostgresSaver")
                return False

            # 创建 checkpointer
            from_conn_string = getattr(saver_cls, "from_conn_string", None)
            if callable(from_conn_string):
                saver = from_conn_string(postgres_url)
            else:
                saver = saver_cls(postgres_url)

            # 进入 context manager
            if hasattr(saver, "__aenter__"):
                self._checkpointer_cm = saver
                self._checkpointer = await saver.__aenter__()
            else:
                self._checkpointer = saver

            # 执行 setup (创建表结构)
            setup_fn = getattr(self._checkpointer, "setup", None)
            if callable(setup_fn):
                setup_result = setup_fn()
                if inspect.isawaitable(setup_result):
                    await setup_result

            self._initialized = True
            logger.info(f"Shared PostgreSQL checkpointer initialized: {postgres_url[:50]}...")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize shared checkpointer: {e}")
            return False

    async def initialize_store(self) -> bool:
        """初始化共享 store (可选)"""
        if self._store is not None:
            return True

        try:
            postgres_url = self._resolve_postgres_url()

            module_name = "langgraph.store.postgres.aio"
            try:
                module = importlib.import_module(module_name)
            except ImportError as e:
                logger.warning(f"{module_name} 导入失败，跳过 store 初始化: {e}")
                return False

            store_cls = getattr(module, "AsyncPostgresStore", None)
            if store_cls is None:
                return False

            from_conn_string = getattr(store_cls, "from_conn_string", None)
            if callable(from_conn_string):
                store = from_conn_string(postgres_url)
            else:
                store = store_cls(postgres_url)

            if hasattr(store, "__aenter__"):
                self._store_cm = store
                self._store = await store.__aenter__()
            else:
                self._store = store

            setup_fn = getattr(self._store, "setup", None)
            if callable(setup_fn):
                setup_result = setup_fn()
                if inspect.isawaitable(setup_result):
                    await setup_result

            logger.info("Shared PostgreSQL store initialized")
            return True

        except Exception as e:
            logger.warning(f"Failed to initialize shared store: {e}")
            return False

    def get_checkpointer(self):
        """获取共享 checkpointer 实例"""
        return self._checkpointer

    def get_store(self):
        """获取共享 store 实例"""
        return self._store

    def is_available(self) -> bool:
        """检查 checkpointer 是否可用"""
        return self._initialized and self._checkpointer is not None

    async def close(self):
        """关闭连接，应用关闭时调用"""
        if self._store_cm is not None:
            try:
                await self._store_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing store: {e}")
            self._store_cm = None
            self._store = None

        if self._checkpointer_cm is not None:
            try:
                await self._checkpointer_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing checkpointer: {e}")
            self._checkpointer_cm = None
            self._checkpointer = None

        self._initialized = False
        logger.info("Shared checkpointer closed")


# 全局单例
checkpointer_manager = CheckpointerManager()
