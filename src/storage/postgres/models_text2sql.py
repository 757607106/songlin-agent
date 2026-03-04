"""PostgreSQL Text2SQL 数据模型 - 数据库连接、Schema、值映射、查询历史等"""

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from src.storage.postgres.models_business import Base
from src.utils.datetime_utils import format_utc_datetime, utc_now_naive


class DBConnection(Base):
    """数据库连接配置"""

    __tablename__ = "db_connections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False, comment="连接名称")
    db_type = Column(String(20), nullable=False, comment="数据库类型: mysql/postgresql/sqlite")
    host = Column(String(255), nullable=True, comment="主机地址")
    port = Column(Integer, nullable=True, comment="端口")
    database = Column(String(100), nullable=False, comment="数据库名")
    username = Column(String(100), nullable=True, comment="用户名")
    password_encrypted = Column(Text, nullable=True, comment="加密后的密码")
    extra_params = Column(JSON, nullable=True, comment="额外连接参数")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否启用")

    created_by = Column(String(64), nullable=True)
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    # 关联关系
    schema_tables = relationship("SchemaTable", back_populates="connection", cascade="all, delete-orphan")
    value_mappings = relationship("ValueMapping", back_populates="connection", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_db_connections_dept_name", "department_id", "name", unique=True),)

    def to_dict(self, include_password: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "department_id": self.department_id,
            "name": self.name,
            "db_type": self.db_type,
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "username": self.username,
            "extra_params": self.extra_params or {},
            "is_active": bool(self.is_active),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }
        if include_password:
            result["password_encrypted"] = self.password_encrypted
        return result


class SchemaTable(Base):
    """数据库表 Schema"""

    __tablename__ = "schema_tables"

    id = Column(Integer, primary_key=True, autoincrement=True)
    connection_id = Column(Integer, ForeignKey("db_connections.id"), nullable=False, index=True)
    table_name = Column(String(100), nullable=False, comment="表名")
    table_comment = Column(String(500), nullable=True, comment="表注释")
    table_type = Column(String(20), nullable=True, default="TABLE", comment="表类型: TABLE/VIEW")

    # ReactFlow 位置信息
    position_x = Column(Integer, nullable=True, default=0)
    position_y = Column(Integer, nullable=True, default=0)

    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    # 关联关系
    connection = relationship("DBConnection", back_populates="schema_tables")
    columns = relationship("SchemaColumn", back_populates="table", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_schema_tables_conn_name", "connection_id", "table_name", unique=True),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "table_name": self.table_name,
            "table_comment": self.table_comment,
            "table_type": self.table_type,
            "position_x": self.position_x or 0,
            "position_y": self.position_y or 0,
            "columns": [col.to_dict() for col in self.columns] if self.columns else [],
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class SchemaColumn(Base):
    """数据库列 Schema"""

    __tablename__ = "schema_columns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    table_id = Column(Integer, ForeignKey("schema_tables.id"), nullable=False, index=True)
    column_name = Column(String(100), nullable=False, comment="列名")
    column_type = Column(String(100), nullable=False, comment="数据类型")
    column_comment = Column(String(500), nullable=True, comment="列注释")
    is_primary_key = Column(Boolean, nullable=False, default=False, comment="是否主键")
    is_nullable = Column(Boolean, nullable=False, default=True, comment="是否可空")
    default_value = Column(String(255), nullable=True, comment="默认值")
    ordinal_position = Column(Integer, nullable=True, comment="列顺序")

    created_at = Column(DateTime, default=utc_now_naive)

    # 关联关系
    table = relationship("SchemaTable", back_populates="columns")

    __table_args__ = (Index("ix_schema_columns_table_name", "table_id", "column_name", unique=True),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "table_id": self.table_id,
            "column_name": self.column_name,
            "column_type": self.column_type,
            "column_comment": self.column_comment,
            "is_primary_key": bool(self.is_primary_key),
            "is_nullable": bool(self.is_nullable),
            "default_value": self.default_value,
            "ordinal_position": self.ordinal_position,
        }


class SchemaRelationship(Base):
    """表关系（外键关联）"""

    __tablename__ = "schema_relationships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    connection_id = Column(Integer, ForeignKey("db_connections.id"), nullable=False, index=True)
    source_table = Column(String(100), nullable=False, comment="源表名")
    source_column = Column(String(100), nullable=False, comment="源列名")
    target_table = Column(String(100), nullable=False, comment="目标表名")
    target_column = Column(String(100), nullable=False, comment="目标列名")
    relationship_type = Column(String(20), nullable=True, default="one_to_many", comment="关系类型")

    created_at = Column(DateTime, default=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "source_table": self.source_table,
            "source_column": self.source_column,
            "target_table": self.target_table,
            "target_column": self.target_column,
            "relationship_type": self.relationship_type,
        }


class ValueMapping(Base):
    """值映射（自然语言 <-> 数据库值）"""

    __tablename__ = "value_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    connection_id = Column(Integer, ForeignKey("db_connections.id"), nullable=False, index=True)
    table_name = Column(String(100), nullable=False, comment="表名")
    column_name = Column(String(100), nullable=False, comment="列名")
    natural_value = Column(String(255), nullable=False, comment="自然语言值")
    db_value = Column(String(255), nullable=False, comment="数据库实际值")
    description = Column(String(500), nullable=True, comment="描述说明")

    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)

    # 关联关系
    connection = relationship("DBConnection", back_populates="value_mappings")

    __table_args__ = (Index("ix_value_mappings_lookup", "connection_id", "table_name", "column_name", "natural_value"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "table_name": self.table_name,
            "column_name": self.column_name,
            "natural_value": self.natural_value,
            "db_value": self.db_value,
            "description": self.description,
            "created_by": self.created_by,
            "created_at": format_utc_datetime(self.created_at),
        }


class QueryHistory(Base):
    """查询历史记录 — 用于混合检索和相似 SQL 推荐"""

    __tablename__ = "query_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    connection_id = Column(Integer, ForeignKey("db_connections.id"), nullable=False, index=True)
    question = Column(Text, nullable=False, comment="用户原始问题")
    sql = Column(Text, nullable=False, comment="生成的 SQL")
    tables_used = Column(JSON, nullable=True, comment='使用的表名列表 ["orders", "users"]')
    query_pattern = Column(String(50), nullable=True, comment="查询模式: JOIN/GROUP_BY/AGGREGATE/SIMPLE")
    execution_success = Column(Boolean, nullable=False, default=True, comment="是否执行成功")
    milvus_id = Column(String(100), nullable=True, comment="Milvus 向量 ID")
    # 增强字段：用于混合检索质量评分
    difficulty_level = Column(Integer, nullable=False, default=1, comment="查询难度 1-5")
    success_rate = Column(Float, nullable=False, default=1.0, comment="历史成功率 0.0-1.0")
    verified = Column(Boolean, nullable=False, default=False, comment="是否人工验证")
    created_at = Column(DateTime, default=utc_now_naive)

    __table_args__ = (
        Index("ix_query_history_conn_created", "connection_id", "created_at"),
        Index("ix_query_history_pattern_difficulty", "connection_id", "query_pattern", "difficulty_level"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "question": self.question,
            "sql": self.sql,
            "tables_used": self.tables_used or [],
            "query_pattern": self.query_pattern,
            "execution_success": bool(self.execution_success),
            "milvus_id": self.milvus_id,
            "difficulty_level": self.difficulty_level or 1,
            "success_rate": float(self.success_rate) if self.success_rate is not None else 1.0,
            "verified": bool(self.verified),
            "created_at": format_utc_datetime(self.created_at),
        }
