"""查询历史服务 — Milvus 向量存储 + PostgreSQL 元数据 + 混合检索

基于老项目 Text2SQL 混合检索系统迁移增强：
- 三层检索：语义(Milvus) + 结构(PostgreSQL) + 模式(PostgreSQL)
- 动态权重融合排序
- 质量评分机制
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from dataclasses import dataclass

from src.utils import logger

# Milvus 可用性检查
try:
    from pymilvus import (
        Collection,
        CollectionSchema,
        DataType,
        FieldSchema,
        connections,
        utility,
    )

    MILVUS_AVAILABLE = True
except ImportError:
    MILVUS_AVAILABLE = False

COLLECTION_NAME = "text2sql_history"
CONNECTION_ALIAS = "text2sql_history"

# 混合检索配置
MIN_SIMILARITY_THRESHOLD = 0.5  # 最低相似度阈值
DEFAULT_TOP_K = 5


@dataclass
class RetrievalResult:
    """检索结果"""

    id: int
    question: str
    sql: str
    tables_used: list[str]
    query_pattern: str
    difficulty_level: int
    success_rate: float
    verified: bool
    semantic_score: float = 0.0
    structural_score: float = 0.0
    pattern_score: float = 0.0
    quality_score: float = 0.0
    final_score: float = 0.0
    explanation: str = ""


def _extract_tables(sql: str) -> list[str]:
    """从 SQL 中提取 FROM/JOIN 后的表名"""
    pattern = r"(?:FROM|JOIN)\s+[`\"]?(\w+)[`\"]?"
    return list(dict.fromkeys(re.findall(pattern, sql, re.IGNORECASE)))


def _classify_pattern(sql: str) -> str:
    """按 SQL 结构分类查询模式"""
    upper = sql.upper()
    if "JOIN" in upper:
        return "JOIN"
    if "GROUP BY" in upper:
        return "GROUP_BY"
    if re.search(r"\b(COUNT|SUM|AVG|MAX|MIN)\s*\(", upper):
        return "AGGREGATE"
    return "SIMPLE"


def _estimate_difficulty(sql: str) -> int:
    """估算查询难度 (1-5)"""
    difficulty = 1
    upper = sql.upper()

    if "JOIN" in upper:
        difficulty += 1
    if "GROUP BY" in upper:
        difficulty += 1
    if "HAVING" in upper or "SUBQUERY" in upper or sql.count("SELECT") > 1:
        difficulty += 1
    if "UNION" in upper:
        difficulty += 1

    return min(5, difficulty)


def _extract_table_keywords(question: str, known_tables: list[str] | None = None) -> list[str]:
    """从用户问题中提取可能的表名关键词（用于结构检索）"""
    if not known_tables:
        return []
    question_lower = question.lower()
    return [t for t in known_tables if t.lower() in question_lower]


def _calculate_quality_score(record: dict) -> float:
    """计算问答对的质量分数 (0.0-1.0)"""
    quality_score = 0.0

    # 验证状态加分 (30%)
    if record.get("verified", False):
        quality_score += 0.3

    # 成功率加分 (50%)
    success_rate = record.get("success_rate", 1.0)
    quality_score += success_rate * 0.5

    # 难度适中加分 (20%): 难度 2-3 的问答对通常质量较高
    difficulty = record.get("difficulty_level", 1)
    if 2 <= difficulty <= 3:
        quality_score += 0.2

    return min(1.0, quality_score)


def _calculate_dynamic_weights(semantic_score: float) -> dict[str, float]:
    """根据语义相似度动态调整权重

    策略：
    - 语义相似度很高时，更信任语义检索
    - 语义相似度较低时，更依赖结构和模式匹配
    """
    if semantic_score >= 0.9:
        return {"semantic": 0.80, "structural": 0.10, "pattern": 0.05, "quality": 0.05}
    if semantic_score >= 0.7:
        return {"semantic": 0.70, "structural": 0.15, "pattern": 0.10, "quality": 0.05}
    if semantic_score >= 0.5:
        return {"semantic": 0.60, "structural": 0.20, "pattern": 0.10, "quality": 0.10}
    # 语义匹配较差时，更多依赖结构和模式
    return {"semantic": 0.40, "structural": 0.35, "pattern": 0.20, "quality": 0.05}


def _generate_explanation(result: RetrievalResult) -> str:
    """生成推荐解释"""
    explanations = []

    # 语义相似度解释
    if result.semantic_score >= 0.9:
        explanations.append(f"语义高度相似({result.semantic_score:.2f})")
    elif result.semantic_score >= 0.7:
        explanations.append(f"语义相似({result.semantic_score:.2f})")
    elif result.semantic_score >= 0.5:
        explanations.append(f"语义部分相似({result.semantic_score:.2f})")

    # 结构相似度解释
    if result.structural_score > 0.7:
        explanations.append("使用相同的表结构")
    elif result.structural_score > 0.3:
        explanations.append("使用部分相同的表")

    # 模式匹配解释
    if result.pattern_score > 0.5:
        explanations.append(f"匹配 {result.query_pattern} 查询模式")

    # 质量指标解释
    if result.verified:
        explanations.append("已验证的高质量示例")

    return "; ".join(explanations) if explanations else "相关示例"


class QueryHistoryService:
    """查询历史的向量存储与混合检索服务"""

    def __init__(self):
        self._collection: Collection | None = None
        self._connected = False
        self._embed_model = None
        self._embed_dim: int | None = None
        self._warmup_task: asyncio.Task | None = None
        self._warmup_done = False

    async def prewarm(self) -> None:
        if self._warmup_done:
            return
        try:
            self._get_embed_model()
            collection = await asyncio.to_thread(self._get_or_create_collection)
            await asyncio.to_thread(collection.load)
            self._warmup_done = True
            logger.info("QueryHistoryService: warmup completed")
        except Exception as e:
            logger.warning(f"QueryHistoryService: warmup failed: {e}")

    def start_warmup(self) -> None:
        if self._warmup_done:
            return
        if self._warmup_task is not None and not self._warmup_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._warmup_task = loop.create_task(self.prewarm())

    def _ensure_connection(self):
        """确保 Milvus 连接已建立"""
        if self._connected:
            return
        if not MILVUS_AVAILABLE:
            raise ImportError("pymilvus is not installed")

        uri = os.getenv("MILVUS_URI") or "http://localhost:19530"
        token = os.getenv("MILVUS_TOKEN") or ""
        connections.connect(alias=CONNECTION_ALIAS, uri=uri, token=token)
        self._connected = True
        logger.info(f"QueryHistoryService: connected to Milvus at {uri}")

    def _get_embed_model(self):
        """延迟加载 embedding 模型"""
        if self._embed_model is None:
            from src.config import config
            from src.models import select_embedding_model

            self._embed_model = select_embedding_model(config.embed_model)
            self._embed_dim = config.embed_model_names[config.embed_model].dimension
        return self._embed_model

    def _get_or_create_collection(self) -> Collection:
        """获取或创建 Milvus 集合"""
        if self._collection is not None:
            return self._collection

        self._ensure_connection()
        embed_dim = self._embed_dim or self._get_embed_model() and self._embed_dim

        if utility.has_collection(COLLECTION_NAME, using=CONNECTION_ALIAS):
            self._collection = Collection(name=COLLECTION_NAME, using=CONNECTION_ALIAS)
        else:
            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=100, is_primary=True),
                FieldSchema(name="question", dtype=DataType.VARCHAR, max_length=2000),
                FieldSchema(name="connection_id", dtype=DataType.INT64),
                FieldSchema(name="history_id", dtype=DataType.INT64),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=embed_dim),
            ]
            schema = CollectionSchema(fields=fields, description="Text2SQL query history vectors")
            self._collection = Collection(name=COLLECTION_NAME, schema=schema, using=CONNECTION_ALIAS)
            self._collection.create_index(
                "embedding",
                {"metric_type": "COSINE", "index_type": "IVF_FLAT", "params": {"nlist": 128}},
            )
            logger.info(f"QueryHistoryService: created collection {COLLECTION_NAME} (dim={embed_dim})")

        return self._collection

    async def save(self, connection_id: int, question: str, sql: str, success: bool = True) -> None:
        """保存成功的查询到 Milvus + PostgreSQL"""
        from src.repositories.text2sql_repository import query_history_repo

        tables_used = _extract_tables(sql)
        pattern = _classify_pattern(sql)
        difficulty = _estimate_difficulty(sql)
        milvus_id = str(uuid.uuid4())

        # 1. 写 PostgreSQL
        pg_record = await query_history_repo.create(
            {
                "connection_id": connection_id,
                "question": question,
                "sql": sql,
                "tables_used": tables_used,
                "query_pattern": pattern,
                "difficulty_level": difficulty,
                "success_rate": 1.0 if success else 0.0,
                "verified": False,
                "execution_success": success,
                "milvus_id": milvus_id,
            }
        )
        history_id = pg_record["id"]

        # 2. 写 Milvus
        try:
            embed_model = self._get_embed_model()
            embeddings = await embed_model.aencode([question])
            collection = await asyncio.to_thread(self._get_or_create_collection)

            entities = [
                [milvus_id],
                [question[:2000]],
                [connection_id],
                [history_id],
                embeddings,
            ]

            def _insert():
                collection.insert(entities)

            await asyncio.to_thread(_insert)
            logger.info(f"QueryHistoryService: saved history_id={history_id}, milvus_id={milvus_id}")
        except Exception as e:
            logger.warning(f"QueryHistoryService: Milvus insert failed (PG record kept): {e}")

    async def search(
        self,
        connection_id: int,
        question: str,
        top_k: int = DEFAULT_TOP_K,
        min_similarity: float = MIN_SIMILARITY_THRESHOLD,
        schema_tables: list[str] | None = None,
    ) -> list[dict]:
        """三层混合检索: 语义(Milvus) + 结构(PG) + 模式(PG) → 动态权重融合排序"""
        from src.repositories.text2sql_repository import query_history_repo

        # --- 语义检索 ---
        semantic_results: dict[int, float] = {}  # history_id -> similarity
        try:
            embed_model = self._get_embed_model()
            embeddings = await embed_model.aencode([question])
            collection = await asyncio.to_thread(self._get_or_create_collection)

            search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}

            def _search():
                collection.load()
                return collection.search(
                    data=embeddings,
                    anns_field="embedding",
                    param=search_params,
                    limit=top_k * 3,
                    expr=f"connection_id == {connection_id}",
                    output_fields=["history_id"],
                )

            results = await asyncio.to_thread(_search)
            if results and len(results) > 0:
                for hit in results[0]:
                    hid = hit.entity.get("history_id")
                    semantic_results[hid] = float(hit.distance)  # COSINE distance = similarity
        except Exception as e:
            logger.warning(f"QueryHistoryService: Milvus search failed: {e}")

        # --- 结构检索 ---
        structural_ids: set[int] = set()
        known_tables: set[str] = set()
        try:
            # 获取已知表名用于关键词匹配
            recent = await query_history_repo.get_by_connection(connection_id, limit=50)
            for r in recent:
                known_tables.update(r.get("tables_used", []))

            # 如果提供了 schema_tables，也加入已知表名
            if schema_tables:
                known_tables.update(schema_tables)

            table_keywords = _extract_table_keywords(question, list(known_tables))
            if table_keywords:
                struct_results = await query_history_repo.search_by_tables(
                    connection_id, table_keywords, limit=top_k * 3
                )
                structural_ids = {r["id"] for r in struct_results}
        except Exception as e:
            logger.warning(f"QueryHistoryService: structural search failed: {e}")

        # --- 模式检索 ---
        pattern_ids: dict[int, float] = {}  # history_id -> pattern_score
        try:
            estimated_pattern = _classify_pattern(question)  # 简单估算用户可能想要的模式
            estimated_difficulty = _estimate_difficulty(question)

            pattern_results = await query_history_repo.search_by_pattern(
                connection_id, estimated_pattern, estimated_difficulty, limit=top_k * 3
            )
            for r in pattern_results:
                pattern_ids[r["id"]] = 0.5  # 基础模式匹配分数
        except Exception as e:
            logger.warning(f"QueryHistoryService: pattern search failed: {e}")

        # --- 融合排序 ---
        all_ids = set(semantic_results.keys()) | structural_ids | set(pattern_ids.keys())
        if not all_ids:
            return []

        # 获取所有候选记录的完整信息
        all_records = await query_history_repo.get_by_connection(connection_id, limit=200)
        record_map = {r["id"]: r for r in all_records}

        # 计算表重叠度（如果有 schema_tables）
        def calc_structural_score(record: dict) -> float:
            if not schema_tables:
                return 1.0 if record["id"] in structural_ids else 0.0
            record_tables = set(record.get("tables_used", []))
            overlap = len(record_tables & set(schema_tables))
            return overlap / max(len(schema_tables), 1)

        retrieval_results: list[RetrievalResult] = []
        for hid in all_ids:
            record = record_map.get(hid)
            if not record:
                continue

            sem_score = semantic_results.get(hid, 0.0)
            struct_score = calc_structural_score(record)
            pat_score = pattern_ids.get(hid, 0.0)
            qual_score = _calculate_quality_score(record)

            # 动态权重计算
            weights = _calculate_dynamic_weights(sem_score)
            final_score = (
                sem_score * weights["semantic"]
                + struct_score * weights["structural"]
                + pat_score * weights["pattern"]
                + qual_score * weights["quality"]
            )

            result = RetrievalResult(
                id=record["id"],
                question=record["question"],
                sql=record["sql"],
                tables_used=record.get("tables_used", []),
                query_pattern=record.get("query_pattern", "SIMPLE"),
                difficulty_level=record.get("difficulty_level", 1),
                success_rate=record.get("success_rate", 1.0),
                verified=record.get("verified", False),
                semantic_score=sem_score,
                structural_score=struct_score,
                pattern_score=pat_score,
                quality_score=qual_score,
                final_score=final_score,
            )
            result.explanation = _generate_explanation(result)
            retrieval_results.append(result)

        # 按最终分数排序并过滤
        retrieval_results.sort(key=lambda x: x.final_score, reverse=True)

        # 过滤低于最小相似度阈值的结果
        filtered = [r for r in retrieval_results if r.final_score >= min_similarity]

        return [
            {
                "question": r.question,
                "sql": r.sql,
                "similarity": round(r.final_score, 4),
                "semantic_score": round(r.semantic_score, 4),
                "structural_score": round(r.structural_score, 4),
                "pattern_score": round(r.pattern_score, 4),
                "quality_score": round(r.quality_score, 4),
                "query_pattern": r.query_pattern,
                "difficulty_level": r.difficulty_level,
                "verified": r.verified,
                "explanation": r.explanation,
            }
            for r in filtered[:top_k]
        ]


query_history_service = QueryHistoryService()
