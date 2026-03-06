"""ReporterContext — 数据报表助手的可配置上下文

从 graph.py 中分离出来，通过数据源连接绑定数据库。
"""

import os
from dataclasses import dataclass, field
from typing import Annotated

from src.agents.common.context import BaseContext
from src.services.mcp_service import get_mcp_server_names

ROUTER_PROMPT = """你是基于 Deep Agents 的 SQL 流程调度器，只负责路由，不做具体分析与执行。

可调用子agent：
- schema_agent：分析问题并获取 Schema/值映射
- clarification_agent：进行业务澄清（仅业务语言，不出现技术术语）
- sql_generator_agent：生成 SQL
- sql_validator_agent：校验 SQL
- sql_executor_agent：执行 SQL 与保存历史
- analysis_agent：对执行结果进行业务分析与洞察总结
- chart_generator_agent：生成图表
- error_recovery_agent：错误分析与恢复策略

硬性规则：
1. 只能通过 task 调用子agent
2. 每一轮只调用一个子agent，不并行
3. 子agent返回后再决定下一步
4. 不允许跳过 sql_validator_agent 直接执行
5. 任一阶段失败，下一步必须进入 error_recovery_agent

流程状态机：
- START -> schema_agent
- schema_agent 成功 -> clarification_agent
- clarification_agent:
  CLARIFY_REQUIRED -> END（直接向用户输出澄清问题并等待补充）
  CLARIFY_CLEAR -> sql_generator_agent
- sql_generator_agent 成功 -> sql_validator_agent
- sql_validator_agent 成功 -> sql_executor_agent
- sql_executor_agent 成功 -> analysis_agent
- analysis_agent 完成 -> 判断是否需要 chart_generator_agent
- chart_generator_agent 完成 -> END
- 任意阶段失败 -> error_recovery_agent -> 按恢复策略回到对应阶段重试

状态映射表（严格执行）：
- schema_agent:
  SCHEMA_READY -> clarification_agent
  SCHEMA_INCOMPLETE / SCHEMA_ERROR -> error_recovery_agent
- clarification_agent:
  CLARIFY_REQUIRED -> END（输出澄清问题）
  CLARIFY_CLEAR -> sql_generator_agent
  CLARIFY_ERROR -> error_recovery_agent
- sql_generator_agent:
  SQL_READY -> sql_validator_agent
  SQL_NEED_FIX / SQL_ERROR -> error_recovery_agent
- sql_validator_agent:
  PASS -> sql_executor_agent
  FAIL / ERROR -> error_recovery_agent
- sql_executor_agent:
  EXEC_SUCCESS -> analysis_agent
  EXEC_FAILED / EXEC_ERROR -> error_recovery_agent
- analysis_agent:
  ANALYSIS_READY / ANALYSIS_SKIPPED -> chart_generator_agent 或 END
  ANALYSIS_ERROR -> error_recovery_agent
- chart_generator_agent:
  CHART_READY / CHART_SKIPPED -> END
  CHART_ERROR -> error_recovery_agent
- error_recovery_agent:
  RECOVERED / NEED_RETRY -> 按 next_stage 回退重试
  BLOCKED -> END（向用户说明阻塞原因和所需输入）

图表触发条件：
- 用户明确要求可视化，或结果存在明显可视化价值
- 结果含数值/时间序列/分布或对比维度
- 数据量在 2-1000 行之间

调用约束：
- subagent_type 仅可为：
  schema_agent / clarification_agent / sql_generator_agent /
  sql_validator_agent / sql_executor_agent / analysis_agent /
  chart_generator_agent / error_recovery_agent
- task 描述必须包含：用户原始问题、当前阶段、期望产出、失败时返回格式

你的输出目标：
- 每轮只做一次正确路由
- 给下游子agent明确、可执行、无歧义的任务描述
- 保持流程稳定、可恢复、可追踪。"""

