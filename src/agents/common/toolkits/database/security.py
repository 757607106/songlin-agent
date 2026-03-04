"""通用 SQL 安全检查器 — 支持多数据库方言"""

import re


class SQLSecurityChecker:
    """通用 SQL 安全检查器，支持 MySQL / PostgreSQL / Oracle / MSSQL / SQLite"""

    # 允许的 SQL 操作（只读）
    ALLOWED_OPERATIONS = {"SELECT", "SHOW", "DESCRIBE", "EXPLAIN", "\\D"}

    # 危险关键词（禁止出现在语句开头）
    DANGEROUS_KEYWORDS = {
        "DROP",
        "DELETE",
        "UPDATE",
        "INSERT",
        "CREATE",
        "ALTER",
        "TRUNCATE",
        "REPLACE",
        "LOAD",
        "GRANT",
        "REVOKE",
        "SET",
        "COMMIT",
        "ROLLBACK",
        "UNLOCK",
        "KILL",
        "SHUTDOWN",
        "EXEC",
        "EXECUTE",
        "MERGE",
    }

    # SQL 注入模式
    SQL_INJECTION_PATTERNS = [
        r"\bor\s+1\s*=\s*1\b",
        r"\bunion\s+select\b",
        r"\bexec\s*\(",
        r"\bxp_cmdshell\b",
        r"\bsleep\s*\(",
        r"\bbenchmark\s*\(",
        r"\bwaitfor\s+delay\b",
        r"\bpg_sleep\s*\(",
        r"\bdbms_lock\.sleep\b",
        r"\b;\s*drop\b",
        r"\b;\s*delete\b",
        r"\b;\s*update\b",
        r"\b;\s*insert\b",
    ]

    @classmethod
    def validate_sql(cls, sql: str) -> bool:
        """验证 SQL 语句的安全性（只允许只读查询）"""
        if not sql or not sql.strip():
            return False

        # 移除注释
        sql_clean = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
        sql_clean = re.sub(r"/\*.*?\*/", "", sql_clean, flags=re.DOTALL)
        sql_upper = sql_clean.strip().upper()

        if not sql_upper:
            return False

        # 检查是否以允许的操作开头
        if not any(sql_upper.startswith(op) for op in cls.ALLOWED_OPERATIONS):
            return False

        # 检查语句开头是否为危险关键词
        first_word_match = re.match(r"^\s*(\w+)", sql_upper)
        first_word = first_word_match.group(1) if first_word_match else ""
        if first_word in cls.DANGEROUS_KEYWORDS:
            return False

        # 检查 SQL 注入模式
        for pattern in cls.SQL_INJECTION_PATTERNS:
            if re.search(pattern, sql_upper, re.IGNORECASE):
                return False

        return True

    @classmethod
    def check_sql(cls, sql: str) -> dict:
        """验证 SQL 并返回结构化结果

        Returns:
            {"safe": bool, "reason": str} — safe=True 表示通过检查
        """
        if not sql or not sql.strip():
            return {"safe": False, "reason": "SQL 语句为空"}

        sql_clean = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
        sql_clean = re.sub(r"/\*.*?\*/", "", sql_clean, flags=re.DOTALL)
        sql_upper = sql_clean.strip().upper()

        if not sql_upper:
            return {"safe": False, "reason": "SQL 语句为空（仅包含注释）"}

        if not any(sql_upper.startswith(op) for op in cls.ALLOWED_OPERATIONS):
            first_word = re.match(r"^\s*(\w+)", sql_upper)
            keyword = first_word.group(1) if first_word else sql_upper[:20]
            return {"safe": False, "reason": f"不允许的操作: {keyword}，只允许 SELECT/SHOW/DESCRIBE/EXPLAIN"}

        first_word_match = re.match(r"^\s*(\w+)", sql_upper)
        first_word = first_word_match.group(1) if first_word_match else ""
        if first_word in cls.DANGEROUS_KEYWORDS:
            return {"safe": False, "reason": f"检测到危险操作: {first_word}"}

        for pattern in cls.SQL_INJECTION_PATTERNS:
            if re.search(pattern, sql_upper, re.IGNORECASE):
                return {"safe": False, "reason": f"检测到 SQL 注入风险模式: {pattern}"}

        return {"safe": True, "reason": "通过安全检查"}

    @classmethod
    def validate_table_name(cls, table_name: str) -> bool:
        """验证表名安全性"""
        if not table_name:
            return False
        # 允许 schema.table 格式
        return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]*$", table_name))

    @classmethod
    def validate_timeout(cls, timeout: int) -> bool:
        """验证 timeout 参数"""
        return isinstance(timeout, int) and 1 <= timeout <= 600
