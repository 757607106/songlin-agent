from __future__ import annotations

import json
import re
import time
from graphlib import CycleError, TopologicalSorter
from itertools import combinations
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src import config as app_config
from src.agents.common.models import load_chat_model
from src.services.mcp_service import get_enabled_mcp_tools
from src.utils import logger

TEAM_MODES = {"disabled", "supervisor", "deep_agents"}
COMMUNICATION_MODES = {"sync", "async", "hybrid"}

_ROLE_ASSIGN_RE = re.compile(
    r"(?P<name>[A-Za-z0-9_\-\u4e00-\u9fff]+)\.(?P<field>description|system_prompt|model|tools|knowledges|mcps|depends_on|allowed_targets|max_retries|communication_mode|plugin)\s*[:=：]\s*(?P<value>.+)"
)
_AGENT_LINE_RE = re.compile(
    r"^[\-\*\d\.)\s]*(?P<name>[A-Za-z0-9_\-\u4e00-\u9fff]+)\s*[:：]\s*(?P<desc>.+)$"
)

_STOP_WORDS = {
    "agent",
    "agents",
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "负责",
    "进行",
    "处理",
    "以及",
    "一个",
    "智能体",
    "任务",
    "团队",
    "协作",
    "workflow",
    "mode",
    "system",
    "prompt",
}

_TEAM_INTENT_KEYWORDS = {
    "团队",
    "team",
    "multi-agent",
    "multi agent",
    "subagent",
    "deepagents",
    "deep_agents",
    "agent 团队",
    "agent团队",
    "智能体团队",
    "多智能体",
    "协作团队",
}

_DEV_TEAM_KEYWORDS = {
    "开发团队",
    "研发团队",
    "需求开发",
    "软件开发",
    "project",
    "产品开发",
    "deepagents",
    "deep_agents",
}

_DEEP_AGENTS_CAPABILITY_HINT = (
    "DeepAgents 默认具备以下核心机制："
    "1) Planning：write_todos；"
    "2) Subagents：task 委派；"
    "3) Filesystem：ls/read_file/write_file/edit_file。"
)


