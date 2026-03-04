"""
Text2SQL Schema 迁移脚本

为 query_history 表添加混合检索所需的新字段：
- difficulty_level: 查询难度 (1-5)
- success_rate: 历史成功率 (0.0-1.0)
- verified: 是否人工验证

以及新增索引：
- ix_query_history_pattern_difficulty

使用方式：
    # 预览迁移（不执行）
    python scripts/migrate_text2sql_schema.py --dry-run

    # 执行迁移
    python scripts/migrate_text2sql_schema.py --execute

    # 验证迁移结果
    python scripts/migrate_text2sql_schema.py --verify
"""

import argparse
import asyncio
import os
import sys

# 确保路径正确
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from sqlalchemy import text

from src.storage.postgres.manager import pg_manager


# 迁移语句列表
MIGRATION_STATEMENTS = [
    # 新增字段
    "ALTER TABLE IF EXISTS query_history ADD COLUMN IF NOT EXISTS difficulty_level INTEGER DEFAULT 1",
    "ALTER TABLE IF EXISTS query_history ADD COLUMN IF NOT EXISTS success_rate DOUBLE PRECISION DEFAULT 1.0",
    "ALTER TABLE IF EXISTS query_history ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT FALSE",
    # 设置 NOT NULL 约束（需要先确保无空值）
    "UPDATE query_history SET difficulty_level = 1 WHERE difficulty_level IS NULL",
    "UPDATE query_history SET success_rate = 1.0 WHERE success_rate IS NULL",
    "UPDATE query_history SET verified = FALSE WHERE verified IS NULL",
    # 新增索引
    (
        "CREATE INDEX IF NOT EXISTS ix_query_history_pattern_difficulty "
        "ON query_history(connection_id, query_pattern, difficulty_level)"
    ),
]

# 验证查询
VERIFY_QUERIES = [
    # 检查字段是否存在
    """
    SELECT column_name, data_type, column_default, is_nullable
    FROM information_schema.columns
    WHERE table_name = 'query_history'
    AND column_name IN ('difficulty_level', 'success_rate', 'verified')
    ORDER BY column_name
    """,
    # 检查索引是否存在
    """
    SELECT indexname, indexdef
    FROM pg_indexes
    WHERE tablename = 'query_history'
    AND indexname = 'ix_query_history_pattern_difficulty'
    """,
]


async def preview_migration():
    """预览迁移语句"""
    print("\n" + "=" * 60)
    print("📋 Text2SQL Schema 迁移预览")
    print("=" * 60)

    print("\n将执行以下 SQL 语句:\n")
    for i, stmt in enumerate(MIGRATION_STATEMENTS, 1):
        print(f"  {i}. {stmt.strip()}")

    print("\n" + "-" * 60)
    print("💡 提示: 使用 --execute 参数执行迁移")
    print("-" * 60)


async def execute_migration():
    """执行迁移"""
    print("\n" + "=" * 60)
    print("🚀 Text2SQL Schema 迁移执行")
    print("=" * 60)

    pg_manager.initialize()

    success_count = 0
    error_count = 0

    async with pg_manager.async_engine.begin() as conn:
        for i, stmt in enumerate(MIGRATION_STATEMENTS, 1):
            try:
                await conn.execute(text(stmt))
                print(f"  ✅ [{i}/{len(MIGRATION_STATEMENTS)}] {stmt.strip()[:60]}...")
                success_count += 1
            except Exception as e:
                print(f"  ❌ [{i}/{len(MIGRATION_STATEMENTS)}] {stmt.strip()[:60]}...")
                print(f"      错误: {e}")
                error_count += 1

    print("\n" + "-" * 60)
    print(f"📊 迁移结果: 成功 {success_count}, 失败 {error_count}")
    print("-" * 60)

    if error_count == 0:
        print("✅ 迁移完成!")
    else:
        print("⚠️ 迁移完成但存在错误，请检查日志")


async def verify_migration():
    """验证迁移结果"""
    print("\n" + "=" * 60)
    print("🔍 Text2SQL Schema 迁移验证")
    print("=" * 60)

    pg_manager.initialize()

    async with pg_manager.async_engine.begin() as conn:
        # 验证字段
        print("\n📌 字段验证:")
        result = await conn.execute(text(VERIFY_QUERIES[0]))
        rows = result.fetchall()

        if len(rows) == 3:
            print("  ✅ 所有新字段已存在:")
            for row in rows:
                print(f"      - {row[0]}: {row[1]}, default={row[2]}, nullable={row[3]}")
        else:
            print(f"  ❌ 期望 3 个字段，实际找到 {len(rows)} 个")
            for row in rows:
                print(f"      - {row[0]}: {row[1]}")

        # 验证索引
        print("\n📌 索引验证:")
        result = await conn.execute(text(VERIFY_QUERIES[1]))
        rows = result.fetchall()

        if rows:
            print("  ✅ 索引已存在:")
            for row in rows:
                print(f"      - {row[0]}")
        else:
            print("  ❌ 索引 ix_query_history_pattern_difficulty 不存在")

        # 统计数据
        print("\n📌 数据统计:")
        result = await conn.execute(
            text(
                """
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN verified = TRUE THEN 1 END) as verified_count,
                AVG(difficulty_level) as avg_difficulty,
                AVG(success_rate) as avg_success_rate
            FROM query_history
        """
            )
        )
        row = result.fetchone()
        if row:
            print(f"      - 总记录数: {row[0]}")
            print(f"      - 已验证记录: {row[1]}")
            print(f"      - 平均难度: {row[2]:.2f}" if row[2] else "      - 平均难度: N/A")
            print(f"      - 平均成功率: {row[3]:.2f}" if row[3] else "      - 平均成功率: N/A")

    print("\n" + "-" * 60)
    print("✅ 验证完成!")
    print("-" * 60)


async def main():
    parser = argparse.ArgumentParser(description="Text2SQL Schema 迁移脚本")
    parser.add_argument("--dry-run", action="store_true", help="预览迁移（不执行）")
    parser.add_argument("--execute", action="store_true", help="执行迁移")
    parser.add_argument("--verify", action="store_true", help="验证迁移结果")

    args = parser.parse_args()

    if args.dry_run:
        await preview_migration()
    elif args.execute:
        await execute_migration()
    elif args.verify:
        await verify_migration()
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
