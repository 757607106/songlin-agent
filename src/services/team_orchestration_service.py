"""Team orchestration service — validation and runtime context builder.

Provides:
- Team configuration validation (DAG checks, naming, overlap detection)
- Runtime context generation for DynamicAgent
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from graphlib import CycleError, TopologicalSorter
from itertools import combinations
from typing import Any

from src.utils import logger

TEAM_MODES = {"disabled", "supervisor", "deep_agents", "swarm"}
COMMUNICATION_MODES = {"sync", "async", "hybrid"}

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


class TeamOrchestrationService:
    """Team configuration validation and runtime context builder.

    Responsibilities:
    1. Validate team payloads (dependencies, naming, overlap, resources)
    2. Generate DynamicAgent-compatible runtime contexts
    """

    # ── Public API ─────────────────────────────────────────────

    def validate_team(
        self,
        team_payload: dict[str, Any],
        *,
        strict: bool = True,
        available_resources: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
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
        resource_validation = self._validate_resource_references(team, available_resources=available_resources)
        if resource_validation["errors"]:
            errors.extend(resource_validation["errors"])

        return {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "dependency_order": dependency_order,
            "execution_groups": execution_groups,
            "responsibility_overlap": overlap_pairs,
            "permission_matrix": permission_matrix,
            "communication_matrix": communication_matrix,
            "resource_validation": resource_validation,
            "normalized_team": team,
        }

    def build_runtime_context(
        self,
        team_payload: dict[str, Any],
        *,
        strict: bool = True,
        available_resources: dict[str, list[str]] | None = None,
        assembly_meta: dict[str, Any] | None = None,
        mode_recommendation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        validated = self.validate_team(
            team_payload,
            strict=strict,
            available_resources=available_resources,
        )
        if strict and not validated["valid"]:
            raise ValueError("; ".join(validated["errors"]))

        team = validated["normalized_team"]
        mode = team.get("multi_agent_mode") or "disabled"
        members = team.get("subagents") or []

        runtime_audit = {
            "built_at": self._utc_now_iso(),
            "builder_version": "team-orchestration-v3",
            "build_source": str((assembly_meta or {}).get("pipeline") or "direct_payload"),
            "assembly_status": str((assembly_meta or {}).get("status") or "unknown"),
            "attempts": list((assembly_meta or {}).get("attempts") or []),
            "mode_alignment_events": list((assembly_meta or {}).get("mode_alignment_events") or []),
            "selected_mode": mode,
            "recommended_mode": (mode_recommendation or {}).get("recommended_mode"),
            "is_selected_mode_recommended": bool((mode_recommendation or {}).get("is_selected_mode_recommended")),
            "blueprint_summary": dict((assembly_meta or {}).get("latest_blueprint") or {}),
        }

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
                    "skills": list(member.get("skills") or []),
                    "depends_on": list(member.get("depends_on") or []),
                    "allowed_targets": list(
                        member.get("allowed_targets") or validated["communication_matrix"].get(name, [])
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
            "tools": list(team.get("tools") or []),
            "knowledges": list(team.get("knowledges") or []),
            "mcps": list(team.get("mcps") or []),
            "skills": list(team.get("skills") or []),
            "subagents": runtime_subagents,
            "team_policy": {
                "dependency_order": validated["dependency_order"],
                "execution_groups": validated["execution_groups"],
                "permission_matrix": validated["permission_matrix"],
                "communication_matrix": validated["communication_matrix"],
                "warnings": validated["warnings"],
                "resource_validation": validated["resource_validation"],
                "mode_recommendation": mode_recommendation or {},
                "runtime_audit": runtime_audit,
            },
        }

    # ── Normalization ──────────────────────────────────────────

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
            "tools": self._normalize_list_field(context.get("tools")),
            "knowledges": self._normalize_list_field(context.get("knowledges")),
            "mcps": self._normalize_list_field(context.get("mcps")),
            "skills": self._normalize_list_field(context.get("skills")),
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
            "skills": self._normalize_list_field(data.get("skills")),
            "depends_on": self._normalize_list_field(data.get("depends_on")),
            "allowed_targets": self._normalize_list_field(data.get("allowed_targets")),
            "communication_mode": (
                data.get("communication_mode") if data.get("communication_mode") in COMMUNICATION_MODES else "hybrid"
            ),
            "max_retries": self._safe_int(data.get("max_retries"), 1),
            "plugin": str(data.get("plugin") or "default").strip() or "default",
        }

    # ── Dependency & DAG ───────────────────────────────────────

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

    # ── Overlap Detection ──────────────────────────────────────

    def _detect_responsibility_overlap(self, members: list[dict[str, Any]]) -> list[dict[str, Any]]:
        overlaps: list[dict[str, Any]] = []
        indexed: list[tuple[str, set[str]]] = []

        for member in members:
            name = member.get("name")
            if not name:
                continue
            text = f"{member.get('description', '')} {member.get('system_prompt', '')}".lower()
            tokens = {
                token for token in re.findall(r"[a-zA-Z0-9_\-\u4e00-\u9fff]{2,}", text) if token not in _STOP_WORDS
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

    # ── Permission & Communication ─────────────────────────────

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
                "skills": sorted(set(member.get("skills") or [])),
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

    # ── Resource Validation ────────────────────────────────────

    def _validate_resource_references(
        self,
        team: dict[str, Any],
        *,
        available_resources: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        provided_categories = set((available_resources or {}).keys()) if available_resources is not None else set()
        normalized_available = {
            "tools": sorted(set(self._normalize_list_field((available_resources or {}).get("tools")))),
            "knowledges": sorted(set(self._normalize_list_field((available_resources or {}).get("knowledges")))),
            "mcps": sorted(set(self._normalize_list_field((available_resources or {}).get("mcps")))),
            "skills": sorted(set(self._normalize_list_field((available_resources or {}).get("skills")))),
        }
        available_set = {key: set(values) for key, values in normalized_available.items()}

        invalid = {"tools": [], "knowledges": [], "mcps": [], "skills": []}
        refs = self._collect_resource_refs(team)
        for category in ("tools", "knowledges", "mcps", "skills"):
            if available_resources is None or category not in provided_categories:
                continue
            invalid_items = sorted({name for name in refs[category] if name not in available_set[category]})
            invalid[category] = invalid_items

        errors: list[str] = []
        if invalid["tools"]:
            errors.append(f"存在无效工具: {', '.join(invalid['tools'])}")
        if invalid["knowledges"]:
            errors.append(f"存在无权限或不存在的知识库: {', '.join(invalid['knowledges'])}")
        if invalid["mcps"]:
            errors.append(f"存在无效 MCP 服务器: {', '.join(invalid['mcps'])}")
        if invalid["skills"]:
            errors.append(f"存在无效 Skills: {', '.join(invalid['skills'])}")

        return {
            "valid": not errors,
            "errors": errors,
            "invalid": invalid,
            "available": normalized_available,
        }

    def _collect_resource_refs(self, team: dict[str, Any]) -> dict[str, list[str]]:
        refs = {
            "tools": list(team.get("tools") or []),
            "knowledges": list(team.get("knowledges") or []),
            "mcps": list(team.get("mcps") or []),
            "skills": list(team.get("skills") or []),
        }
        for member in team.get("subagents") or []:
            if not isinstance(member, dict):
                continue
            refs["tools"].extend(member.get("tools") or [])
            refs["knowledges"].extend(member.get("knowledges") or [])
            refs["mcps"].extend(member.get("mcps") or [])
            refs["skills"].extend(member.get("skills") or [])

        return {
            "tools": sorted(set(self._normalize_list_field(refs["tools"]))),
            "knowledges": sorted(set(self._normalize_list_field(refs["knowledges"]))),
            "mcps": sorted(set(self._normalize_list_field(refs["mcps"]))),
            "skills": sorted(set(self._normalize_list_field(refs["skills"]))),
        }

    # ── Prompt Builders ────────────────────────────────────────

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
            groups = "\n".join(f"- 阶段 {idx + 1}: {', '.join(group)}" for idx, group in enumerate(execution_groups))
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
            f"{'\n'.join(description_lines) or '- 无可用子Agent'}\n\n"
            "[Dependencies]\n"
            f"{'\n'.join(dependency_lines) or '- 无'}\n"
            f"- 拓扑顺序参考: {order_text}\n\n"
            "[Communication Matrix]\n"
            f"{'\n'.join(communication_lines) or '- 无'}\n\n"
            "[Routing Rules]\n"
            "1. 任何 Agent 的 depends_on 未满足时，不得调度该 Agent。\n"
            "2. 不得连续路由同一 Agent 超过其 max_retries 上限。\n"
            "3. 发现循环调用风险时，立即 FINISH 并输出阻塞原因。\n"
            "4. 每次只能返回一个 next（某个 Agent 名称或 FINISH）。"
        )

    # ── Utilities ──────────────────────────────────────────────

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
            return parsed if parsed >= 0 else default
        except Exception:
            return default

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
            "skills": sorted(set(member.get("skills") or [])),
        }
        return json.dumps(material, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(UTC).isoformat()


team_orchestration_service = TeamOrchestrationService()
