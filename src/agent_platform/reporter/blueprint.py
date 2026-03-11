from __future__ import annotations

import os

from src.agent_platform.blueprint.models import AgentBlueprint, BlueprintWorker
from src.agent_platform.types import ExecutionMode, WorkerKind
from src.agents.reporter.agents import (
    build_analysis_system_prompt,
    build_chart_system_prompt,
    build_clarification_system_prompt,
    build_error_recovery_system_prompt,
    build_sample_retrieval_system_prompt,
    build_schema_system_prompt,
    build_sql_executor_system_prompt,
    build_sql_generator_system_prompt,
    build_sql_validator_system_prompt,
)
from src.agents.reporter.context import ROUTER_PROMPT, ReporterContext

REPORTER_NAME = "数据库报表助手"
REPORTER_DESCRIPTION = (
    "保留现有数据库报表流程的内置业务 agent，"
    "通过受控的 Schema -> SQL -> Validation -> Execution -> Analysis 流程回答问题。"
)
REPORTER_GOAL = "通过稳定、可审计、可恢复的数据库查询流程生成报表结论"
REPORTER_SCOPE = "仅覆盖数据库结构分析、SQL 生成校验执行、结果分析和可选图表生成"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _interrupt_on_tools(context: ReporterContext) -> list[str]:
    if not context.enable_interrupt_on:
        return []
    interrupt_on: list[str] = []
    if context.interrupt_on_db_execute_query:
        interrupt_on.append("db_execute_query")
    if context.interrupt_on_save_query_history:
        interrupt_on.append("save_query_history")
    if context.interrupt_on_auto_fix_sql_error:
        interrupt_on.append("auto_fix_sql_error")
    return interrupt_on