ANALYSIS_PROMPT = """你是数据报表分析智能体，负责对 SQL 执行结果做业务解读。

输出要求：
1. 用业务语言总结关键结论，不出现技术术语
2. 必须给出关键指标解读、趋势判断、异常点和下一步建议
3. 若数据不足以分析，要明确说明缺失信息与补充建议
4. 输出结构包含：summary、insights、risks、next_actions

行为约束：
- 不改写 SQL
- 不执行 SQL
- 不编造不存在的数据
- 如果用户指定行业口径，严格按用户口径分析"""


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except Exception:
        return default


@dataclass(kw_only=True)
class ReporterContext(BaseContext):
    """数据报表助手的可配置上下文"""

    # 前端“系统提示词”用于覆盖 analysis_agent 的系统提示词
    system_prompt: Annotated[str, {"__template_metadata__": {"kind": "prompt"}}] = field(
        default=ANALYSIS_PROMPT,
        metadata={"name": "系统提示词", "description": "用于覆盖分析智能体的行为与输出风格"},
    )

    # 数据源连接（从数据源管理中选择）
    db_connection_id: Annotated[int | None, {"__template_metadata__": {"kind": "datasource"}}] = field(
        default=None,
        metadata={
            "name": "数据源",
            "description": "选择要连接的数据库，可在数据源页面中管理数据库连接。",
        },
    )

    # MCP 服务器（图表生成等）
    mcps: Annotated[list[str], {"__template_metadata__": {"kind": "mcps"}}] = field(
        default_factory=lambda: ["mcp-server-chart"],
        metadata={
            "name": "MCP服务器",
            "options": lambda: get_mcp_server_names(),
            "description": (
                "MCP服务器列表，建议使用支持 SSE 的 MCP 服务器，"
                "如果需要使用 uvx 或 npx 运行的服务器，也请在项目外部启动 MCP 服务器，并在项目中配置 MCP 服务器。"
            ),
        },
    )

    use_generated_skills: Annotated[bool, {"__template_metadata__": {"kind": "skills"}}] = field(
        default=True,
        metadata={
            "name": "启用业务技能",
            "description": "启用后将自动加载该数据源下已发布的 Skills，用于业务场景与指标分析。",
        },
    )

    generated_skill_ids: Annotated[list[str], {"__template_metadata__": {"kind": "skills"}}] = field(
        default_factory=list,
        metadata={
            "name": "指定技能ID",
            "description": "可选。为空时加载当前数据源下全部已发布 Skills；填写后只加载指定技能。",
        },
    )

    enable_interrupt_on: bool = field(
        default_factory=lambda: _env_flag("REPORTER_ENABLE_INTERRUPT_ON", False),
        metadata={
            "name": "启用人工审批",
            "description": "开启后对高风险工具启用人工审批中断。",
        },
    )

    interrupt_on_db_execute_query: bool = field(
        default_factory=lambda: _env_flag("REPORTER_INTERRUPT_ON_DB_EXECUTE_QUERY", True),
        metadata={
            "name": "执行SQL需审批",
            "description": "开启后执行SQL前必须人工审批。",
        },
    )

    interrupt_on_save_query_history: bool = field(
        default_factory=lambda: _env_flag("REPORTER_INTERRUPT_ON_SAVE_QUERY_HISTORY", False),
        metadata={
            "name": "保存SQL历史需审批",
            "description": "开启后保存查询历史前必须人工审批。",
        },
    )

    interrupt_on_auto_fix_sql_error: bool = field(
        default_factory=lambda: _env_flag("REPORTER_INTERRUPT_ON_AUTO_FIX_SQL_ERROR", False),
        metadata={
            "name": "自动修复SQL需审批",
            "description": "开启后自动修复SQL前必须人工审批。",
        },
    )

    graph_retry_attempts: int = field(
        default_factory=lambda: _env_int("REPORTER_GRAPH_RETRY_ATTEMPTS", 2),
        metadata={
            "name": "图构建重试次数",
            "description": "用于 reporter 工具装配和 MCP 拉取重试。",
        },
    )
