from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime
from graphlib import CycleError, TopologicalSorter
from itertools import combinations
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src import config as app_config
from src.agents.common.models import load_chat_model
from src.services.mcp_service import get_enabled_mcp_tools
from src.utils import logger

TEAM_MODES = {"disabled", "supervisor", "deep_agents", "swarm"}
COMMUNICATION_MODES = {"sync", "async", "hybrid"}

_ROLE_ASSIGN_RE = re.compile(
    r"(?P<name>[A-Za-z0-9_\-\u4e00-\u9fff]+)\.(?P<field>description|system_prompt|model|tools|knowledges|mcps|skills|depends_on|allowed_targets|max_retries|communication_mode|plugin)\s*[:=：]\s*(?P<value>.+)"
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

_SUPERVISOR_HINT_KEYWORDS = {
    "supervisor",
    "可观测",
    "审计",
    "追踪",
    "路由",
    "监管",
    "治理",
}

_DEEP_AGENTS_HINT_KEYWORDS = {
    "deepagents",
    "deep_agents",
    "并行",
    "效率",
    "吞吐",
    "批处理",
    "批量",
}

_SWARM_HINT_KEYWORDS = {
    "swarm",
    "handoff",
    "转接",
    "客服",
    "销售",
    "支持",
    "support",
    "sales",
    "交接",
    "路由到",
    "转给",
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

    def wizard_step(
        self,
        message: str,
        draft: dict[str, Any] | None = None,
        *,
        available_resources: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        merged = self._merge_draft(draft or {}, self._parse_user_message(message))
        normalized = self._normalize_team_payload(merged)
        assembly_meta = {
            "pipeline": "manual_parse",
            "status": "ready",
            "attempts": [],
            "updated_at": self._utc_now_iso(),
        }
        return self._build_wizard_result(
            normalized,
            message=message,
            available_resources=available_resources,
            assembly_meta=assembly_meta,
        )

    async def wizard_step_with_ai(
        self,
        message: str,
        draft: dict[str, Any] | None = None,
        *,
        auto_complete: bool = True,
        available_resources: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        """AI-powered team creation wizard.
        
        Flow:
        1. Parse user message to extract structured fields
        2. If team needs completion, use LLM to understand intent and generate team
        3. Validate and optionally request one more LLM repair pass
        """
        current_draft = dict(draft or {})
        user_patch = self._parse_user_message_with_context(message, current_draft)
        user_explicit_mode = bool(user_patch.get("multi_agent_mode"))
        merged = self._merge_draft(current_draft, user_patch)
        normalized = self._normalize_team_payload(merged)
        assembly_meta = {
            "pipeline": "ai_team_builder",
            "status": "skipped",
            "attempts": [],
            "user_explicit_mode": user_explicit_mode,
            "updated_at": self._utc_now_iso(),
        }

        # Check if AI auto-complete should be triggered
        if auto_complete and self._should_auto_complete(message, normalized):
            normalized, ai_meta = await self._complete_team_with_llm(
                message,
                normalized,
                available_resources=available_resources,
                user_explicit_mode=user_explicit_mode,
            )
            assembly_meta = ai_meta
        elif not auto_complete:
            assembly_meta["status"] = "auto_complete_disabled"
        else:
            assembly_meta["status"] = "auto_complete_not_needed"

        return self._build_wizard_result(
            normalized,
            message=message,
            available_resources=available_resources,
            assembly_meta=assembly_meta,
        )

    async def _complete_team_with_llm(
        self,
        message: str,
        current_team: dict[str, Any],
        *,
        available_resources: dict[str, list[str]] | None = None,
        user_explicit_mode: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Use LLM to complete team draft, then run one repair round if needed."""
        working = self._normalize_team_payload(current_team)
        llm_prompt = message
        build_meta: dict[str, Any] = {
            "pipeline": "ai_blueprint_pipeline",
            "status": "in_progress",
            "started_at": self._utc_now_iso(),
            "attempts": [],
            "mode_alignment_events": [],
            "user_explicit_mode": user_explicit_mode,
            "latest_blueprint": {},
        }

        for idx in range(2):
            blueprint = await self._build_task_blueprint_with_llm(llm_prompt, working)
            ai_patch = await self._generate_team_patch_from_blueprint_with_llm(
                llm_prompt,
                working,
                blueprint=blueprint,
                available_resources=available_resources,
            )
            patch_source = "blueprint"
            if not self._has_meaningful_team_content(ai_patch):
                ai_patch = await self._generate_team_patch_with_llm(llm_prompt, working)
                patch_source = "direct_fallback"
            if not self._has_meaningful_team_content(ai_patch):
                build_meta["attempts"].append(
                    {
                        "attempt": idx + 1,
                        "patch_source": patch_source,
                        "used_blueprint": bool(blueprint),
                        "is_empty_patch": True,
                    }
                )
                break

            working = self._normalize_team_payload(self._merge_draft(working, ai_patch))
            if not user_explicit_mode:
                working, alignment_event = self._align_mode_with_recommendation(
                    llm_prompt,
                    working,
                    available_resources=available_resources,
                )
                if alignment_event:
                    build_meta["mode_alignment_events"].append(alignment_event)

            validation = self.validate_team(
                working,
                strict=False,
                available_resources=available_resources,
            )
            questions = self._build_missing_questions(working)
            if blueprint:
                build_meta["latest_blueprint"] = {
                    "workstream_count": len(blueprint.get("workstreams") or []),
                    "complexity_level": str(blueprint.get("complexity_level") or "").strip(),
                }
            build_meta["attempts"].append(
                {
                    "attempt": idx + 1,
                    "patch_source": patch_source,
                    "used_blueprint": bool(blueprint),
                    "subagent_count": len(working.get("subagents") or []),
                    "selected_mode": working.get("multi_agent_mode") or "disabled",
                    "is_valid": bool(validation["valid"]),
                    "error_count": len(validation.get("errors") or []),
                    "question_count": len(questions),
                }
            )
            if validation["valid"] and not questions:
                build_meta["status"] = "completed"
                break

            llm_prompt = self._build_repair_prompt(
                message=message,
                validation_errors=validation["errors"],
                questions=questions,
            )

        if build_meta["status"] == "in_progress":
            build_meta["status"] = "partial" if build_meta["attempts"] else "no_generation"
        build_meta["completed_at"] = self._utc_now_iso()
        build_meta["final_subagent_count"] = len(working.get("subagents") or [])
        build_meta["final_mode"] = working.get("multi_agent_mode") or "disabled"
        return working, build_meta

    async def _build_task_blueprint_with_llm(
        self,
        message: str,
        current_team: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate an execution blueprint before materializing agents."""
        if os.getenv("YUXI_SKIP_APP_INIT") == "1":
            return {}
        try:
            model = load_chat_model(app_config.default_model, temperature=0)
            response = await model.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "你是任务编排规划器。请把用户需求转成团队执行蓝图 JSON。\n"
                            "输出字段：team_goal,task_scope,complexity_level,workstreams。\n"
                            "workstreams 每项字段：id,objective,depends_on,required_capabilities,deliverables。\n"
                            "只输出 JSON，不要解释。"
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"用户输入:\n{message}\n\n"
                            f"当前草稿:\n{json.dumps(current_team, ensure_ascii=False)}"
                        )
                    ),
                ]
            )
            parsed = self._parse_model_json(getattr(response, "content", response))
            if not isinstance(parsed, dict):
                return {}
            if not isinstance(parsed.get("workstreams"), list):
                return {}
            return parsed
        except Exception as exc:
            logger.warning(f"Build task blueprint failed: {exc}")
            return {}

    async def _generate_team_patch_from_blueprint_with_llm(
        self,
        message: str,
        current_team: dict[str, Any],
        *,
        blueprint: dict[str, Any],
        available_resources: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        """Materialize a DynamicAgent team patch from an AI-generated blueprint."""
        if not blueprint:
            return {}
        if os.getenv("YUXI_SKIP_APP_INIT") == "1":
            return {}

        normalized_resources = self._normalize_available_resources(available_resources)
        try:
            model = load_chat_model(app_config.default_model, temperature=0)
            response = await model.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "你是多 Agent 团队架构师。基于执行蓝图生成 DynamicAgent 团队 JSON。\n"
                            "角色分工必须覆盖蓝图中的 workstreams 且依赖关系无环。\n"
                            "输出 JSON 字段：team_goal,task_scope,multi_agent_mode,communication_protocol,"
                            "max_parallel_tasks,allow_cross_agent_comm,system_prompt,supervisor_system_prompt,subagents。\n"
                            "subagents 每项必须包含 name,description,system_prompt,depends_on,communication_mode,"
                            "tools,knowledges,mcps,skills。\n"
                            "若提供了可用资源列表，只能从该列表中选择资源。\n"
                            "只输出 JSON，不要额外解释。"
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"用户输入:\n{message}\n\n"
                            f"当前草稿:\n{json.dumps(current_team, ensure_ascii=False)}\n\n"
                            f"执行蓝图:\n{json.dumps(blueprint, ensure_ascii=False)}\n\n"
                            f"可用资源:\n{json.dumps(normalized_resources, ensure_ascii=False)}"
                        )
                    ),
                ]
            )
            parsed = self._parse_model_json(getattr(response, "content", response))
            if not isinstance(parsed, dict):
                return {}
            normalized = self._normalize_team_payload(parsed)
            if self._has_meaningful_team_content(normalized):
                return normalized
            return {}
        except Exception as exc:
            logger.warning(f"Generate team from blueprint failed: {exc}")
            return {}

    def _normalize_available_resources(
        self,
        available_resources: dict[str, list[str]] | None = None,
    ) -> dict[str, list[str]]:
        source = available_resources or {}
        return {
            "tools": sorted(set(self._normalize_list_field(source.get("tools")))),
            "knowledges": sorted(set(self._normalize_list_field(source.get("knowledges")))),
            "mcps": sorted(set(self._normalize_list_field(source.get("mcps")))),
            "skills": sorted(set(self._normalize_list_field(source.get("skills")))),
        }

    @staticmethod
    def _has_meaningful_team_content(patch: dict[str, Any] | None) -> bool:
        if not isinstance(patch, dict) or not patch:
            return False

        for field in ("team_goal", "task_scope", "system_prompt", "supervisor_system_prompt"):
            if str(patch.get(field) or "").strip():
                return True
        if patch.get("subagents"):
            return True
        return any(patch.get(field) for field in ("tools", "knowledges", "mcps", "skills"))

    def _align_mode_with_recommendation(
        self,
        message: str,
        team: dict[str, Any],
        *,
        available_resources: dict[str, list[str]] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        validation = self.validate_team(
            team,
            strict=False,
            available_resources=available_resources,
        )
        recommendation = self._recommend_mode(message=message, team=team, validation=validation)
        selected_mode = team.get("multi_agent_mode") or "disabled"
        recommended_mode = recommendation.get("recommended_mode")
        member_count = len(team.get("subagents") or [])

        if selected_mode == "disabled" and member_count > 1 and recommended_mode in TEAM_MODES:
            aligned = dict(team)
            aligned["multi_agent_mode"] = recommended_mode
            return self._normalize_team_payload(aligned), {
                "from_mode": selected_mode,
                "to_mode": recommended_mode,
                "reason": recommendation.get("reason") or "",
                "at": self._utc_now_iso(),
            }
        return team, None

    @staticmethod
    def _build_repair_prompt(
        *,
        message: str,
        validation_errors: list[str],
        questions: list[str],
    ) -> str:
        issues = []
        for err in (validation_errors or [])[:5]:
            issues.append(f"- 校验错误: {err}")
        for q in (questions or [])[:3]:
            issues.append(f"- 缺失字段: {q}")

        if not issues:
            return message

        return (
            f"{message}\n\n"
            "请修复以下问题并重新生成完整团队 JSON：\n"
            f"{chr(10).join(issues)}"
        )

    def _build_wizard_result(
        self,
        normalized: dict[str, Any],
        *,
        message: str = "",
        available_resources: dict[str, list[str]] | None = None,
        assembly_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        check = self.validate_team(
            normalized,
            strict=False,
            available_resources=available_resources,
        )
        questions = self._build_missing_questions(normalized)
        mode_recommendation = self._recommend_mode(
            message=message,
            team=normalized,
            validation=check,
        )
        final_meta = dict(assembly_meta or {})
        final_meta["selected_mode"] = normalized.get("multi_agent_mode") or "disabled"
        final_meta["recommended_mode"] = mode_recommendation.get("recommended_mode")
        final_meta["is_selected_mode_recommended"] = bool(mode_recommendation.get("is_selected_mode_recommended"))
        final_meta["updated_at"] = self._utc_now_iso()

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
            "mode_recommendation": mode_recommendation,
            "resource_validation": check.get("resource_validation") or {},
            "assembly_meta": final_meta,
        }

    def _should_auto_complete(self, message: str, team: dict[str, Any]) -> bool:
        """Determine if AI auto-completion should be triggered.
        
        Auto-complete is triggered when:
        1. Message contains team-related keywords AND team is incomplete, OR
        2. Team has goal/scope but no subagents (needs AI to generate team structure)
        """
        text = (message or "").strip().lower()
        if not text:
            return False

        members = team.get("subagents") or []
        has_goal = bool(team.get("team_goal"))
        has_scope = bool(team.get("task_scope"))
        
        # Case 1: Message looks like team creation intent
        if self._looks_like_team_intent(text):
            if not members:
                return True
            if not has_goal or not has_scope:
                return True
            for member in members:
                if not member.get("description") or not member.get("system_prompt"):
                    return True
        
        # Case 2: User provided goal/scope but no subagents yet
        # This enables conversational team building
        if has_goal and has_scope and not members:
            return True
        
        # Case 3: Message describes a service/function that could be a team
        service_indicators = {
            "客服", "服务", "支持", "咨询", "售前", "售后",
            "分析", "报表", "数据", "开发", "研发", "测试",
            "内容", "创作", "写作", "营销", "运营"
        }
        if any(ind in text for ind in service_indicators) and not members:
            return True

        return False

    @staticmethod
    def _looks_like_team_intent(text: str) -> bool:
        normalized = text.lower()
        return any(key in normalized for key in _TEAM_INTENT_KEYWORDS)

    async def _generate_team_patch_with_llm(self, message: str, current_team: dict[str, Any]) -> dict[str, Any]:
        try:
            model = load_chat_model(app_config.default_model, temperature=0)
            response = await model.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "你是多 Agent 团队架构师。请把用户需求转换成 DynamicAgent 团队 JSON。\n"
                            "必须保证职责边界清晰、依赖有向无环。\n\n"
                            f"{_DEEP_AGENTS_CAPABILITY_HINT}\n\n"
                            "multi_agent_mode 选择规则：\n"
                            "- deep_agents: 任务存在可并行阶段，强调吞吐与效率\n"
                            "- swarm: 需要动态交接、路由转派的一线服务场景\n"
                            "- supervisor: 依赖链长、审计和可观测性要求高\n"
                            "- disabled: 单角色即可完成任务\n\n"
                            "输出 JSON 字段：team_goal,task_scope,multi_agent_mode,communication_protocol,"
                            "max_parallel_tasks,allow_cross_agent_comm,system_prompt,supervisor_system_prompt,subagents。\n"
                            "subagents 每项必须包含 name,description,system_prompt,depends_on,communication_mode。\n"
                            "不要使用固定模板名直接映射；必须根据任务目标和范围推导角色分工。\n"
                            "只输出 JSON，不要额外解释。"
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"用户输入:\n{message}\n\n"
                            f"当前草稿:\n{json.dumps(current_team, ensure_ascii=False)}\n\n"
                            "请根据用户需求生成合适的团队配置，并补全缺失字段。"
                        )
                    ),
                ]
            )
            parsed = self._parse_model_json(getattr(response, "content", response))
            if not isinstance(parsed, dict):
                return {}
            normalized = self._normalize_team_payload(parsed)
            if self._has_meaningful_team_content(normalized):
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
        final_mode_recommendation = dict(mode_recommendation or {})
        if not final_mode_recommendation:
            final_mode_recommendation = self._recommend_mode(
                message="",
                team=team,
                validation=validated,
            )
        runtime_audit = {
            "built_at": self._utc_now_iso(),
            "builder_version": "team-orchestration-v2",
            "build_source": str((assembly_meta or {}).get("pipeline") or "direct_payload"),
            "assembly_status": str((assembly_meta or {}).get("status") or "unknown"),
            "attempts": list((assembly_meta or {}).get("attempts") or []),
            "mode_alignment_events": list((assembly_meta or {}).get("mode_alignment_events") or []),
            "selected_mode": mode,
            "recommended_mode": final_mode_recommendation.get("recommended_mode"),
            "is_selected_mode_recommended": bool(final_mode_recommendation.get("is_selected_mode_recommended")),
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
                "mode_recommendation": final_mode_recommendation,
                "runtime_audit": runtime_audit,
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
        """Parse user message for explicit formatted fields."""
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
                if field in {"tools", "knowledges", "mcps", "skills", "depends_on", "allowed_targets"}:
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

    def _parse_user_message_with_context(
        self,
        message: str,
        current_draft: dict[str, Any],
    ) -> dict[str, Any]:
        """Parse user message with awareness of what's missing in current draft.
        
        If user provides a natural language response and the draft is missing
        required fields (team_goal, task_scope), intelligently map the response
        to the appropriate field.
        """
        # First, try standard parsing
        result = self._parse_user_message(message)
        
        # If we got explicit fields, return them
        if result.get("team_goal") or result.get("task_scope") or result.get("subagents"):
            return result
        
        text = message.strip()
        if not text:
            return result
        
        # Handle confirmation messages - if draft is already complete, just return empty
        # to keep the current draft unchanged
        confirmation_keywords = {"确认", "好的", "ok", "yes", "是的", "同意", "可以", "行", "没问题"}
        if text.lower() in confirmation_keywords or len(text) <= 3:
            # User is confirming, don't try to parse as goal/scope
            return result
        
        # Check if it looks like a JSON or structured input - if so, don't auto-map
        if "{" in text or "```" in text:
            return result
        
        # Check what's missing in current draft and try to intelligently fill it
        missing_goal = not current_draft.get("team_goal")
        missing_scope = not current_draft.get("task_scope")
        
        # If user input looks like a goal/objective description (not a command)
        # and team_goal is missing, treat it as team_goal
        if missing_goal:
            # Heuristics for goal-like input:
            # - Contains words like "服务", "处理", "完成", "实现", etc.
            # - Is a relatively short statement (< 200 chars)
            # - Doesn't look like a command (not starting with "帮我", "请", etc.)
            goal_indicators = {"服务", "处理", "完成", "实现", "提供", "帮助", "解决", "支持",
                               "管理", "分析", "创建", "开发", "构建", "优化", "改进"}
            command_prefixes = {"帮我", "请", "我需要", "我想", "给我", "创建一个"}
            
            text_lower = text.lower()
            is_goal_like = any(ind in text for ind in goal_indicators)
            is_command = any(text.startswith(pref) for pref in command_prefixes)
            
            # If it looks like a goal statement (not a command) and is reasonably short
            if (is_goal_like or len(text) < 100) and not is_command:
                result["team_goal"] = text
                return result
        
        # If team_goal exists but task_scope is missing, and user provides additional context
        if not missing_goal and missing_scope:
            scope_indicators = {"范围", "包括", "覆盖", "不包括", "职责", "边界"}
            if any(ind in text for ind in scope_indicators) or len(text) < 150:
                result["task_scope"] = text
                return result
        
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
                data.get("communication_mode")
                if data.get("communication_mode") in COMMUNICATION_MODES
                else "hybrid"
            ),
            "max_retries": self._safe_int(data.get("max_retries"), 1),
            "plugin": str(data.get("plugin") or "default").strip() or "default",
        }

    def _recommend_mode(
        self,
        *,
        message: str,
        team: dict[str, Any],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        """Intelligently recommend the best multi-agent mode based on context.
        
        Factors considered:
        1. Explicit user keywords (highest priority)
        2. Team structure analysis (member count, dependencies)
        3. Communication patterns (handoff vs parallel vs sequential)
        4. Resource configuration (tools, MCPs distribution)
        """
        text = (message or "").lower()
        selected_mode = team.get("multi_agent_mode") or "disabled"
        members = team.get("subagents") or []
        execution_groups = validation.get("execution_groups") or []
        has_parallel_stage = any(isinstance(group, list) and len(group) > 1 for group in execution_groups)
        
        # Analyze team structure for better recommendations
        member_count = len(members)
        has_dependencies = any(m.get("depends_on") for m in members if isinstance(m, dict))
        has_default_agent = any(m.get("is_default") for m in members if isinstance(m, dict))
        
        # Check for handoff-like patterns in member descriptions
        handoff_patterns = {"转接", "转给", "交接", "handoff", "transfer", "route to", "路由到"}
        member_descs = " ".join(m.get("description", "") for m in members if isinstance(m, dict)).lower()
        has_handoff_pattern = any(p in member_descs or p in text for p in handoff_patterns)
        
        # Analyze resource distribution across agents
        tools_per_agent = [len(m.get("tools", [])) for m in members if isinstance(m, dict)]
        mcps_per_agent = [len(m.get("mcps", [])) for m in members if isinstance(m, dict)]
        has_specialized_agents = tools_per_agent and max(tools_per_agent) > 0 and min(tools_per_agent) == 0
        
        # Score-based recommendation
        scores = {
            "disabled": 0,
            "supervisor": 0,
            "deep_agents": 0,
            "swarm": 0,
        }
        reasons = []
        
        # 1. Explicit keywords (highest weight)
        if "disabled" in text or "单智能体" in text:
            scores["disabled"] += 100
            reasons.append("用户明确指定单智能体模式")
        
        if any(key in text for key in _SWARM_HINT_KEYWORDS):
            scores["swarm"] += 80
            reasons.append("用户输入包含 Swarm/Handoff 相关关键词")
        
        if any(key in text for key in _SUPERVISOR_HINT_KEYWORDS):
            scores["supervisor"] += 80
            reasons.append("用户输入强调可观测与治理")
        
        if any(key in text for key in _DEEP_AGENTS_HINT_KEYWORDS):
            scores["deep_agents"] += 80
            reasons.append("用户输入强调并行与效率")
        
        # 2. Team structure analysis
        if member_count <= 1:
            scores["disabled"] += 50
            reasons.append("团队成员较少")
        elif member_count >= 5:
            scores["supervisor"] += 20
            reasons.append("团队成员较多，Supervisor 便于管理")
        
        # 3. Communication pattern analysis
        if has_handoff_pattern:
            scores["swarm"] += 40
            reasons.append("检测到 Agent 间交接模式")
        
        if has_default_agent and member_count > 2:
            scores["swarm"] += 30
            reasons.append("存在默认入口 Agent，符合 Swarm 模式")
        
        if has_parallel_stage:
            scores["deep_agents"] += 40
            reasons.append("依赖分组存在可并行阶段")
        
        if has_dependencies and not has_parallel_stage:
            scores["supervisor"] += 30
            reasons.append("存在依赖关系但无明显并行收益")
        
        # 4. Resource distribution analysis
        if has_specialized_agents:
            scores["swarm"] += 20
            scores["supervisor"] += 20
            reasons.append("Agent 职责分工明确")
        
        # Determine recommended mode
        max_score = max(scores.values())
        if max_score == 0:
            # Default fallback logic
            if member_count <= 1:
                recommended = "disabled"
                reason = "当前团队成员较少，单智能体更直接。"
            else:
                recommended = "supervisor"
                reason = "需要多角色协作且无明确专业化需求，Supervisor 更稳健。"
        else:
            recommended = max(scores, key=scores.get)
            reason = "；".join(reasons[:3]) if reasons else "基于团队配置分析。"
        
        # Build detailed recommendation
        mode_descriptions = {
            "disabled": "单智能体模式 - 适合简单任务",
            "supervisor": "Supervisor 模式 - 可观测、易调试，适合复杂工作流",
            "deep_agents": "Deep Agents 模式 - 高效并行，适合大负载任务",
            "swarm": "Swarm Handoff 模式 - 动态交接，适合客服/销售场景",
        }

        return {
            "recommended_mode": recommended,
            "reason": reason,
            "selected_mode": selected_mode,
            "is_selected_mode_recommended": selected_mode == recommended,
            "mode_scores": scores,
            "mode_description": mode_descriptions.get(recommended, ""),
            "analysis_factors": reasons,
        }

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
            "skills": sorted(set(member.get("skills") or [])),
        }
        return json.dumps(material, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(UTC).isoformat()


team_orchestration_service = TeamOrchestrationService()


__all__ = ["TeamOrchestrationService", "team_orchestration_service"]
