from __future__ import annotations

import asyncio
import json
import re
from typing import Annotated, Any, TypedDict

from deepagents import create_deep_agent
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.graph.state import CompiledStateGraph
import yaml

from src.agent_platform.reporter.spec import build_reporter_spec
from src.agent_platform.spec.models import AgentSpec, WorkerSpec
from src.agents.common import load_chat_model
from src.agents.common.deepagent_runtime import create_state_store_backend
from src.agents.common.middlewares import save_attachments_to_fs
from src.agents.reporter.context import ReporterContext

_RECOVERY_TARGET_MAP = {
    "schema_analysis": "schema_worker",
    "clarification": "clarification_worker",
    "sample_retrieval": "sample_retrieval_worker",
    "sql_generation": "sql_generation_worker",
    "sql_validation": "sql_validation_worker",
    "sql_execution": "sql_execution_worker",
    "analysis": "analysis_worker",
    "chart_generation": "chart_worker",
    "chart": "chart_worker",
}
_FINAL_RESPONSE_NODE = "final_response"


class ReporterSupervisorState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    attachments: list[dict[str, Any]]
    files: dict[str, Any]
    todos: list[dict[str, Any]]
    route_log: list[str]
    stage_outputs: dict[str, dict[str, Any]]
    active_worker: str | None


def _message_text(message: AnyMessage | None) -> str:
    if message is None:
        return ""
    if isinstance(message, str):
        return message
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text") or ""))
        return "".join(chunks)
    return str(content)


def _parse_payload_text(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    if text.startswith("```"):
        parts = text.split("```")
        for part in parts:
            candidate = part.strip()
            if not candidate:
                continue
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate:
                text = candidate
                break
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    try:
        import json_repair

        parsed = json_repair.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    yaml_candidate = re.sub(r"(?m)^(\s*)\d+[.)]\s+", r"\1- ", text)
    try:
        parsed = yaml.safe_load(yaml_candidate)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    parsed = _parse_stage_output_key_values(text)
    return parsed or None


def _parse_stage_output(message: AnyMessage | None, *, fallback_status: str = "ERROR") -> dict[str, Any]:
    text = _message_text(message).strip()
    if not text:
        return {"status": fallback_status, "summary": "worker 未返回内容"}
    parsed = _parse_payload_text(text)
    if parsed:
        return parsed
    return {"status": fallback_status, "summary": text}


def _parse_stage_output_key_values(text: str) -> dict[str, Any] | None:
    parsed: dict[str, Any] = {}
    current_key: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = re.match(r"^([A-Za-z_][A-Za-z0-9_\- ]*):\s*(.*)$", line)
        if match:
            current_key = match.group(1).strip().replace(" ", "_")
            value = match.group(2).strip()
            if value:
                parsed[current_key] = value
            else:
                parsed[current_key] = []
            continue

        if current_key is None:
            continue

        list_match = re.match(r"^(?:[-*]|\d+[.)])\s+(.*)$", line)
        if list_match:
            existing = parsed.get(current_key)
            if not isinstance(existing, list):
                existing = [] if existing in (None, "") else [str(existing)]
            existing.append(list_match.group(1).strip())
            parsed[current_key] = existing
            continue

        existing = parsed.get(current_key)
        if isinstance(existing, list):
            existing.append(line)
        elif existing:
            parsed[current_key] = f"{existing}\n{line}"
        else:
            parsed[current_key] = line

    return parsed or None


def _normalize_input_messages(messages: list[Any]) -> list[AnyMessage]:
    normalized: list[AnyMessage] = []
    for message in messages:
        if isinstance(message, str):
            normalized.append(HumanMessage(content=message))
            continue
        normalized.append(message)
    return normalized


def _trim_prompt_value(
    value: Any,
    *,
    max_string: int = 4000,
    max_list_items: int = 8,
    max_dict_items: int = 16,
) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if len(text) <= max_string:
            return text
        return text[:max_string].rstrip() + "\n...(truncated)"
    if isinstance(value, dict):
        trimmed: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_dict_items:
                break
            if item in (None, "", [], {}):
                continue
            trimmed[key] = _trim_prompt_value(
                item,
                max_string=max_string,
                max_list_items=max_list_items,
                max_dict_items=max_dict_items,
            )
        return trimmed
    if isinstance(value, (list, tuple)):
        return [
            _trim_prompt_value(
                item,
                max_string=max_string,
                max_list_items=max_list_items,
                max_dict_items=max_dict_items,
            )
            for item in list(value)[:max_list_items]
        ]
    return value


_WORKER_CONTEXT_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "clarification_worker": {
        "schema_worker": ("status", "summary", "schema_text", "query_analysis", "value_mappings"),
    },
    "sample_retrieval_worker": {
        "clarification_worker": ("status", "summary", "clarified_scope"),
        "schema_worker": ("summary", "query_analysis"),
    },
    "sql_generation_worker": {
        "schema_worker": ("status", "summary", "schema_text", "query_analysis", "value_mappings"),
        "clarification_worker": ("status", "summary", "clarified_scope"),
        "sample_retrieval_worker": ("status", "summary", "recommended_samples", "qa_pairs"),
    },
    "sql_validation_worker": {
        "sql_generation_worker": ("status", "summary", "generated_sql", "sql"),
    },
    "sql_execution_worker": {
        "sql_generation_worker": ("status", "generated_sql", "sql"),
        "sql_validation_worker": ("status", "summary", "details"),
    },
    "analysis_worker": {
        "clarification_worker": ("status", "clarified_scope", "summary"),
        "sql_execution_worker": ("status", "summary", "executed_sql", "result", "note", "truncated"),
    },
    "chart_worker": {
        "clarification_worker": ("status", "clarified_scope"),
        "sql_execution_worker": ("status", "summary", "result"),
        "analysis_worker": ("status", "summary", "insights", "risks", "next_actions"),
    },
}


