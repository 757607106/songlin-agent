"""Text2SQL Service - 数据库连接、Schema 发现、值映射业务逻辑"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, inspect, text

from src.repositories.text2sql_repository import (
    db_connection_repo,
    schema_column_repo,
    schema_relationship_repo,
    schema_table_repo,
    value_mapping_repo,
)
from src.utils import logger

# 加密密钥（从环境变量获取，不存在则生成）
_ENCRYPTION_KEY = os.environ.get("TEXT2SQL_ENCRYPTION_KEY")


def _get_fernet() -> Fernet:
    """获取 Fernet 加密实例"""
    global _ENCRYPTION_KEY
    if not _ENCRYPTION_KEY:
        # 使用 JWT_SECRET_KEY 派生加密密钥
        jwt_secret = os.environ.get("JWT_SECRET_KEY", "yuxi_know_secure_key")
        # 使用 SHA256 哈希并截取前 32 字节作为 Fernet 密钥
        import hashlib

        key_bytes = hashlib.sha256(jwt_secret.encode()).digest()
        _ENCRYPTION_KEY = base64.urlsafe_b64encode(key_bytes).decode()
    return Fernet(_ENCRYPTION_KEY.encode())


def encrypt_password(password: str) -> str:
    """加密密码"""
    if not password:
        return ""
    fernet = _get_fernet()
    return fernet.encrypt(password.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    """解密密码"""
    if not encrypted:
        return ""
    fernet = _get_fernet()
    return fernet.decrypt(encrypted.encode()).decode()


def _extract_json_payload(text_payload: str) -> dict[str, Any] | None:
    """从模型输出中尽量提取 JSON 对象。"""
    content = (text_payload or "").strip()
    if not content:
        return None

    if "```" in content:
        parts = content.split("```")
        for part in parts:
            chunk = part.strip()
            if not chunk:
                continue
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            try:
                obj = json.loads(chunk)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue

    try:
        obj = json.loads(content)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    match = re.search(r"{[\s\S]*}", content)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _fallback_analysis(question: str) -> dict[str, Any]:
    """当模型返回不可解析内容时，基于关键词生成回退分析。"""
    tokens = re.findall(r"[A-Za-z0-9\u4e00-\u9fff_]+", question.lower())
    filtered = [t for t in tokens if len(t) > 1]
    return _normalize_analysis(
        {
            "intent": question[:120],
            "tables": [],
            "columns": filtered[:10],
            "filters": [],
            "aggregations": [],
            "order_by": [],
            "group_by": [],
        },
        question,
    )


def _normalize_analysis(payload: dict[str, Any], question: str) -> dict[str, Any]:
    normalized = {
        "intent": question[:120],
        "tables": [],
        "columns": [],
        "filters": [],
        "aggregations": [],
        "order_by": [],
        "group_by": [],
    }
    normalized.update(payload or {})

    entities = normalized.get("entities")
    if not isinstance(entities, list):
        entities = list(normalized.get("tables", []) or [])

    relationships = normalized.get("relationships")
    if not isinstance(relationships, list):
        relationships = []

    query_intent = normalized.get("query_intent")
    if not isinstance(query_intent, str) or not query_intent.strip():
        query_intent = str(normalized.get("intent", "") or question[:120])

    likely_aggregations = normalized.get("likely_aggregations")
    if not isinstance(likely_aggregations, list):
        likely_aggregations = list(normalized.get("aggregations", []) or [])

    text_for_detect = f"{question} {query_intent}".lower()
    normalized["entities"] = entities
    normalized["relationships"] = relationships
    normalized["query_intent"] = query_intent
    normalized["likely_aggregations"] = likely_aggregations
    normalized["time_related"] = bool(normalized.get("time_related")) or any(
        token in text_for_detect for token in ["趋势", "按月", "按天", "同比", "环比", "time", "date", "month", "year"]
    )
    normalized["comparison_related"] = bool(normalized.get("comparison_related")) or any(
        token in text_for_detect for token in ["比较", "对比", "排名", "最高", "最低", "compare", "top", "rank"]
    )
    return normalized


def build_connection_url(
    db_type: str,
    host: str | None,
    port: int | None,
    database: str,
    username: str | None,
    password: str | None,
    extra_params: dict | None = None,
) -> str:
    """构建数据库连接 URL"""
    db_type = (db_type or "").lower()

    if db_type == "sqlite":
        return f"sqlite:///{database}"

    from urllib.parse import quote_plus

    auth = ""
    if username:
        auth = username
        if password:
            auth += f":{quote_plus(password)}"
        auth += "@"

    host_value = host or "localhost"
    port_str = f":{port}" if port else ""

    params = dict(extra_params or {})

    if db_type == "mysql":
        url = f"mysql+pymysql://{auth}{host_value}{port_str}/{database}"
    elif db_type in {"postgres", "postgresql"}:
        url = f"postgresql+psycopg2://{auth}{host_value}{port_str}/{database}"
    elif db_type in {"oracle", "oracledb"}:
        # 默认按 service_name 连接，兼容常见部署方式。
        if "service_name" not in params and database:
            params["service_name"] = database
        url = f"oracle+oracledb://{auth}{host_value}{port_str}/"
    elif db_type in {"mssql", "sqlserver"}:
        # 默认 pyodbc 驱动参数，可由 extra_params 覆盖。
        params.setdefault("driver", "ODBC Driver 18 for SQL Server")
        params.setdefault("TrustServerCertificate", "yes")
        url = f"mssql+pyodbc://{auth}{host_value}{port_str}/{database}"
    else:
        raise ValueError(f"Unsupported db_type: {db_type}")

    if params:
        encoded = "&".join(f"{k}={quote_plus(str(v))}" for k, v in params.items())
        url += f"?{encoded}"

    return url


class Text2SqlService:
    """Text2SQL 服务"""

    # ========== 连接管理 ==========

    async def get_connections(self, department_id: int) -> list[dict[str, Any]]:
        """获取部门的所有数据库连接"""
        connections = await db_connection_repo.get_by_department(department_id)
        return [conn.to_dict() for conn in connections]

    async def get_connection(self, connection_id: int) -> dict[str, Any] | None:
        """获取单个连接详情"""
        conn = await db_connection_repo.get_by_id(connection_id)
        return conn.to_dict() if conn else None

    async def create_connection(self, data: dict[str, Any]) -> dict[str, Any]:
        """创建数据库连接"""
        # 加密密码
        if "password" in data and data["password"]:
            data["password_encrypted"] = encrypt_password(data.pop("password"))
        elif "password" in data:
            data.pop("password")

        conn = await db_connection_repo.create(data)
        return conn.to_dict()

    async def update_connection(self, connection_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        """更新数据库连接"""
        # 加密密码
        if "password" in data:
            if data["password"]:
                data["password_encrypted"] = encrypt_password(data.pop("password"))
            else:
                data.pop("password")

        conn = await db_connection_repo.update(connection_id, data)
        return conn.to_dict() if conn else None

    async def delete_connection(self, connection_id: int) -> bool:
        """删除数据库连接（级联删除 Schema 和值映射）"""
        return await db_connection_repo.delete(connection_id)

    async def test_connection(self, connection_id: int) -> dict[str, Any]:
        """测试数据库连接"""
        conn = await db_connection_repo.get_by_id(connection_id)
        if not conn:
            return {"success": False, "message": "连接不存在"}

        try:
            password = decrypt_password(conn.password_encrypted) if conn.password_encrypted else None
            url = build_connection_url(
                conn.db_type, conn.host, conn.port, conn.database, conn.username, password, conn.extra_params
            )
            engine = create_engine(url, pool_pre_ping=True)
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            engine.dispose()
            return {"success": True, "message": "连接成功"}
        except Exception as e:
            logger.warning(f"Connection test failed for {connection_id}: {e}")
            return {"success": False, "message": str(e)}

    async def analyze_query(self, question: str, model_name: str | None = None) -> dict[str, Any]:
        """分析用户查询，提取意图与相关实体"""
        if not question:
            return {"success": False, "error": "question is empty"}

        from langchain_core.messages import HumanMessage

        from src.agents.common import load_chat_model
        from src.config import config

        model = load_chat_model(model_name or config.default_model)
        prompt = (
            "你是数据库查询分析专家。\n"
            "请分析用户问题，输出 JSON：\n"
            "{\n"
            '  "intent": "查询意图（如统计/列表/趋势）",\n'
            '  "tables": ["可能相关的表名"],\n'
            '  "columns": ["可能相关的列名"],\n'
            '  "filters": ["筛选条件"],\n'
            '  "aggregations": ["聚合函数或指标"],\n'
            '  "order_by": ["排序字段"],\n'
            '  "group_by": ["分组字段"],\n'
            '  "entities": ["相关实体（兼容字段，可与 tables 一致）"],\n'
            '  "relationships": ["实体关系描述"],\n'
            '  "query_intent": "查询意图（兼容字段）",\n'
            '  "likely_aggregations": ["可能聚合（兼容字段）"]\n'
            "}\n"
            "只返回 JSON，不要包含其他内容。\n"
            f"用户问题: {question}"
        )

        resp = await model.ainvoke([HumanMessage(content=prompt)])
        content = (resp.content or "").strip()

        data = _extract_json_payload(content)
        if not data:
            fallback = _fallback_analysis(question)
            return {
                "success": True,
                "analysis": fallback,
                "fallback": True,
                "raw": content[:500],
            }

        normalized = _normalize_analysis(data, question)
        return {"success": True, "analysis": normalized, "fallback": False}

    # ========== Schema 管理 ==========

    async def get_schema(self, connection_id: int) -> dict[str, Any]:
        """获取连接的 Schema 信息（表、列、关系）"""
        tables = await schema_table_repo.get_by_connection(connection_id)
        relationships = await schema_relationship_repo.get_by_connection(connection_id)
        return {
            "tables": tables,  # 已经是字典列表
            "relationships": [r.to_dict() for r in relationships],
        }

    async def discover_schema(self, connection_id: int) -> dict[str, Any]:
        """从数据库发现 Schema（自动获取表结构）"""
        conn = await db_connection_repo.get_by_id(connection_id)
        if not conn:
            raise ValueError("连接不存在")

        try:
            password = decrypt_password(conn.password_encrypted) if conn.password_encrypted else None
            url = build_connection_url(
                conn.db_type, conn.host, conn.port, conn.database, conn.username, password, conn.extra_params
            )
            engine = create_engine(url)
            inspector = inspect(engine)

            # 清除现有 Schema（注意顺序：先删除列，再删除表）
            await schema_relationship_repo.delete_by_connection(connection_id)
            await schema_column_repo.delete_by_connection(connection_id)
            await schema_table_repo.delete_by_connection(connection_id)

            # 获取所有表
            table_names = inspector.get_table_names()
            tables_data = []
            columns_data = []

            for idx, table_name in enumerate(table_names):
                # 表信息
                table_data = {
                    "connection_id": connection_id,
                    "table_name": table_name,
                    "table_comment": self._get_table_comment(inspector, table_name, conn.db_type),
                    "table_type": "TABLE",
                    "position_x": (idx % 4) * 300,
                    "position_y": (idx // 4) * 250,
                }
                tables_data.append(table_data)

            # 批量创建表
            created_tables = await schema_table_repo.batch_create(tables_data)
            table_id_map = {t.table_name: t.id for t in created_tables}

            # 获取列信息
            for table_name in table_names:
                table_id = table_id_map[table_name]
                columns = inspector.get_columns(table_name)
                pk_constraint = inspector.get_pk_constraint(table_name)
                # constrained_columns 是字符串列表，如 ['id', 'name']
                pk_columns = set(pk_constraint.get("constrained_columns") or [])

                for col_idx, col in enumerate(columns):
                    columns_data.append(
                        {
                            "table_id": table_id,
                            "column_name": col["name"],
                            "column_type": str(col["type"]),
                            "column_comment": col.get("comment"),
                            "is_primary_key": col["name"] in pk_columns,
                            "is_nullable": col.get("nullable", True),
                            "default_value": str(col.get("default")) if col.get("default") is not None else None,
                            "ordinal_position": col_idx,
                        }
                    )

            # 批量创建列
            if columns_data:
                await schema_column_repo.batch_create(columns_data)

            # 获取外键关系
            relationships_data = []
            for table_name in table_names:
                fks = inspector.get_foreign_keys(table_name)
                for fk in fks:
                    if fk.get("constrained_columns") and fk.get("referred_columns"):
                        relationships_data.append(
                            {
                                "connection_id": connection_id,
                                "source_table": table_name,
                                "source_column": fk["constrained_columns"][0],
                                "target_table": fk["referred_table"],
                                "target_column": fk["referred_columns"][0],
                                "relationship_type": "many_to_one",
                            }
                        )

            if relationships_data:
                await schema_relationship_repo.batch_create(relationships_data)

            engine.dispose()
            return await self.get_schema(connection_id)

        except Exception as e:
            logger.error(f"Schema discovery failed for connection {connection_id}: {e}")
            raise

    def _get_table_comment(self, inspector, table_name: str, db_type: str) -> str | None:
        """获取表注释"""
        try:
            if db_type == "mysql":
                # MySQL 使用 get_table_comment
                return inspector.get_table_comment(table_name).get("text")
            elif db_type == "postgresql":
                # PostgreSQL 使用 pg_description
                return inspector.get_table_comment(table_name).get("text")
        except Exception:
            pass
        return None

    async def update_table_position(self, table_id: int, position_x: int, position_y: int) -> dict[str, Any] | None:
        """更新表的位置（ReactFlow 拖拽）"""
        return await schema_table_repo.update(table_id, {"position_x": position_x, "position_y": position_y})

    async def update_table(self, table_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        """更新表信息（注释等）"""
        return await schema_table_repo.update(table_id, data)

    async def delete_table(self, table_id: int) -> bool:
        """删除表及其列"""
        return await schema_table_repo.delete(table_id)

    async def update_column(self, column_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        """更新列信息（注释等）"""
        column = await schema_column_repo.update(column_id, data)
        return column.to_dict() if column else None

    # ========== 关系管理 ==========

    async def create_relationship(self, data: dict[str, Any]) -> dict[str, Any]:
        """创建关系"""
        relationship = await schema_relationship_repo.create(data)
        return relationship.to_dict()

    async def update_relationship(self, relationship_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        """更新关系"""
        relationship = await schema_relationship_repo.update(relationship_id, data)
        return relationship.to_dict() if relationship else None

    async def delete_relationship(self, relationship_id: int) -> bool:
        """删除关系"""
        return await schema_relationship_repo.delete(relationship_id)

    # ========== 值映射管理 ==========

    async def get_value_mappings(self, connection_id: int) -> list[dict[str, Any]]:
        """获取连接的所有值映射"""
        mappings = await value_mapping_repo.get_by_connection(connection_id)
        return [m.to_dict() for m in mappings]

    async def create_value_mapping(self, data: dict[str, Any]) -> dict[str, Any]:
        """创建值映射"""
        mapping = await value_mapping_repo.create(data)
        return mapping.to_dict()

    async def batch_create_value_mappings(self, mappings_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """批量创建值映射"""
        mappings = await value_mapping_repo.batch_create(mappings_data)
        return [m.to_dict() for m in mappings]

    async def delete_value_mapping(self, mapping_id: int) -> bool:
        """删除值映射"""
        return await value_mapping_repo.delete(mapping_id)

    async def get_value_mappings_for_sql(
        self, connection_id: int, table_name: str | None = None, column_name: str | None = None
    ) -> dict[str, dict[str, str]]:
        """获取用于 SQL 生成的值映射（natural_value -> db_value）"""
        if table_name and column_name:
            mappings = await value_mapping_repo.get_by_table_column(connection_id, table_name, column_name)
        else:
            mappings = await value_mapping_repo.get_by_connection(connection_id)

        result: dict[str, dict[str, str]] = {}
        for m in mappings:
            key = f"{m.table_name}.{m.column_name}"
            if key not in result:
                result[key] = {}
            result[key][m.natural_value] = m.db_value
        return result


# 单例实例
text2sql_service = Text2SqlService()