class TeamOrchestrationService:
    """OpenClaw 风格团队编排服务。

    目标：
    1. 支持对话式团队草稿构建
    2. 统一职责边界校验（依赖、循环、权限、通信）
    3. 生成 DynamicAgent 可直接使用的运行时上下文
    """

    def wizard_step(self, message: str, draft: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = self._merge_draft(draft or {}, self._parse_user_message(message))
        normalized = self._normalize_team_payload(merged)
        return self._build_wizard_result(normalized)

    async def wizard_step_with_ai(
        self,
        message: str,
        draft: dict[str, Any] | None = None,
        *,
        auto_complete: bool = True,
    ) -> dict[str, Any]:
        merged = self._merge_draft(draft or {}, self._parse_user_message(message))
        normalized = self._normalize_team_payload(merged)

        if auto_complete and self._should_auto_complete(message, normalized):
            template_patch = self._build_builtin_team_patch(message, normalized)
            if template_patch:
                merged = self._merge_draft(merged, template_patch)
                normalized = self._normalize_team_payload(merged)

        if auto_complete and self._should_auto_complete(message, normalized):
            ai_patch = await self._generate_team_patch_with_llm(message, normalized)
            if ai_patch:
                merged = self._merge_draft(merged, ai_patch)
                normalized = self._normalize_team_payload(merged)

        return self._build_wizard_result(normalized)

    def _build_wizard_result(self, normalized: dict[str, Any]) -> dict[str, Any]:
        check = self.validate_team(normalized, strict=False)
        questions = self._build_missing_questions(normalized)

        if questions:
            assistant_message = questions[0]
            is_complete = False
        elif check["errors"]:
            assistant_message = "团队草稿已接收，但还需要修正：" + "；".join(check["errors"][:3])
            is_complete = False
        else:
            agents = normalized.get("subagents", [])
            assistant_message = (
                f"团队定义已完整。目标：{normalized.get('team_goal') or '未填写'}；"
                f"模式：{normalized.get('multi_agent_mode')}; 子Agent数量：{len(agents)}。"
                "请确认后执行创建。"
            )
            is_complete = True

        return {
            "draft": normalized,
            "is_complete": is_complete,
            "assistant_message": assistant_message,
            "questions": questions,
            "validation": check,
        }

    def _should_auto_complete(self, message: str, team: dict[str, Any]) -> bool:
        text = (message or "").strip().lower()
        if not text:
            return False

        if not self._looks_like_team_intent(text):
            return False

        members = team.get("subagents") or []
        if not members:
            return True

        if not team.get("team_goal") or not team.get("task_scope"):
            return True

        for member in members:
            if not member.get("description") or not member.get("system_prompt"):
                return True

        return False

    @staticmethod
    def _looks_like_team_intent(text: str) -> bool:
        normalized = text.lower()
        return any(key in normalized for key in _TEAM_INTENT_KEYWORDS)

    def _build_builtin_team_patch(self, message: str, current_team: dict[str, Any]) -> dict[str, Any]:
        text = (message or "").strip().lower()
        if not any(key in text for key in _DEV_TEAM_KEYWORDS):
            return {}

        goal = current_team.get("team_goal") or "完成一个可交付的软件需求开发项目"
        scope = current_team.get("task_scope") or (
            "覆盖需求澄清、任务拆解、前后端实现、测试验收、文档交付；"
            "不包含生产部署与运维值班。"
        )
        base_prompt = (
            "你是开发团队总调度 Agent。先调用 write_todos 做规划，再通过 task 将任务委派给子 Agent，"
            "要求每个阶段的产物写入文件系统并可追踪。"
        )
        return {
            "team_goal": goal,
            "task_scope": scope,
            "multi_agent_mode": current_team.get("multi_agent_mode")
            if current_team.get("multi_agent_mode") in TEAM_MODES and current_team.get("multi_agent_mode") != "disabled"
            else "deep_agents",
            "communication_protocol": current_team.get("communication_protocol") or "hybrid",
            "max_parallel_tasks": max(2, self._safe_int(current_team.get("max_parallel_tasks"), 4)),
            "allow_cross_agent_comm": False,
            "system_prompt": current_team.get("system_prompt") or base_prompt,
            "subagents": [
                {
                    "name": "product_manager",
                    "description": "澄清业务目标与验收标准，输出 PRD 与范围边界。",
                    "system_prompt": (
                        "你是产品经理子 Agent。仅负责需求澄清与验收标准定义。"
                        "输出 `prd.md` 与 `acceptance_criteria.md`。"
                    ),
                    "depends_on": [],
                    "communication_mode": "sync",
                },
                {
                    "name": "project_manager",
                    "description": "基于 PRD 做任务拆解、排期与依赖编排。",
                    "system_prompt": (
                        "你是项目经理子 Agent。先调用 write_todos 拆解任务，再形成执行计划。"
                        "输出 `delivery_plan.md` 与 `task_breakdown.md`。"
                    ),
                    "depends_on": ["product_manager"],
                    "communication_mode": "sync",
                },
                {
                    "name": "frontend_engineer",
                    "description": "实现前端页面、状态管理与交互逻辑。",
                    "system_prompt": (
                        "你是前端工程师子 Agent。仅负责前端实现与自测说明。"
                        "输出 `frontend_changes.md`，并将关键实现写入文件系统。"
                    ),
                    "depends_on": ["project_manager"],
                    "communication_mode": "hybrid",
                },
                {
                    "name": "backend_engineer",
                    "description": "实现后端 API、数据模型与服务逻辑。",
                    "system_prompt": (
                        "你是后端工程师子 Agent。仅负责后端实现与接口契约。"
                        "输出 `backend_changes.md` 与 `api_contract.md`。"
                    ),
                    "depends_on": ["project_manager"],
                    "communication_mode": "hybrid",
                },
                {
                    "name": "qa_engineer",
                    "description": "设计并执行测试，输出缺陷与回归结论。",
                    "system_prompt": (
                        "你是测试工程师子 Agent。仅负责测试设计、执行和结果汇总。"
                        "输出 `test_report.md` 与 `defect_list.md`。"
                    ),
                    "depends_on": ["frontend_engineer", "backend_engineer"],
                    "communication_mode": "sync",
                },
                {
                    "name": "technical_writer",
                    "description": "沉淀用户文档与交付说明。",
                    "system_prompt": (
                        "你是文档工程师子 Agent。仅负责交付文档编写。"
                        "输出 `release_notes.md` 与 `user_guide.md`。"
                    ),
                    "depends_on": ["qa_engineer"],
                    "communication_mode": "async",
                },
            ],
        }

    async def _generate_team_patch_with_llm(self, message: str, current_team: dict[str, Any]) -> dict[str, Any]:
        try:
            model = load_chat_model(app_config.default_model, temperature=0)
            response = await model.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "你是多 Agent 团队架构师。请把用户需求转换成 DynamicAgent 团队 JSON。"
                            "必须保证职责边界清晰、依赖有向无环、可直接用于 DeepAgents 或 Supervisor。"
                            f"{_DEEP_AGENTS_CAPABILITY_HINT}"
                            "输出 JSON 字段：team_goal,task_scope,multi_agent_mode,communication_protocol,"
                            "max_parallel_tasks,allow_cross_agent_comm,system_prompt,supervisor_system_prompt,subagents。"
                            "subagents 每项必须包含 name,description,system_prompt,depends_on,communication_mode。"
                            "只输出 JSON，不要额外解释。"
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"用户输入:\n{message}\n\n"
                            f"当前草稿:\n{json.dumps(current_team, ensure_ascii=False)}\n\n"
                            "如果用户描述是研发或需求开发团队，优先给出 6 角色："
                            "product_manager,project_manager,frontend_engineer,backend_engineer,qa_engineer,technical_writer。"
                        )
                    ),
                ]
            )
            parsed = self._parse_model_json(getattr(response, "content", response))
            if not isinstance(parsed, dict):
                return {}
            normalized = self._normalize_team_payload(parsed)
            if normalized.get("subagents"):
                return normalized
            return {}
        except Exception as exc:
            logger.warning(f"AI auto-complete team failed: {exc}")
            return {}

    def _parse_model_json(self, content: Any) -> dict[str, Any] | None:
        if isinstance(content, dict):
            return content
        if isinstance(content, str):
            return self._extract_json_payload(content)
        if isinstance(content, list):
            texts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    texts.append(block)
                elif isinstance(block, dict):
                    text = block.get("text") or block.get("content")
                    if text:
                        texts.append(str(text))
            if texts:
                return self._extract_json_payload("\n".join(texts))
        return None

    def validate_team(self, team_payload: dict[str, Any], *, strict: bool = True) -> dict[str, Any]:
        team = self._normalize_team_payload(team_payload)
        logger.debug(
            "Validating team payload: mode={}, subagents={}",
            team.get("multi_agent_mode"),
            len(team.get("subagents") or []),
        )
        errors: list[str] = []
        warnings: list[str] = []

        mode = team.get("multi_agent_mode") or "disabled"
        if mode not in TEAM_MODES:
            errors.append(f"不支持的 multi_agent_mode: {mode}")

        members = team.get("subagents") or []

        if mode != "disabled" and not members:
            errors.append("多Agent模式至少需要 1 个子Agent")

        name_list = [m.get("name", "").strip() for m in members if isinstance(m, dict)]
        if len(name_list) != len(set(name_list)):
            errors.append("子Agent名称必须唯一")

        for idx, member in enumerate(members):
            if not isinstance(member, dict):
                errors.append(f"第 {idx + 1} 个子Agent配置格式错误")
                continue
            if not member.get("name"):
                errors.append(f"第 {idx + 1} 个子Agent缺少 name")
            if strict and not member.get("description"):
                errors.append(f"子Agent `{member.get('name') or idx + 1}` 缺少 description")
            if strict and not member.get("system_prompt"):
                errors.append(f"子Agent `{member.get('name') or idx + 1}` 缺少 system_prompt")

            comm_mode = member.get("communication_mode", "hybrid")
            if comm_mode not in COMMUNICATION_MODES:
                errors.append(f"子Agent `{member.get('name')}` communication_mode 无效: {comm_mode}")

            max_retries = member.get("max_retries", 1)
            if not isinstance(max_retries, int) or max_retries < 0:
                errors.append(f"子Agent `{member.get('name')}` max_retries 必须为非负整数")

        dependency_errors, dependency_order, execution_groups = self._validate_dependencies(team)
        errors.extend(dependency_errors)

        overlap_pairs = self._detect_responsibility_overlap(members)
        for pair in overlap_pairs:
            score = pair["score"]
            msg = f"职责可能重叠: {pair['a']} <-> {pair['b']} (score={score:.2f})"
            if score >= 0.75 and strict:
                errors.append(msg)
            else:
                warnings.append(msg)

        permission_matrix = self._build_permission_matrix(members)
        communication_matrix = self._build_communication_matrix(team)

        return {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "dependency_order": dependency_order,
            "execution_groups": execution_groups,
            "responsibility_overlap": overlap_pairs,
            "permission_matrix": permission_matrix,
            "communication_matrix": communication_matrix,
            "normalized_team": team,
        }

    def build_runtime_context(self, team_payload: dict[str, Any], *, strict: bool = True) -> dict[str, Any]:
        validated = self.validate_team(team_payload, strict=strict)
        if strict and not validated["valid"]:
            raise ValueError("; ".join(validated["errors"]))

        team = validated["normalized_team"]
        mode = team.get("multi_agent_mode") or "disabled"
        members = team.get("subagents") or []

        supervisor_prompt = team.get("supervisor_system_prompt") or self._build_supervisor_prompt(
            team,
            dependency_order=validated["dependency_order"],
            communication_matrix=validated["communication_matrix"],
        )

        system_prompt = self._build_team_system_prompt(
            team,
            execution_groups=validated["execution_groups"],
        )

        runtime_subagents = []
        for member in members:
            name = member.get("name", "").strip()
            runtime_subagents.append(
                {
                    "name": name,
                    "description": member.get("description", ""),
                    "system_prompt": member.get("system_prompt", ""),
                    "tools": list(member.get("tools") or []),
                    "model": member.get("model"),
                    "knowledges": list(member.get("knowledges") or []),
                    "mcps": list(member.get("mcps") or []),
                    "depends_on": list(member.get("depends_on") or []),
                    "allowed_targets": list(
                        member.get("allowed_targets")
                        or validated["communication_matrix"].get(name, [])
                    ),
                    "communication_mode": member.get("communication_mode") or "hybrid",
                    "max_retries": int(member.get("max_retries", 1) or 1),
                    "plugin": member.get("plugin") or "default",
                    "responsibility_score": self._member_scope_hash(member),
                }
            )

        return {
            "team_goal": team.get("team_goal", ""),
            "task_scope": team.get("task_scope", ""),
            "multi_agent_mode": mode,
            "communication_protocol": team.get("communication_protocol", "hybrid"),
            "max_parallel_tasks": int(team.get("max_parallel_tasks", 4) or 4),
            "allow_cross_agent_comm": bool(team.get("allow_cross_agent_comm", False)),
            "system_prompt": system_prompt,
            "supervisor_system_prompt": supervisor_prompt,
            "subagents": runtime_subagents,
            "team_policy": {
                "dependency_order": validated["dependency_order"],
                "execution_groups": validated["execution_groups"],
                "permission_matrix": validated["permission_matrix"],
                "communication_matrix": validated["communication_matrix"],
                "warnings": validated["warnings"],
            },
        }

    async def query_langchain_docs(
        self,
        query: str,
        *,
        server_name: str = "langchain-docs",
    ) -> dict[str, Any]:
        tools = await get_enabled_mcp_tools(server_name)
        if not tools:
            raise ValueError(f"MCP 服务器 `{server_name}` 未配置或没有可用工具")

        tool = self._pick_docs_tool(tools)
        logger.info(f"Querying LangChain docs via MCP: server={server_name}, tool={getattr(tool, 'name', 'unknown')}")
        args = self._infer_tool_args(tool, query)
        result = await self._invoke_tool(tool, args)

        return {
            "server": server_name,
            "tool": getattr(tool, "name", "unknown"),
            "query": query,
            "result": result,
        }

    def benchmark_modes(self, team_payload: dict[str, Any], *, iterations: int = 8) -> dict[str, Any]:
        iterations = max(1, min(iterations, 50))
        team = self._normalize_team_payload(team_payload)
        check = self.validate_team(team, strict=False)

        samples: list[dict[str, float]] = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            check = self.validate_team(team, strict=False)
            t1 = time.perf_counter()
            self.build_runtime_context(team, strict=False)
            t2 = time.perf_counter()
            samples.append(
                {
                    "validate_ms": (t1 - t0) * 1000,
                    "build_context_ms": (t2 - t1) * 1000,
                }
            )

        members_count = len(team.get("subagents") or [])
        execution_groups = check.get("execution_groups") or []
        group_count = max(1, len(execution_groups))

        # 估算执行效率（在无真实模型调用时提供可比口径）
        baseline_disabled = max(1, members_count) * 100.0
        estimated_supervisor = members_count * 110.0
        estimated_deep = group_count * 85.0

        return {
            "valid": check["valid"],
            "errors": check["errors"],
            "warnings": check["warnings"],
            "iterations": iterations,
            "timings": {
                "avg_validate_ms": round(sum(s["validate_ms"] for s in samples) / iterations, 3),
                "avg_build_context_ms": round(sum(s["build_context_ms"] for s in samples) / iterations, 3),
                "max_validate_ms": round(max(s["validate_ms"] for s in samples), 3),
                "max_build_context_ms": round(max(s["build_context_ms"] for s in samples), 3),
            },
            "mode_comparison": {
                "disabled_estimated_cost": round(baseline_disabled, 2),
                "supervisor_estimated_cost": round(estimated_supervisor, 2),
                "deep_agents_estimated_cost": round(estimated_deep, 2),
                "deep_vs_disabled_speedup": round(baseline_disabled / max(estimated_deep, 1.0), 2),
                "deep_vs_supervisor_speedup": round(estimated_supervisor / max(estimated_deep, 1.0), 2),
            },
            "execution_groups": check.get("execution_groups") or [],
        }

    def _parse_user_message(self, message: str) -> dict[str, Any]:
        payload = self._extract_json_payload(message)
        if payload is not None:
            return payload

        result: dict[str, Any] = {}
        text = message.strip()
        if not text:
            return result

        goal = re.search(r"(?:团队目标|目标|goal)\s*[:：]\s*(.+)", text, flags=re.IGNORECASE)
        if goal:
            result["team_goal"] = goal.group(1).strip()

        scope = re.search(r"(?:任务范围|范围|scope)\s*[:：]\s*(.+)", text, flags=re.IGNORECASE)
        if scope:
            result["task_scope"] = scope.group(1).strip()

        if "supervisor" in text.lower() or "子图" in text:
            result["multi_agent_mode"] = "supervisor"
        elif "deep_agents" in text.lower() or "并行" in text:
            result["multi_agent_mode"] = "deep_agents"
        elif "disabled" in text.lower() or "单智能体" in text:
            result["multi_agent_mode"] = "disabled"

        draft_members: dict[str, dict[str, Any]] = {}
        for line in text.splitlines():
            assign = _ROLE_ASSIGN_RE.search(line.strip())
            if assign:
                name = assign.group("name").strip()
                field = assign.group("field").strip()
                value = assign.group("value").strip()
                member = draft_members.setdefault(name, {"name": name})
                if field in {"tools", "knowledges", "mcps", "depends_on", "allowed_targets"}:
                    member[field] = self._split_list(value)
                elif field == "max_retries":
                    member[field] = self._safe_int(value, 1)
                else:
                    member[field] = value
                continue

            agent_line = _AGENT_LINE_RE.search(line.strip())
            if agent_line:
                name = agent_line.group("name").strip()
                if name.lower() in {"goal", "scope", "mode", "system_prompt"} or name in {
                    "目标",
                    "范围",
                    "模式",
                }:
                    continue
                desc = agent_line.group("desc").strip()
                member = draft_members.setdefault(name, {"name": name})
                member.setdefault("description", desc)

        if draft_members:
            result["subagents"] = list(draft_members.values())

        return result

    def _extract_json_payload(self, message: str) -> dict[str, Any] | None:
        text = (message or "").strip()
        if not text:
            return None

        fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]+?\})\s*```", text, flags=re.IGNORECASE)
        candidate = fence_match.group(1) if fence_match else text

        if "{" not in candidate or "}" not in candidate:
            return None

        try:
            return json.loads(candidate)
        except Exception:
            try:
                from json_repair import repair_json

                repaired = repair_json(candidate)
                return json.loads(repaired)
            except Exception:
                return None

    def _merge_draft(self, base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in patch.items():
            if key != "subagents":
                merged[key] = value
                continue

            base_members = {
                m.get("name"): dict(m)
                for m in merged.get("subagents", [])
                if isinstance(m, dict) and m.get("name")
            }
            for member in value or []:
                if not isinstance(member, dict):
                    continue
                name = member.get("name")
                if not name:
                    continue
                existing = base_members.get(name, {"name": name})
                existing.update(member)
                base_members[name] = existing
            merged["subagents"] = list(base_members.values())

        return merged

    def _normalize_team_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = dict(payload or {})
        context = raw.get("context") if isinstance(raw.get("context"), dict) else raw

        team_goal = context.get("team_goal") or context.get("goal") or ""
        task_scope = context.get("task_scope") or context.get("scope") or ""
        mode = context.get("multi_agent_mode") or context.get("mode") or "disabled"
        mode = mode if mode in TEAM_MODES else "disabled"

        communication_protocol = context.get("communication_protocol") or "hybrid"
        if communication_protocol not in COMMUNICATION_MODES:
            communication_protocol = "hybrid"

        members_raw = context.get("subagents") or context.get("agents") or []
        members = [self._normalize_member_payload(m) for m in members_raw if isinstance(m, dict)]

        return {
            "team_goal": str(team_goal or "").strip(),
            "task_scope": str(task_scope or "").strip(),
            "multi_agent_mode": mode,
            "system_prompt": str(context.get("system_prompt") or "").strip(),
            "supervisor_system_prompt": str(context.get("supervisor_system_prompt") or "").strip(),
            "communication_protocol": communication_protocol,
            "max_parallel_tasks": self._safe_int(context.get("max_parallel_tasks"), 4),
            "allow_cross_agent_comm": bool(context.get("allow_cross_agent_comm", False)),
            "subagents": members,
        }

    def _normalize_member_payload(self, member: dict[str, Any]) -> dict[str, Any]:
        data = dict(member)
        return {
            "name": str(data.get("name") or "").strip(),
            "description": str(data.get("description") or data.get("name.description") or "").strip(),
            "system_prompt": str(data.get("system_prompt") or "").strip(),
            "tools": self._normalize_list_field(data.get("tools")),
            "model": str(data.get("model") or "").strip() or None,
            "knowledges": self._normalize_list_field(data.get("knowledges")),
            "mcps": self._normalize_list_field(data.get("mcps") or data.get("mcp")),
            "depends_on": self._normalize_list_field(data.get("depends_on")),
            "allowed_targets": self._normalize_list_field(data.get("allowed_targets")),
            "communication_mode": (
                data.get("communication_mode")
                if data.get("communication_mode") in COMMUNICATION_MODES
                else "hybrid"
            ),
            "max_retries": self._safe_int(data.get("max_retries"), 1),
            "plugin": str(data.get("plugin") or "default").strip() or "default",
        }

    def _validate_dependencies(self, team: dict[str, Any]) -> tuple[list[str], list[str], list[list[str]]]:
        members = team.get("subagents") or []
        names = {m.get("name") for m in members if m.get("name")}
        dependency_map: dict[str, set[str]] = {}
        errors: list[str] = []

        for member in members:
            name = member.get("name")
            if not name:
                continue
            deps = {d for d in member.get("depends_on", []) if d}
            unknown = sorted(d for d in deps if d not in names)
            if unknown:
                errors.append(f"子Agent `{name}` 的依赖不存在: {', '.join(unknown)}")
            dependency_map[name] = {d for d in deps if d in names}

        if not dependency_map:
            return errors, [], []

        try:
            order = list(TopologicalSorter(dependency_map).static_order())
        except CycleError as exc:
            cycle_nodes = ", ".join(str(v) for v in exc.args[1] if v)
            errors.append(f"检测到循环依赖: {cycle_nodes}")
            return errors, [], []

        groups = self._build_execution_groups(
            dependency_map,
            max_parallel=max(1, self._safe_int(team.get("max_parallel_tasks"), 4)),
        )
        return errors, order, groups

    def _build_execution_groups(self, dependency_map: dict[str, set[str]], *, max_parallel: int) -> list[list[str]]:
        pending = {name: set(deps) for name, deps in dependency_map.items()}
        groups: list[list[str]] = []

        while pending:
            ready = sorted([name for name, deps in pending.items() if not deps])
            if not ready:
                break

            emitted: set[str] = set()
            while ready:
                chunk = ready[:max_parallel]
                ready = ready[max_parallel:]
                groups.append(chunk)
                emitted.update(chunk)

            completed = emitted
            for name in list(pending.keys()):
                if name in completed:
                    del pending[name]
                    continue
                pending[name].difference_update(completed)

        return groups

    def _detect_responsibility_overlap(self, members: list[dict[str, Any]]) -> list[dict[str, Any]]:
        overlaps: list[dict[str, Any]] = []
        indexed: list[tuple[str, set[str]]] = []

        for member in members:
            name = member.get("name")
            if not name:
                continue
            text = f"{member.get('description', '')} {member.get('system_prompt', '')}".lower()
            tokens = {
                token
                for token in re.findall(r"[a-zA-Z0-9_\-\u4e00-\u9fff]{2,}", text)
                if token not in _STOP_WORDS
            }
            indexed.append((name, tokens))

        for (a_name, a_tokens), (b_name, b_tokens) in combinations(indexed, 2):
            union = a_tokens | b_tokens
            if not union:
                continue
            score = len(a_tokens & b_tokens) / len(union)
            if score >= 0.55:
                overlaps.append({"a": a_name, "b": b_name, "score": round(score, 4)})

        return overlaps

    def _build_permission_matrix(self, members: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
        matrix: dict[str, dict[str, list[str]]] = {}
        for member in members:
            name = member.get("name")
            if not name:
                continue
            matrix[name] = {
                "tools": sorted(set(member.get("tools") or [])),
                "knowledges": sorted(set(member.get("knowledges") or [])),
                "mcps": sorted(set(member.get("mcps") or [])),
            }
        return matrix

    def _build_communication_matrix(self, team: dict[str, Any]) -> dict[str, list[str]]:
        members = team.get("subagents") or []
        names = [m.get("name") for m in members if m.get("name")]
        reverse_deps: dict[str, list[str]] = {name: [] for name in names}

        for member in members:
            cur = member.get("name")
            if not cur:
                continue
            for dep in member.get("depends_on") or []:
                if dep in reverse_deps:
                    reverse_deps[dep].append(cur)

        allow_cross = bool(team.get("allow_cross_agent_comm", False))
        matrix: dict[str, list[str]] = {}
        for member in members:
            name = member.get("name")
            if not name:
                continue
            if allow_cross:
                matrix[name] = [n for n in names if n != name]
                continue

            explicit = [n for n in member.get("allowed_targets") or [] if n in names and n != name]
            if explicit:
                matrix[name] = sorted(set(explicit))
                continue

            inferred = set(member.get("depends_on") or []) | set(reverse_deps.get(name, []))
            matrix[name] = sorted(n for n in inferred if n in names and n != name)

        return matrix

    def _build_team_system_prompt(self, team: dict[str, Any], *, execution_groups: list[list[str]]) -> str:
        base = (team.get("system_prompt") or "You are a helpful assistant.").strip()
        goal = team.get("team_goal")
        scope = team.get("task_scope")
        protocol = team.get("communication_protocol", "hybrid")

        instructions = [base]
        if goal:
            instructions.append(f"\n[Team Goal]\n{goal}")
        if scope:
            instructions.append(f"\n[Task Scope]\n{scope}")

        instructions.append(
            "\n[OpenClaw Collaboration Contract]\n"
            "1. 先做任务分解，再做执行。\n"
            "2. 每次调用子Agent前先验证依赖是否满足。\n"
            "3. 任何输出必须附带可追踪的来源或中间结论。\n"
            "4. 子Agent不得越权访问未授权工具/知识库/MCP。\n"
            f"5. 通信协议：{protocol}。"
        )

        if execution_groups:
            groups = "\n".join(
                f"- 阶段 {idx + 1}: {', '.join(group)}" for idx, group in enumerate(execution_groups)
            )
            instructions.append(f"\n[Execution Groups]\n{groups}")

        if team.get("multi_agent_mode") == "deep_agents":
            instructions.append(
                "\n[Deep Agents 并行策略]\n"
                "- 对同一执行阶段内无依赖冲突的子任务并行下发。\n"
                "- 若并行结果冲突：优先选择依赖链更长的结果；若仍冲突，选择引用证据更完整的结果。\n"
                "- 聚合输出必须明确说明冲突点和最终裁决依据。\n"
                "- 先调用 write_todos 完成规划，再使用 task 做子 Agent 委派。\n"
                "- 每个关键中间结果写入文件系统（write_file/edit_file），最终结论引用对应文件。"
            )

        return "\n".join(instructions).strip()

    def _build_supervisor_prompt(
        self,
        team: dict[str, Any],
        *,
        dependency_order: list[str],
        communication_matrix: dict[str, list[str]],
    ) -> str:
        members = team.get("subagents") or []
        description_lines = []
        dependency_lines = []
        communication_lines = []

        for member in members:
            name = member.get("name")
            if not name:
                continue
            desc = member.get("description") or "无描述"
            depends = ", ".join(member.get("depends_on") or []) or "无"
            description_lines.append(f"- {name}: {desc}")
            dependency_lines.append(f"- {name} depends_on: {depends}")
            allowed = ", ".join(communication_matrix.get(name, [])) or "无"
            communication_lines.append(f"- {name} -> {allowed}")

        order_text = " -> ".join(dependency_order) if dependency_order else "未指定"

        return (
            "你是团队调度 Supervisor。你必须严格遵循职责边界、依赖顺序和通信协议。\n\n"
            "[Agents]\n"
            f"{"\n".join(description_lines) or '- 无可用子Agent'}\n\n"
            "[Dependencies]\n"
            f"{"\n".join(dependency_lines) or '- 无'}\n"
            f"- 拓扑顺序参考: {order_text}\n\n"
            "[Communication Matrix]\n"
            f"{"\n".join(communication_lines) or '- 无'}\n\n"
            "[Routing Rules]\n"
            "1. 任何 Agent 的 depends_on 未满足时，不得调度该 Agent。\n"
            "2. 不得连续路由同一 Agent 超过其 max_retries 上限。\n"
            "3. 发现循环调用风险时，立即 FINISH 并输出阻塞原因。\n"
            "4. 每次只能返回一个 next（某个 Agent 名称或 FINISH）。"
        )

    def _build_missing_questions(self, team: dict[str, Any]) -> list[str]:
        questions: list[str] = []
        if not team.get("team_goal"):
            questions.append("请先告诉我团队整体目标（team_goal）。")
        if not team.get("task_scope"):
            questions.append("请补充任务范围（task_scope），说明哪些任务在本团队职责内。")

        members = team.get("subagents") or []
        if team.get("multi_agent_mode") != "disabled" and not members:
            questions.append("请至少定义一个子Agent（name、description、system_prompt）。")
            return questions

        for member in members:
            name = member.get("name") or "未命名Agent"
            if not member.get("description"):
                questions.append(f"请补充 `{name}` 的职责描述（description）。")
                break
            if not member.get("system_prompt"):
                questions.append(f"请补充 `{name}` 的系统提示词（system_prompt）。")
                break

        return questions

    def _pick_docs_tool(self, tools: list[Any]) -> Any:
        for tool in tools:
            name = (getattr(tool, "name", "") or "").lower()
            if any(key in name for key in ("search", "query", "doc", "retrieve")):
                return tool
        return tools[0]

    def _infer_tool_args(self, tool: Any, query: str) -> Any:
        args_schema = getattr(tool, "args_schema", None)
        if args_schema is None:
            return {"query": query}

        try:
            schema = args_schema if isinstance(args_schema, dict) else args_schema.schema()
        except Exception:
            return {"query": query}

        props = (schema or {}).get("properties") or {}
        if not props:
            return {"query": query}

        for candidate in ("query", "question", "input", "text"):
            if candidate in props:
                return {candidate: query}

        first_key = next(iter(props.keys()))
        return {first_key: query}

    async def _invoke_tool(self, tool: Any, args: Any) -> Any:
        if hasattr(tool, "ainvoke"):
            return await tool.ainvoke(args)
        if hasattr(tool, "arun"):
            return await tool.arun(args)
        if hasattr(tool, "invoke"):
            return tool.invoke(args)
        if hasattr(tool, "run"):
            return tool.run(args)
        raise ValueError(f"工具 `{getattr(tool, 'name', 'unknown')}` 不支持调用")

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
            return parsed if parsed >= 0 else default
        except Exception:
            return default

    @staticmethod
    def _split_list(value: str) -> list[str]:
        raw = re.split(r"[,，;；|]", value)
        return [v.strip() for v in raw if v.strip()]

    @staticmethod
    def _normalize_list_field(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [v.strip() for v in re.split(r"[,，;；|]", value) if v.strip()]
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return []

    @staticmethod
    def _member_scope_hash(member: dict[str, Any]) -> str:
        material = {
            "tools": sorted(set(member.get("tools") or [])),
            "knowledges": sorted(set(member.get("knowledges") or [])),
            "mcps": sorted(set(member.get("mcps") or [])),
        }
        return json.dumps(material, ensure_ascii=False, sort_keys=True)


team_orchestration_service = TeamOrchestrationService()


__all__ = ["TeamOrchestrationService", "team_orchestration_service"]
