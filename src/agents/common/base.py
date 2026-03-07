from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import tomllib as tomli
import uuid
from abc import abstractmethod
from pathlib import Path

from langgraph.graph.state import CompiledStateGraph

from src import config as sys_config
from src.agents.common.context import BaseContext
from src.utils import logger


class BaseAgent:
    """
    定义一个基础 Agent 供 各类 graph 继承
    """

    name = "base_agent"
    description = "base_agent"
    capabilities: list[str] = []  # 智能体能力列表，如 ["file_upload", "web_search"] 等
    context_schema: type[BaseContext] = BaseContext  # 智能体上下文 schema

    def __init__(self, **kwargs):
        self.graph = None  # will be covered by get_graph
        self.checkpointer = None
        self.store = None
        self._postgres_saver_cm = None
        self._postgres_store_cm = None
        self.workdir = Path(sys_config.save_dir) / "agents" / self.module_name
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._metadata_cache = None  # Cache for metadata to avoid repeated file reads

    @property
    def module_name(self) -> str:
        """Get the module name of the agent class."""
        return self.__class__.__module__.split(".")[-2]

    @property
    def id(self) -> str:
        """Get the agent's class name."""
        return self.__class__.__name__

    async def get_info(self):
        # Load metadata from file
        metadata = self.load_metadata()

        # 使用快速路径检查 checkpointer，避免初始化 Graph
        # 如果共享 checkpointer 已注入，直接返回 True；否则返回 False
        has_checkpointer = self.checkpointer is not None

        # Merge metadata with class attributes, metadata takes precedence
        return {
            "id": self.id,
            "name": metadata.get("name", getattr(self, "name", "Unknown")),
            "description": metadata.get("description", getattr(self, "description", "Unknown")),
            "examples": metadata.get("examples", []),
            "configurable_items": self.context_schema.get_configurable_items(),
            "has_checkpointer": has_checkpointer,
            "capabilities": getattr(self, "capabilities", []),  # 智能体能力列表
        }

    async def get_config(self):
        return self.context_schema.from_file(module_name=self.module_name)

    async def stream_values(self, messages: list[str], input_context=None, **kwargs):
        graph = await self.get_graph()
        context = self._build_runtime_context(input_context)
        for event in graph.astream({"messages": messages}, stream_mode="values", context=context):
            yield event["messages"]

    async def stream_messages(self, messages: list[str], input_context=None, **kwargs):
        graph = await self.get_graph()
        context = self._build_runtime_context(input_context)
        logger.debug(f"stream_messages: {context}")

        # 构建配置：LangGraph 会自动从 checkpointer 恢复 state
        input_config = {
            "configurable": {"thread_id": context.thread_id, "user_id": context.user_id},
            "recursion_limit": 300,
        }

        # 官方文档标准用法：stream_mode="messages" 返回 (msg, metadata) 二元组
        # https://docs.langchain.com/oss/python/langgraph/streaming
        async for msg, metadata in graph.astream(
            {"messages": messages},
            stream_mode="messages",
            context=context,
            config=input_config,
        ):
            yield msg, metadata

    async def invoke_messages(self, messages: list[str], input_context=None, **kwargs):
        graph = await self.get_graph()
        context = self._build_runtime_context(input_context)
        logger.debug(f"invoke_messages: {context}")

        # 构建配置
        input_config = {
            "configurable": {"thread_id": context.thread_id, "user_id": context.user_id},
            "recursion_limit": 100,
        }

        msg = await graph.ainvoke(
            {"messages": messages},
            context=context,
            config=input_config,
        )
        return msg

    async def check_checkpointer(self, skip_graph_init: bool = False):
        """检查 checkpointer 是否可用

        Args:
            skip_graph_init: 如果为 True，则不初始化 Graph，仅检查 self.checkpointer
        """
        # 快速路径：如果已有共享 checkpointer，直接返回 True
        if self.checkpointer is not None:
            return True

        # 如果跳过 Graph 初始化，直接返回 False
        if skip_graph_init:
            return False

        app = await self.get_graph()
        if not hasattr(app, "checkpointer") or app.checkpointer is None:
            logger.warning(f"智能体 {self.name} 的 Graph 未配置 checkpointer，无法获取历史记录")
            return False
        return True

    async def get_history(self, user_id, thread_id) -> list[dict]:
        """获取历史消息"""
        try:
            app = await self.get_graph()

            if not await self.check_checkpointer():
                return []

            config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
            state = await app.aget_state(config)

            result = []
            if state:
                messages = state.values.get("messages", [])
                for msg in messages:
                    if hasattr(msg, "model_dump"):
                        msg_dict = msg.model_dump()  # 转换成字典
                    else:
                        msg_dict = dict(msg) if hasattr(msg, "__dict__") else {"content": str(msg)}
                    result.append(msg_dict)

            return result

        except Exception as e:
            logger.error(f"获取智能体 {self.name} 历史消息出错: {e}")
            return []

    def reload_graph(self):
        """重置 graph 缓存，强制下次调用 get_graph 时重新构建"""
        self.graph = None
        self.checkpointer = None
        if hasattr(self, "_graph_cache") and isinstance(getattr(self, "_graph_cache"), dict):
            getattr(self, "_graph_cache").clear()
        logger.info(f"{self.name} graph 缓存已清空，将在下次调用时重新构建")

    @abstractmethod
    async def get_graph(self, **kwargs) -> CompiledStateGraph:
        """
        获取并编译对话图实例。
        必须确保在编译时设置 checkpointer，否则将无法获取历史记录。
        例如: graph = workflow.compile(checkpointer=postgres_checkpointer)
        """
        pass

    async def _get_checkpointer(self):
        if self.checkpointer is not None:
            return self.checkpointer

        try:
            checkpointer = await self._get_postgres_checkpointer()
        except Exception as e:
            logger.error(f"构建 Graph 设置 Postgres checkpointer 时出错: {e}")
            raise RuntimeError("Postgres checkpointer 初始化失败，请检查配置与依赖") from e

        self.checkpointer = checkpointer
        return self.checkpointer

    async def _get_store(self):
        if self.store is not None:
            return self.store

        try:
            store = await self._get_postgres_store()
        except Exception as e:
            logger.error(f"构建 Graph 设置 Postgres store 时出错: {e}")
            raise RuntimeError("Postgres store 初始化失败，请检查配置与依赖") from e

        self.store = store
        return self.store

    @staticmethod
    def _resolve_postgres_url() -> str:
        postgres_url = (
            str(getattr(sys_config, "checkpointer_postgres_url", "") or "").strip()
            or os.getenv("CHECKPOINTER_POSTGRES_URL")
            or os.getenv("POSTGRES_URL")
        )
        if not postgres_url:
            raise RuntimeError("未配置 CHECKPOINTER_POSTGRES_URL/POSTGRES_URL")
        return BaseAgent._normalize_postgres_conninfo(postgres_url)

    async def _get_postgres_checkpointer(self):
        postgres_url = self._resolve_postgres_url()

        module_name = "langgraph.checkpoint.postgres.aio"
        try:
            module = importlib.import_module(module_name)
        except Exception:
            raise RuntimeError(f"未安装 {module_name}，请安装 langgraph-checkpoint-postgres") from None

        saver_cls = getattr(module, "AsyncPostgresSaver", None)
        if saver_cls is None:
            raise RuntimeError(f"{module_name} 不包含 AsyncPostgresSaver")

        saver = None
        from_conn_string = getattr(saver_cls, "from_conn_string", None)
        if callable(from_conn_string):
            saver = from_conn_string(postgres_url)
        else:
            saver = saver_cls(postgres_url)

        if hasattr(saver, "__aenter__") and hasattr(saver, "__aexit__"):
            saver_cm = saver
            saver = await saver_cm.__aenter__()
            self._postgres_saver_cm = saver_cm
        elif hasattr(saver, "__enter__") and hasattr(saver, "__exit__"):
            saver_cm = saver
            saver = saver_cm.__enter__()
            self._postgres_saver_cm = saver_cm

        setup_fn = getattr(saver, "setup", None)
        if callable(setup_fn):
            setup_result = setup_fn()
            if inspect.isawaitable(setup_result):
                await setup_result

        return saver

    async def _get_postgres_store(self):
        postgres_url = self._resolve_postgres_url()

        module_name = "langgraph.store.postgres"
        try:
            module = importlib.import_module(module_name)
        except Exception:
            raise RuntimeError(f"未安装 {module_name}") from None

        store_cls = getattr(module, "AsyncPostgresStore", None)
        if store_cls is None:
            raise RuntimeError(f"{module_name} 不包含 AsyncPostgresStore")

        store = None
        from_conn_string = getattr(store_cls, "from_conn_string", None)
        if callable(from_conn_string):
            store = from_conn_string(postgres_url)
        else:
            store = store_cls(postgres_url)

        if hasattr(store, "__aenter__") and hasattr(store, "__aexit__"):
            store_cm = store
            store = await store_cm.__aenter__()
            self._postgres_store_cm = store_cm
        elif hasattr(store, "__enter__") and hasattr(store, "__exit__"):
            store_cm = store
            store = store_cm.__enter__()
            self._postgres_store_cm = store_cm

        setup_fn = getattr(store, "setup", None)
        if callable(setup_fn):
            setup_result = setup_fn()
            if inspect.isawaitable(setup_result):
                await setup_result

        return store

    @staticmethod
    def _normalize_postgres_conninfo(raw_url: str) -> str:
        value = (raw_url or "").strip()
        if value.startswith("postgresql+asyncpg://"):
            return "postgresql://" + value[len("postgresql+asyncpg://") :]
        if value.startswith("postgresql+psycopg2://"):
            return "postgresql://" + value[len("postgresql+psycopg2://") :]
        if value.startswith("postgres+asyncpg://"):
            return "postgresql://" + value[len("postgres+asyncpg://") :]
        if value.startswith("postgres+psycopg2://"):
            return "postgresql://" + value[len("postgres+psycopg2://") :]
        return value

    def _normalize_input_context(self, input_context: dict | None = None) -> dict:
        normalized = dict(input_context or {})
        if "thread_id" in normalized and normalized["thread_id"] is not None:
            normalized["thread_id"] = str(normalized["thread_id"]).strip()
            if not normalized["thread_id"]:
                raise ValueError("thread_id 不能为空")
        if "user_id" in normalized and normalized["user_id"] is not None:
            normalized["user_id"] = str(normalized["user_id"]).strip()
            if not normalized["user_id"]:
                raise ValueError("user_id 不能为空")
        if "department_id" in normalized and normalized["department_id"] not in (None, ""):
            normalized["department_id"] = int(normalized["department_id"])
        if "agent_config_id" in normalized and normalized["agent_config_id"] not in (None, ""):
            normalized["agent_config_id"] = int(normalized["agent_config_id"])
        agent_config = normalized.get("agent_config")
        if agent_config is not None and not isinstance(agent_config, dict):
            raise ValueError("agent_config 必须为字典")
        return normalized

    def _build_runtime_context(self, input_context: dict | None = None):
        normalized = self._normalize_input_context(input_context)
        context = self.context_schema()
        agent_config = normalized.pop("agent_config", None)
        if isinstance(agent_config, dict):
            context.update(agent_config)
        context.update(normalized)

        context.thread_id = str(getattr(context, "thread_id", "") or "").strip() or str(uuid.uuid4())
        context.user_id = str(getattr(context, "user_id", "") or "").strip() or str(uuid.uuid4())
        return context

    def load_metadata(self) -> dict:
        """Load metadata from metadata.toml file in the agent's source directory."""
        if self._metadata_cache is not None:
            return self._metadata_cache

        # Try to find metadata.toml in the agent's source directory
        try:
            # Get the agent's source file directory
            agent_module = self.__class__.__module__

            # Use importlib to get the module's file path
            spec = importlib.util.find_spec(agent_module)
            if spec and spec.origin:
                agent_file = Path(spec.origin)
                agent_dir = agent_file.parent
            else:
                # Fallback: construct path from module name
                module_path = agent_module.replace(".", "/")
                agent_file = Path(f"src/{module_path}.py")
                agent_dir = agent_file.parent

            metadata_file = agent_dir / "metadata.toml"

            if metadata_file.exists():
                with open(metadata_file, "rb") as f:
                    metadata = tomli.load(f)
                    self._metadata_cache = metadata
                    logger.debug(f"Loaded metadata from {metadata_file}")
                    return metadata
            else:
                logger.debug(f"No metadata.toml found for {self.module_name} at {metadata_file}")
                self._metadata_cache = {}
                return {}

        except Exception as e:
            logger.error(f"Error loading metadata for {self.module_name}: {e}")
            self._metadata_cache = {}
            return {}