def build_reporter_blueprint(
    context: ReporterContext,
    *,
    resolved_skill_sources: list[str] | None = None,
) -> AgentBlueprint:
    schema_simplified_mode = _env_flag("SCHEMA_SIMPLIFIED_MODE", True)
    include_sample_worker = (
        not resolved_skill_sources
        if resolved_skill_sources is not None
        else not context.use_generated_skills
    )
    include_chart_worker = bool(context.mcps)

    worker_sequence: list[BlueprintWorker] = [
        BlueprintWorker(
            key="schema_worker",
            name="Schema Worker",
            description="分析用户问题并获取相关数据库 Schema 与值映射。",
            objective="为后续澄清和 SQL 生成准备结构化数据库上下文。",
            system_prompt=build_schema_system_prompt(schema_simplified_mode),
            kind=WorkerKind.RETRIEVAL,
            tools=[
                "analyze_user_query",
                "retrieve_database_schema",
                *(
                    []
                    if schema_simplified_mode
                    else [
                        "validate_schema_completeness",
                        "load_database_schema",
                        "db_list_tables",
                        "db_describe_table",
                    ]
                ),
            ],
            allowed_next=["clarification_worker", "error_recovery_worker"],
        ),
        BlueprintWorker(
            key="clarification_worker",
            name="Clarification Worker",
            description="在 Schema 已就绪后进行业务澄清，确认口径与范围。",
            objective="确认用户口径，避免 SQL 在业务定义上偏航。",
            system_prompt=build_clarification_system_prompt(),
            depends_on=["schema_worker"],
            allowed_next=[
                "sample_retrieval_worker" if include_sample_worker else "sql_generation_worker",
                "error_recovery_worker",
            ],
        ),
    ]

    if include_sample_worker:
        worker_sequence.append(
            BlueprintWorker(
                key="sample_retrieval_worker",
                name="Sample Retrieval Worker",
                description="检索并筛选高质量历史 SQL 样本，为 SQL 生成提供参考。",
                objective="用历史样本提升 SQL 生成的准确性和稳定性。",
                system_prompt=build_sample_retrieval_system_prompt(),
                kind=WorkerKind.RETRIEVAL,
                tools=["search_similar_queries", "analyze_sample_relevance"],
                depends_on=["clarification_worker"],
                allowed_next=["sql_generation_worker", "error_recovery_worker"],
            )
        )

    previous_worker = "sample_retrieval_worker" if include_sample_worker else "clarification_worker"
    worker_sequence.extend(
        [
            BlueprintWorker(
                key="sql_generation_worker",
                name="SQL Generation Worker",
                description="基于 Schema 与样本结果生成 SQL。",
                objective="生成满足业务口径的 SQL 草案。",
                system_prompt=build_sql_generator_system_prompt(),
                kind=WorkerKind.TOOL,
                tools=["generate_sql_query"],
                depends_on=[previous_worker],
                allowed_next=["sql_validation_worker", "error_recovery_worker"],
            ),
            BlueprintWorker(
                key="sql_validation_worker",
                name="SQL Validation Worker",
                description="校验 SQL 的语法、安全和可执行性。",
                objective="阻止不安全或不可执行 SQL 进入执行阶段。",
                system_prompt=build_sql_validator_system_prompt(),
                kind=WorkerKind.TOOL,
                tools=["validate_sql"],
                depends_on=["sql_generation_worker"],
                allowed_next=["sql_execution_worker", "error_recovery_worker"],
            ),
            BlueprintWorker(
                key="sql_execution_worker",
                name="SQL Execution Worker",
                description="执行 SQL 并在成功后保存查询历史。",
                objective="执行通过校验的 SQL，并产出结构化结果。",
                system_prompt=build_sql_executor_system_prompt(),
                kind=WorkerKind.TOOL,
                tools=["db_execute_query", "save_query_history"],
                depends_on=["sql_validation_worker"],
                allowed_next=["analysis_worker", "error_recovery_worker"],
            ),
            BlueprintWorker(
                key="analysis_worker",
                name="Analysis Worker",
                description="对 SQL 执行结果进行业务分析与洞察总结。",
                objective="把结构化结果转成业务洞察和建议。",
                system_prompt=build_analysis_system_prompt(context.system_prompt),
                kind=WorkerKind.REASONING,
                depends_on=["sql_execution_worker"],
                allowed_next=[
                    *(["chart_worker"] if include_chart_worker else []),
                    "error_recovery_worker",
                ],
            ),
        ]
    )

    if include_chart_worker:
        worker_sequence.append(
            BlueprintWorker(
                key="chart_worker",
                name="Chart Worker",
                description="在结果适合可视化时生成图表与简要解读。",
                objective="为数值型结果生成图表表达。",
                system_prompt=build_chart_system_prompt(),
                kind=WorkerKind.TOOL,
                mcps=list(context.mcps),
                depends_on=["analysis_worker"],
                allowed_next=["error_recovery_worker"],
            )
        )

    recovery_targets = [worker.key for worker in worker_sequence]
    worker_sequence.append(
        BlueprintWorker(
            key="error_recovery_worker",
            name="Error Recovery Worker",
            description="分析失败原因并输出恢复策略或自动修复建议。",
            objective="让流程在失败时可恢复、可解释、可重试。",
            system_prompt=build_error_recovery_system_prompt(),
            kind=WorkerKind.TOOL,
            tools=[
                "analyze_error_pattern",
                "generate_recovery_strategy",
                "auto_fix_sql_error",
                *(
                    []
                    if not schema_simplified_mode
                    else ["db_list_tables", "db_describe_table"]
                ),
            ],
            depends_on=[worker.key for worker in worker_sequence],
            allowed_next=recovery_targets,
        )
    )

    return AgentBlueprint(
        name=REPORTER_NAME,
        description=REPORTER_DESCRIPTION,
        goal=REPORTER_GOAL,
        task_scope=REPORTER_SCOPE,
        execution_mode=ExecutionMode.SUPERVISOR,
        system_prompt=ROUTER_PROMPT,
        supervisor_prompt=ROUTER_PROMPT,
        default_model=context.model,
        product_agent=True,
        mcps=list(context.mcps),
        skills=list(resolved_skill_sources or context.generated_skill_ids) if context.use_generated_skills else [],
        long_term_memory_namespace="builtin/reporter",
        interrupt_on_tools=_interrupt_on_tools(context),
        max_parallel_workers=1,
        max_dynamic_workers=0,
        workers=worker_sequence,
        tags=["builtin", "reporter", "database"],
    )
