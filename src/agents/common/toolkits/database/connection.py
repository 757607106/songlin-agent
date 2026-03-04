"""多数据库连接管理器 — 基于 langchain_community SQLDatabase"""

from __future__ import annotations

import threading
from typing import Any
from urllib.parse import quote_plus

from langchain_community.utilities import SQLDatabase

from src.utils import logger

# 支持的数据库类型及其驱动前缀
DB_DRIVERS: dict[str, str] = {
    "mysql": "mysql+pymysql",
    "postgresql": "postgresql+psycopg2",
    "postgres": "postgresql+psycopg2",
    "oracle": "oracle+cx_Oracle",
    "mssql": "mssql+pyodbc",
    "sqlite": "sqlite",
}


def build_connection_string(db_type: str, config: dict[str, Any]) -> str:
    """根据数据库类型和配置构建 SQLAlchemy 连接字符串

    Args:
        db_type: 数据库类型 (mysql / postgresql / oracle / mssql / sqlite)
        config: 连接配置 dict, 包含 host, port, user, password, database 等

    Returns:
        SQLAlchemy 连接 URI
    """
    db_type_lower = db_type.lower().strip()
    driver = DB_DRIVERS.get(db_type_lower)
    if driver is None:
        raise ValueError(f"不支持的数据库类型: {db_type}，支持的类型: {list(DB_DRIVERS.keys())}")

    # SQLite 特殊处理
    if db_type_lower == "sqlite":
        db_path = config.get("database", ":memory:")
        return f"sqlite:///{db_path}"

    # 通用的关系型数据库连接串
    user = quote_plus(str(config.get("user", "")))
    password = quote_plus(str(config.get("password", "")))
    host = config.get("host", "localhost")
    port = config.get("port", _default_port(db_type_lower))
    database = config.get("database", "")

    base_uri = f"{driver}://{user}:{password}@{host}:{port}/{database}"

    # MSSQL 需要额外的 driver 参数
    if db_type_lower == "mssql":
        odbc_driver = config.get("odbc_driver", "ODBC+Driver+17+for+SQL+Server")
        base_uri += f"?driver={odbc_driver}"

    return base_uri


def _default_port(db_type: str) -> int:
    """返回数据库默认端口"""
    ports = {
        "mysql": 3306,
        "postgresql": 5432,
        "postgres": 5432,
        "oracle": 1521,
        "mssql": 1433,
    }
    return ports.get(db_type, 3306)


class DatabaseConnectionManager:
    """多数据库连接管理器

    线程安全，复用 SQLDatabase 实例。
    通过 db_type + config 唯一确定一个连接。
    """

    # 模块级缓存：避免同一个 db_type+config 反复创建实例
    _instances: dict[str, DatabaseConnectionManager] = {}
    _instances_lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_type: str, config: dict[str, Any]) -> DatabaseConnectionManager:
        """获取或创建连接管理器实例（同一配置复用同一实例）"""
        key = (
            f"{db_type.lower().strip()}|{config.get('host', '')}:{config.get('port', '')}:{config.get('database', '')}"
        )
        with cls._instances_lock:
            if key not in cls._instances:
                cls._instances[key] = cls(db_type, config)
            return cls._instances[key]

    def __init__(self, db_type: str, config: dict[str, Any]):
        self.db_type = db_type.lower().strip()
        self.config = config
        self._db: SQLDatabase | None = None
        self._lock = threading.Lock()
        self._connection_uri = build_connection_string(self.db_type, config)
        self._connection_error: str | None = None  # 缓存连接错误

    def get_db(self) -> SQLDatabase:
        """获取 SQLDatabase 实例（懒初始化 + 线程安全 + 错误缓存）"""
        if self._db is not None:
            return self._db

        # 如果之前已经连接失败，直接报错不再重试
        if self._connection_error is not None:
            raise ConnectionError(self._connection_error)

        with self._lock:
            if self._db is None and self._connection_error is None:
                logger.info(f"正在创建 {self.db_type} 数据库连接...")
                try:
                    self._db = SQLDatabase.from_uri(self._connection_uri)
                    logger.info(f"{self.db_type} 数据库连接创建成功")
                except Exception as e:
                    self._connection_error = f"无法连接数据库 ({self.db_type}): {e}"
                    logger.error(f"{self.db_type} 数据库连接失败: {e}")
                    raise ConnectionError(self._connection_error) from e

            if self._connection_error is not None:
                raise ConnectionError(self._connection_error)
            return self._db

    def test_connection(self) -> bool:
        """测试数据库连接是否可用"""
        try:
            db = self.get_db()
            db.run("SELECT 1")
            return True
        except Exception as e:
            logger.warning(f"数据库连接测试失败: {e}")
            return False

    def get_table_info(self) -> str:
        """获取数据库 schema 信息（表结构文本）"""
        db = self.get_db()
        return db.get_table_info()

    def get_usable_table_names(self) -> list[str]:
        """获取所有可用表名"""
        db = self.get_db()
        return db.get_usable_table_names()

    def run_query(self, sql: str) -> str:
        """执行查询并返回结果文本"""
        db = self.get_db()
        return db.run(sql)

    def close(self):
        """关闭连接"""
        with self._lock:
            if self._db is not None:
                try:
                    self._db._engine.dispose()
                except Exception:
                    pass
                self._db = None
                logger.info(f"{self.db_type} 数据库连接已关闭")

    @property
    def dialect(self) -> str:
        """返回当前数据库方言名称"""
        db = self.get_db()
        return db.dialect

    def __repr__(self) -> str:
        return f"DatabaseConnectionManager(db_type={self.db_type!r})"
