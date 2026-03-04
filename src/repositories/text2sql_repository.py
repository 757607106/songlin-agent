"""Text2SQL Repository - 数据库连接、Schema、值映射的数据访问层"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from src.storage.postgres.manager import pg_manager
from src.storage.postgres.models_text2sql import (
    DBConnection,
    QueryHistory,
    SchemaColumn,
    SchemaRelationship,
    SchemaTable,
    ValueMapping,
)


class DBConnectionRepository:
    """数据库连接 Repository"""

    async def get_by_department(self, department_id: int) -> list[DBConnection]:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(DBConnection).where(DBConnection.department_id == department_id).order_by(DBConnection.id)
            )
            return list(result.scalars().all())

    async def get_by_id(self, connection_id: int) -> DBConnection | None:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(DBConnection).where(DBConnection.id == connection_id))
            return result.scalar_one_or_none()

    async def get_by_id_with_schema(self, connection_id: int) -> DBConnection | None:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(DBConnection)
                .where(DBConnection.id == connection_id)
                .options(selectinload(DBConnection.schema_tables).selectinload(SchemaTable.columns))
            )
            return result.scalar_one_or_none()

    async def create(self, data: dict[str, Any]) -> DBConnection:
        conn = DBConnection(**data)
        async with pg_manager.get_async_session_context() as session:
            session.add(conn)
            await session.flush()
            await session.refresh(conn)
            return conn

    async def update(self, connection_id: int, data: dict[str, Any]) -> DBConnection | None:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(DBConnection).where(DBConnection.id == connection_id))
            conn = result.scalar_one_or_none()
            if conn is None:
                return None
            for key, value in data.items():
                setattr(conn, key, value)
            await session.flush()
            await session.refresh(conn)
            return conn

    async def delete(self, connection_id: int) -> bool:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(DBConnection).where(DBConnection.id == connection_id))
            conn = result.scalar_one_or_none()
            if conn is None:
                return False
            await session.delete(conn)
            return True


class SchemaTableRepository:
    """Schema 表 Repository"""

    async def get_by_connection(self, connection_id: int) -> list[dict[str, Any]]:
        """获取连接的所有表（返回字典，避免异步懒加载问题）"""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(SchemaTable)
                .where(SchemaTable.connection_id == connection_id)
                .options(selectinload(SchemaTable.columns))
                .order_by(SchemaTable.table_name)
            )
            tables = result.scalars().all()
            # 在会话内转换为字典，避免分离后懒加载问题
            return [t.to_dict() for t in tables]

    async def get_by_id(self, table_id: int) -> dict[str, Any] | None:
        """获取单个表（返回字典，避免异步懒加载问题）"""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(SchemaTable).where(SchemaTable.id == table_id).options(selectinload(SchemaTable.columns))
            )
            table = result.scalar_one_or_none()
            return table.to_dict() if table else None

    async def create(self, data: dict[str, Any]) -> SchemaTable:
        table = SchemaTable(**data)
        async with pg_manager.get_async_session_context() as session:
            session.add(table)
            await session.flush()
            await session.refresh(table)
            return table

    async def batch_create(self, tables_data: list[dict[str, Any]]) -> list[SchemaTable]:
        tables = [SchemaTable(**data) for data in tables_data]
        async with pg_manager.get_async_session_context() as session:
            session.add_all(tables)
            await session.flush()
            for table in tables:
                await session.refresh(table)
            return tables

    async def update(self, table_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        """更新表信息（返回字典，避免异步懒加载问题）"""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(SchemaTable).where(SchemaTable.id == table_id).options(selectinload(SchemaTable.columns))
            )
            table = result.scalar_one_or_none()
            if table is None:
                return None
            for key, value in data.items():
                setattr(table, key, value)
            await session.flush()
            await session.refresh(table)
            # 在会话内转换为字典
            return table.to_dict()

    async def delete(self, table_id: int) -> bool:
        """删除表（级联删除列）"""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(SchemaTable).where(SchemaTable.id == table_id))
            table = result.scalar_one_or_none()
            if table is None:
                return False
            await session.delete(table)
            return True

    async def delete_by_connection(self, connection_id: int) -> int:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(delete(SchemaTable).where(SchemaTable.connection_id == connection_id))
            return result.rowcount


class SchemaColumnRepository:
    """Schema 列 Repository"""

    async def get_by_id(self, column_id: int) -> SchemaColumn | None:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(SchemaColumn).where(SchemaColumn.id == column_id))
            return result.scalar_one_or_none()

    async def batch_create(self, columns_data: list[dict[str, Any]]) -> list[SchemaColumn]:
        columns = [SchemaColumn(**data) for data in columns_data]
        async with pg_manager.get_async_session_context() as session:
            session.add_all(columns)
            await session.flush()
            return columns

    async def update(self, column_id: int, data: dict[str, Any]) -> SchemaColumn | None:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(SchemaColumn).where(SchemaColumn.id == column_id))
            column = result.scalar_one_or_none()
            if column is None:
                return None
            for key, value in data.items():
                setattr(column, key, value)
            await session.flush()
            await session.refresh(column)
            return column

    async def delete_by_table(self, table_id: int) -> int:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(delete(SchemaColumn).where(SchemaColumn.table_id == table_id))
            return result.rowcount

    async def delete_by_connection(self, connection_id: int) -> int:
        """删除指定连接的所有列（通过关联表）"""
        async with pg_manager.get_async_session_context() as session:
            # 获取该连接的所有表 ID
            table_ids_result = await session.execute(
                select(SchemaTable.id).where(SchemaTable.connection_id == connection_id)
            )
            table_ids = [row[0] for row in table_ids_result.fetchall()]
            if not table_ids:
                return 0
            # 删除这些表的所有列
            result = await session.execute(delete(SchemaColumn).where(SchemaColumn.table_id.in_(table_ids)))
            return result.rowcount


class SchemaRelationshipRepository:
    """Schema 关系 Repository"""

    async def get_by_connection(self, connection_id: int) -> list[SchemaRelationship]:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(SchemaRelationship).where(SchemaRelationship.connection_id == connection_id)
            )
            return list(result.scalars().all())

    async def get_by_id(self, relationship_id: int) -> SchemaRelationship | None:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(SchemaRelationship).where(SchemaRelationship.id == relationship_id))
            return result.scalar_one_or_none()

    async def create(self, data: dict[str, Any]) -> SchemaRelationship:
        relationship = SchemaRelationship(**data)
        async with pg_manager.get_async_session_context() as session:
            session.add(relationship)
            await session.flush()
            await session.refresh(relationship)
            return relationship

    async def batch_create(self, relationships_data: list[dict[str, Any]]) -> list[SchemaRelationship]:
        relationships = [SchemaRelationship(**data) for data in relationships_data]
        async with pg_manager.get_async_session_context() as session:
            session.add_all(relationships)
            await session.flush()
            return relationships

    async def update(self, relationship_id: int, data: dict[str, Any]) -> SchemaRelationship | None:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(SchemaRelationship).where(SchemaRelationship.id == relationship_id))
            relationship = result.scalar_one_or_none()
            if relationship is None:
                return None
            for key, value in data.items():
                setattr(relationship, key, value)
            await session.flush()
            await session.refresh(relationship)
            return relationship

    async def delete(self, relationship_id: int) -> bool:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(SchemaRelationship).where(SchemaRelationship.id == relationship_id))
            relationship = result.scalar_one_or_none()
            if relationship is None:
                return False
            await session.delete(relationship)
            return True

    async def delete_by_connection(self, connection_id: int) -> int:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                delete(SchemaRelationship).where(SchemaRelationship.connection_id == connection_id)
            )
            return result.rowcount


class ValueMappingRepository:
    """值映射 Repository"""

    async def get_by_connection(self, connection_id: int) -> list[ValueMapping]:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(ValueMapping)
                .where(ValueMapping.connection_id == connection_id)
                .order_by(ValueMapping.table_name, ValueMapping.column_name)
            )
            return list(result.scalars().all())

    async def get_by_table_column(self, connection_id: int, table_name: str, column_name: str) -> list[ValueMapping]:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(ValueMapping).where(
                    ValueMapping.connection_id == connection_id,
                    ValueMapping.table_name == table_name,
                    ValueMapping.column_name == column_name,
                )
            )
            return list(result.scalars().all())

    async def create(self, data: dict[str, Any]) -> ValueMapping:
        mapping = ValueMapping(**data)
        async with pg_manager.get_async_session_context() as session:
            session.add(mapping)
            await session.flush()
            await session.refresh(mapping)
            return mapping

    async def batch_create(self, mappings_data: list[dict[str, Any]]) -> list[ValueMapping]:
        mappings = [ValueMapping(**data) for data in mappings_data]
        async with pg_manager.get_async_session_context() as session:
            session.add_all(mappings)
            await session.flush()
            return mappings

    async def delete(self, mapping_id: int) -> bool:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(ValueMapping).where(ValueMapping.id == mapping_id))
            mapping = result.scalar_one_or_none()
            if mapping is None:
                return False
            await session.delete(mapping)
            return True

    async def delete_by_connection(self, connection_id: int) -> int:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(delete(ValueMapping).where(ValueMapping.connection_id == connection_id))
            return result.rowcount


# 单例实例
db_connection_repo = DBConnectionRepository()
schema_table_repo = SchemaTableRepository()
schema_column_repo = SchemaColumnRepository()
schema_relationship_repo = SchemaRelationshipRepository()
value_mapping_repo = ValueMappingRepository()


class QueryHistoryRepository:
    """查询历史 Repository"""

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        history = QueryHistory(**data)
        async with pg_manager.get_async_session_context() as session:
            session.add(history)
            await session.flush()
            await session.refresh(history)
            return history.to_dict()

    async def get_by_connection(self, connection_id: int, limit: int = 200) -> list[dict[str, Any]]:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(QueryHistory)
                .where(QueryHistory.connection_id == connection_id)
                .order_by(QueryHistory.created_at.desc())
                .limit(limit)
            )
            return [h.to_dict() for h in result.scalars().all()]

    async def search_by_tables(
        self, connection_id: int, table_names: list[str], limit: int = 10
    ) -> list[dict[str, Any]]:
        """通过表名重叠搜索相关查询历史

        使用 text cast + LIKE 匹配 JSON 数组中的表名，兼容 JSON/JSONB。
        """
        async with pg_manager.get_async_session_context() as session:
            from sqlalchemy import String, cast, or_

            # 将 JSON 列转为文本后用 LIKE 匹配每个表名
            json_text = cast(QueryHistory.tables_used, String)
            conditions = [json_text.contains(name) for name in table_names]

            result = await session.execute(
                select(QueryHistory)
                .where(
                    QueryHistory.connection_id == connection_id,
                    QueryHistory.execution_success.is_(True),
                    or_(*conditions) if conditions else True,
                )
                .order_by(QueryHistory.created_at.desc())
                .limit(limit)
            )
            return [h.to_dict() for h in result.scalars().all()]

    async def search_by_pattern(
        self,
        connection_id: int,
        query_pattern: str,
        difficulty_level: int,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """通过查询模式和难度级别搜索相关查询历史

        匹配相同模式，难度级别在 +/-1 范围内的历史查询。
        """
        async with pg_manager.get_async_session_context() as session:
            from sqlalchemy import and_

            result = await session.execute(
                select(QueryHistory)
                .where(
                    and_(
                        QueryHistory.connection_id == connection_id,
                        QueryHistory.execution_success.is_(True),
                        QueryHistory.query_pattern == query_pattern,
                        QueryHistory.difficulty_level >= max(1, difficulty_level - 1),
                        QueryHistory.difficulty_level <= min(5, difficulty_level + 1),
                    )
                )
                .order_by(QueryHistory.success_rate.desc(), QueryHistory.created_at.desc())
                .limit(limit)
            )
            return [h.to_dict() for h in result.scalars().all()]


query_history_repo = QueryHistoryRepository()