def _extract_tool_payloads(messages: list[AnyMessage]) -> list[dict[str, Any] | str]:
    payloads: list[dict[str, Any] | str] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        text = _message_text(message).strip()
        if not text:
            continue
        payloads.append(_parse_payload_text(text) or text)
    return payloads


def _latest_tool_payload(
    payloads: list[dict[str, Any] | str],
    *,
    stage: str | None = None,
    keys: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    for payload in reversed(payloads):
        if not isinstance(payload, dict):
            continue
        if stage is not None and str(payload.get("stage") or "").strip().lower() != stage:
            continue
        if keys and not any(key in payload for key in keys):
            continue
        return payload
    return None


def _enrich_stage_output(
    worker_key: str,
    stage_output: dict[str, Any],
    messages: list[AnyMessage],
) -> dict[str, Any]:
    payload = dict(stage_output)
    tool_payloads = _extract_tool_payloads(messages)

    if worker_key == "schema_worker":
        tool_payload = _latest_tool_payload(tool_payloads, stage="schema_analysis", keys=("schema_text", "tables"))
        if tool_payload:
            for key in ("schema_text", "tables", "relationships", "value_mappings", "query_analysis", "schema_selection"):
                if key in tool_payload and key not in payload:
                    payload[key] = tool_payload[key]
    elif worker_key == "sample_retrieval_worker":
        tool_payload = _latest_tool_payload(
            tool_payloads,
            stage="sample_retrieval",
            keys=("recommended_samples", "qa_pairs"),
        )
        if tool_payload:
            for key in ("recommended_samples", "qa_pairs", "retrieval_mode"):
                if key in tool_payload and key not in payload:
                    payload[key] = tool_payload[key]
    elif worker_key == "sql_generation_worker":
        tool_payload = _latest_tool_payload(tool_payloads, stage="sql_generation", keys=("sql",))
        if tool_payload:
            generated_sql = tool_payload.get("sql")
            if generated_sql and "generated_sql" not in payload:
                payload["generated_sql"] = generated_sql
            if generated_sql and "sql" not in payload:
                payload["sql"] = generated_sql
            for key in ("samples_used", "db_type"):
                if key in tool_payload and key not in payload:
                    payload[key] = tool_payload[key]
    elif worker_key == "sql_validation_worker":
        tool_payload = _latest_tool_payload(tool_payloads, stage="sql_validation", keys=("is_valid", "details"))
        if tool_payload:
            for key in ("is_valid", "details"):
                if key in tool_payload and key not in payload:
                    payload[key] = tool_payload[key]
    elif worker_key == "sql_execution_worker":
        tool_payload = _latest_tool_payload(
            tool_payloads,
            stage="sql_execution",
            keys=("executed_sql", "result", "error"),
        )
        if tool_payload:
            for key in ("executed_sql", "result", "truncated", "note", "error", "hint"):
                if key in tool_payload and key not in payload:
                    payload[key] = tool_payload[key]
    elif worker_key == "error_recovery_worker":
        tool_payload = _latest_tool_payload(
            tool_payloads,
            stage="error_recovery",
            keys=("strategy", "suggested_next_stage", "fixed_sql"),
        ) or _latest_tool_payload(
            tool_payloads,
            keys=("strategy", "suggested_next_stage", "fixed_sql"),
        )
        if tool_payload:
            if "next_stage" not in payload and tool_payload.get("suggested_next_stage"):
                payload["next_stage"] = tool_payload["suggested_next_stage"]
            for key in ("strategy", "suggested_next_stage", "fixed_sql", "fixes_applied"):
                if key in tool_payload and key not in payload:
                    payload[key] = tool_payload[key]

    return payload


def _select_stage_context(stage_output: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    selected = {field: stage_output[field] for field in fields if field in stage_output}
    if "status" in stage_output and "status" not in selected:
        selected["status"] = stage_output["status"]
    if "summary" in stage_output and "summary" not in selected:
        selected["summary"] = stage_output["summary"]
    return _trim_prompt_value(selected)


def _build_worker_context_payload(worker_key: str, state: ReporterSupervisorState) -> dict[str, Any]:
    stage_outputs = dict(state.get("stage_outputs") or {})
    if worker_key == "error_recovery_worker":
        route_log = list(state.get("route_log") or [])
        failed_worker = next((key for key in reversed(route_log[:-1]) if key != "error_recovery_worker"), None)
        payload = {
            "route_log": route_log[:-1],
            "failed_worker": failed_worker,
        }
        if failed_worker:
            payload["failed_stage_output"] = _trim_prompt_value(stage_outputs.get(failed_worker) or {})
        return payload

    config = _WORKER_CONTEXT_FIELDS.get(worker_key) or {}
    payload: dict[str, Any] = {}
    for stage_key, fields in config.items():
        stage_output = stage_outputs.get(stage_key) or {}
        if not stage_output:
            continue
        selected = _select_stage_context(stage_output, fields)
        if selected:
            payload[stage_key] = selected
    return payload


def _build_worker_input_messages(worker_key: str, state: ReporterSupervisorState) -> list[AnyMessage]:
    messages = _normalize_input_messages(list(state.get("messages") or []))
    context_payload = _build_worker_context_payload(worker_key, state)
    if context_payload:
        messages.append(
            HumanMessage(
                content=(
                    "内部执行上下文：请继续围绕最初的用户问题推进，"
                    "不要把本条消息当成新的用户需求，也不要原样复述给用户。\n"
                    f"当前阶段: {worker_key}\n"
                    "可用上游结果:\n"
                    f"{json.dumps(context_payload, ensure_ascii=False, indent=2, default=str)}"
                )
            )
        )
    return messages


def _next_worker_for_stage(
    worker_key: str,
    stage_output: dict[str, Any],
    *,
    spec: AgentSpec,
) -> str:
    status = str(stage_output.get("status") or "").strip().upper()
    worker_map = {worker.key: worker for worker in spec.workers}
    has_sample = "sample_retrieval_worker" in worker_map
    has_chart = "chart_worker" in worker_map

    if worker_key == "schema_worker":
        return "clarification_worker" if status == "SCHEMA_READY" else "error_recovery_worker"
    if worker_key == "clarification_worker":
        if status == "CLARIFY_REQUIRED":
            return END
        if status == "CLARIFY_CLEAR":
            return "sample_retrieval_worker" if has_sample else "sql_generation_worker"
        return "error_recovery_worker"
    if worker_key == "sample_retrieval_worker":
        if status in {"SAMPLE_READY", "SAMPLE_EMPTY", "SAMPLE_LOW_QUALITY"}:
            return "sql_generation_worker"
        return "error_recovery_worker"
    if worker_key == "sql_generation_worker":
        return "sql_validation_worker" if status == "SQL_READY" else "error_recovery_worker"
    if worker_key == "sql_validation_worker":
        return "sql_execution_worker" if status == "PASS" else "error_recovery_worker"
    if worker_key == "sql_execution_worker":
        return "analysis_worker" if status == "EXEC_SUCCESS" else "error_recovery_worker"
    if worker_key == "analysis_worker":
        if status in {"ANALYSIS_READY", "ANALYSIS_SKIPPED"}:
            return "chart_worker" if has_chart else END
        return "error_recovery_worker"
    if worker_key == "chart_worker":
        return END if status in {"CHART_READY", "CHART_SKIPPED"} else "error_recovery_worker"
    if worker_key == "error_recovery_worker":
        if status not in {"RECOVERED", "NEED_RETRY"}:
            return END
        next_stage = str(stage_output.get("next_stage") or "").strip().lower()
        target = _RECOVERY_TARGET_MAP.get(next_stage)
        if target == "sample_retrieval_worker" and "sample_retrieval_worker" not in worker_map:
            return "sql_generation_worker"
        if target == "chart_worker" and "chart_worker" not in worker_map:
            return END
        return target or END
    return END


def _activation_node_name(worker_key: str) -> str:
    return f"activate__{worker_key}"


def _stringify_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                items.append(text)
        return items
    text = str(value).strip()
    return [text] if text else []


def _latest_stage_payload(state: ReporterSupervisorState) -> dict[str, Any]:
    stage_outputs = dict(state.get("stage_outputs") or {})
    for worker_key in reversed(list(state.get("route_log") or [])):
        payload = stage_outputs.get(worker_key)
        if isinstance(payload, dict) and payload:
            return payload
    for payload in reversed(list(stage_outputs.values())):
        if isinstance(payload, dict) and payload:
            return payload
    return {}


def _format_reporter_final_message(state: ReporterSupervisorState) -> str:
    stage_outputs = dict(state.get("stage_outputs") or {})
    clarification = dict(stage_outputs.get("clarification_worker") or {})
    clarification_status = str(clarification.get("status") or "").strip().upper()
    if clarification_status == "CLARIFY_REQUIRED":
        summary = (_stringify_items(clarification.get("summary")) or ["还需要补充业务信息后才能继续分析。"])[0]
        questions = _stringify_items(clarification.get("clarification_questions"))
        text_parts = [summary]
        if questions:
            question_lines = "\n".join(
                f"{index}. {question}" for index, question in enumerate(questions, start=1)
            )
            text_parts.append(
                "请补充以下信息：\n" + question_lines
            )
        return "\n\n".join(text_parts)

    recovery = dict(stage_outputs.get("error_recovery_worker") or {})
    recovery_status = str(recovery.get("status") or "").strip().upper()
    if recovery and recovery_status not in {"RECOVERED", "NEED_RETRY"}:
        parts = _stringify_items(recovery.get("summary")) or ["当前请求暂时无法继续执行。"]
        root_causes = _stringify_items(recovery.get("root_cause"))
        next_actions = _stringify_items(recovery.get("next_action"))
        if root_causes:
            parts.append(f"原因：{'；'.join(root_causes[:3])}")
        if next_actions:
            parts.append(f"建议：{'；'.join(next_actions[:3])}")
        return "\n\n".join(parts)

    analysis = dict(stage_outputs.get("analysis_worker") or {})
    chart = dict(stage_outputs.get("chart_worker") or {})
    execution = dict(stage_outputs.get("sql_execution_worker") or {})
    sql_validation = dict(stage_outputs.get("sql_validation_worker") or {})

    parts: list[str] = []
    business_scope = _stringify_items(clarification.get("clarified_scope"))
    if business_scope:
        parts.append(f"业务口径：{business_scope[0]}")

    for payload in (analysis, chart, execution, sql_validation):
        summaries = _stringify_items(payload.get("summary"))
        if summaries:
            summary = summaries[0]
            if summary not in parts:
                parts.append(summary)

    insights = _stringify_items(analysis.get("insights"))
    if insights:
        parts.append("关键洞察：" + "；".join(insights[:5]))

    risks = _stringify_items(analysis.get("risks"))
    if risks:
        parts.append("风险提示：" + "；".join(risks[:3]))

    next_actions = _stringify_items(analysis.get("next_actions")) or _stringify_items(chart.get("next_action"))
    if next_actions:
        parts.append("建议下一步：" + "；".join(next_actions[:3]))

    chart_status = str(chart.get("status") or "").strip().upper()
    if chart_status == "CHART_SKIPPED":
        reasons = _stringify_items(chart.get("reason"))
        if reasons:
            parts.append(f"未生成图表：{reasons[0]}")

    if parts:
        return "\n\n".join(parts)

    latest_payload = _latest_stage_payload(state)
    latest_summary = _stringify_items(latest_payload.get("summary"))
    if latest_summary:
        return latest_summary[0]

    latest_status = str(latest_payload.get("status") or "").strip().upper()
    if latest_status:
        return f"本次报表流程已结束，当前状态：{latest_status}。"
    return "本次报表流程已结束。"


def _worker_error_output(
    worker_key: str,
    *,
    message: str,
    error_type: str,
) -> dict[str, Any]:
    return {
        "status": "ERROR",
        "summary": message,
        "worker": worker_key,
        "error_type": error_type,
        "next_action": "进入错误恢复阶段",
    }


def _select_worker_tools(worker: WorkerSpec, tool_map: dict[str, Any], mcp_tools: list[Any]) -> list[Any]:
    tools = [tool_map[name] for name in worker.tool_binding.tool_ids if name in tool_map]
    if worker.mcp_binding.server_names:
        tools.extend(mcp_tools)
    return tools


def _interrupt_policy_for_worker(worker: WorkerSpec, spec: AgentSpec) -> dict[str, bool] | None:
    tool_names = set(worker.tool_binding.tool_ids)
    approval_tools = [tool for tool in spec.interrupt_policy.approval_required_tools if tool in tool_names]
    if not approval_tools:
        return None
    return {tool: True for tool in approval_tools}


def _should_use_deep_agent_driver(
    worker: WorkerSpec,
    *,
    spec: AgentSpec,
    skill_sources: list[str],
) -> bool:
    return bool(skill_sources) or _interrupt_policy_for_worker(worker, spec) is not None


def _build_worker_runnable(
    worker: WorkerSpec,
    *,
    worker_model: Any,
    tools: list[Any],
    spec: AgentSpec,
    skill_sources: list[str],
) -> Any:
    if _should_use_deep_agent_driver(worker, spec=spec, skill_sources=skill_sources):
        return create_deep_agent(
            model=worker_model,
            tools=tools,
            system_prompt=worker.system_prompt,
            skills=skill_sources or None,
            backend=create_state_store_backend,
            middleware=[save_attachments_to_fs],
            interrupt_on=_interrupt_policy_for_worker(worker, spec),
            name=worker.key,
        )

    return create_agent(
        model=worker_model,
        tools=tools,
        system_prompt=worker.system_prompt,
        name=worker.key,
    )


async def build_reporter_supervisor_graph(
    *,
    model: BaseChatModel,
    context: ReporterContext,
    tool_map: dict[str, Any],
    mcp_tools: list[Any],
    skill_sources: list[str],
    checkpointer: Any = None,
    store: Any = None,
    per_worker_timeout: float = 90.0,
) -> CompiledStateGraph:
    spec = build_reporter_spec(context, resolved_skill_sources=skill_sources)
    worker_graphs: dict[str, Any] = {}

    for worker in spec.workers:
        worker_model = model if not worker.model or worker.model == context.model else load_chat_model(worker.model)
        worker_graphs[worker.key] = _build_worker_runnable(
            worker,
            worker_model=worker_model,
            tools=_select_worker_tools(worker, tool_map, mcp_tools),
            spec=spec,
            skill_sources=skill_sources,
        )

    def create_worker_wrapper(worker_key: str):
        worker_graph = worker_graphs[worker_key]

        async def run_worker(state: ReporterSupervisorState) -> dict[str, Any]:
            worker_input = dict(state)
            worker_input_messages = _build_worker_input_messages(worker_key, state)
            worker_input["messages"] = worker_input_messages
            try:
                result = await asyncio.wait_for(worker_graph.ainvoke(worker_input), timeout=per_worker_timeout)
            except GraphBubbleUp:
                raise
            except TimeoutError:
                error_message = AIMessage(
                    content=json.dumps(
                        _worker_error_output(
                            worker_key,
                            message=f"{worker_key} 执行超时（>{per_worker_timeout:.2f}s）",
                            error_type="timeout",
                        ),
                        ensure_ascii=False,
                    )
                )
                result = {"messages": [error_message]}
            except Exception as exc:
                error_message = AIMessage(
                    content=json.dumps(
                        _worker_error_output(
                            worker_key,
                            message=str(exc),
                            error_type="worker_error",
                        ),
                        ensure_ascii=False,
                    )
                )
                result = {"messages": [error_message]}

            messages = _normalize_input_messages(list(result.get("messages") or []))
            if len(messages) > len(worker_input_messages) and messages[: len(worker_input_messages)] == worker_input_messages:
                new_messages = messages[len(worker_input_messages) :]
            else:
                new_messages = messages
            last_message = new_messages[-1] if new_messages else AIMessage(
                content=json.dumps({"status": "ERROR", "summary": f"{worker_key} 未返回消息"}, ensure_ascii=False)
            )
            parsed = _enrich_stage_output(worker_key, _parse_stage_output(last_message), new_messages)
            stage_outputs = dict(state.get("stage_outputs") or {})
            stage_outputs[worker_key] = parsed

            update: dict[str, Any] = {
                "stage_outputs": stage_outputs,
                "active_worker": worker_key,
            }
            for key in ("attachments", "files", "todos"):
                if key in result:
                    update[key] = result[key]
            return update

        return run_worker

    def create_activation_wrapper(worker_key: str):
        def activate_worker(state: ReporterSupervisorState) -> dict[str, Any]:
            route_log = list(state.get("route_log") or [])
            if not route_log or route_log[-1] != worker_key:
                route_log.append(worker_key)
            return {
                "route_log": route_log,
                "active_worker": worker_key,
            }

        return activate_worker

    def route_from(worker_key: str):
        def _route(state: ReporterSupervisorState) -> str:
            payload = dict(state.get("stage_outputs") or {}).get(worker_key) or {}
            next_worker = _next_worker_for_stage(worker_key, payload, spec=spec)
            if next_worker == END:
                return _FINAL_RESPONSE_NODE
            return _activation_node_name(next_worker)

        return _route

    def finalize_response(state: ReporterSupervisorState) -> dict[str, Any]:
        return {
            "messages": [AIMessage(content=_format_reporter_final_message(state))],
        }

    builder = StateGraph(ReporterSupervisorState)
    for worker in spec.workers:
        builder.add_node(_activation_node_name(worker.key), create_activation_wrapper(worker.key))
        builder.add_node(worker.key, create_worker_wrapper(worker.key))
    builder.add_node(_FINAL_RESPONSE_NODE, finalize_response)

    entry_worker = spec.routing_policy.entry_worker
    builder.add_edge(START, _activation_node_name(entry_worker))
    for worker in spec.workers:
        builder.add_edge(_activation_node_name(worker.key), worker.key)
        builder.add_conditional_edges(worker.key, route_from(worker.key))
    builder.add_edge(_FINAL_RESPONSE_NODE, END)

    return builder.compile(checkpointer=checkpointer, store=store)
