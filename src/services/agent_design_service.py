from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from src.agent_platform.constants import AGENT_PLATFORM_AGENT_ID
from src.agent_platform.blueprint.models import AgentBlueprint, BlueprintWorker
from src.agent_platform.blueprint.registry import BlueprintTemplate, BlueprintTemplateRegistry
from src.agent_platform.blueprint.validator import AgentBlueprintValidator
from src.agent_platform.example_catalog import agent_example_registry
from src.agent_platform.examples.registry import AgentExampleRegistry
from src.agent_platform.spec.compiler import AgentSpecCompiler
from src.agent_platform.spec.models import AgentSpec
from src.agent_platform.template_catalog import blueprint_template_registry, worker_template_registry
from src.agent_platform.types import ExecutionMode, WorkerKind, dedupe_strings
from src.agent_platform.workers.registry import WorkerTemplateRegistry
from src.agents.common import load_chat_model
from src.config import config as app_config
from src.repositories.agent_config_repository import AgentConfigRepository
from src.utils import logger

AGENT_PLATFORM_CONFIG_ID = AGENT_PLATFORM_AGENT_ID

_DEEP_AGENT_KEYWORDS = {"deep agents", "deepagents", "自主", "自动创建子agent", "规划并执行", "调研", "研究"}
_SUPERVISOR_KEYWORDS = {"多智能体", "协作", "分工", "审核", "审批", "编排", "流程", "数据库", "sql", "报表"}
_SWARM_KEYWORDS = {"handoff", "swarm", "接待", "客服", "销售", "移交"}
_RETRIEVAL_KEYWORDS = {"知识库", "文档", "rag", "检索", "搜索", "资料", "研究", "调研"}
_TOOL_KEYWORDS = {"数据库", "sql", "报表", "执行", "工具", "图表", "mcp", "api", "查询"}
_MCP_KEYWORDS = {"图表", "浏览器", "mcp", "外部服务", "第三方"}

_LEADING_PHRASES = (
    "帮我创建一个",
    "帮我做一个",
    "创建一个",
    "做一个",
    "生成一个",
    "我需要一个",
    "请创建一个",
    "请帮我创建一个",
    "帮我搭一个",
)


class AgentIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_request: str
    inferred_name: str
    summary: str
    execution_mode: ExecutionMode
    complexity: str
    requires_retrieval: bool = False
    requires_tools: bool = False
    requires_mcp: bool = False
    allows_dynamic_workers: bool = False
    notes: list[str] = Field(default_factory=list)


class DraftBlueprintResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    intent: AgentIntent
    blueprint: AgentBlueprint


class AgentDesignService:
    def __init__(
        self,
        *,
        validator: AgentBlueprintValidator | None = None,
        compiler: AgentSpecCompiler | None = None,
        blueprint_templates: BlueprintTemplateRegistry | None = None,
        worker_templates: WorkerTemplateRegistry | None = None,
        examples: AgentExampleRegistry | None = None,
    ):
        self._validator = validator or AgentBlueprintValidator()
        self._compiler = compiler or AgentSpecCompiler(self._validator)
        self._blueprint_templates = blueprint_templates or blueprint_template_registry
        self._worker_templates = worker_templates or worker_template_registry
        self._examples = examples or agent_example_registry

    def parse_intent(self, prompt: str) -> AgentIntent:
        text = (prompt or "").strip()
        if not text:
            raise ValueError("prompt 不能为空")

        lowered = text.lower()
        requires_retrieval = any(keyword in lowered for keyword in _RETRIEVAL_KEYWORDS)
        requires_tools = any(keyword in lowered for keyword in _TOOL_KEYWORDS)
        requires_mcp = any(keyword in lowered for keyword in _MCP_KEYWORDS)

        if any(keyword in lowered for keyword in _SWARM_KEYWORDS):
            execution_mode = ExecutionMode.SWARM_HANDOFF
        elif any(keyword in lowered for keyword in _DEEP_AGENT_KEYWORDS):
            execution_mode = ExecutionMode.DEEP_AGENTS
        elif any(keyword in lowered for keyword in _SUPERVISOR_KEYWORDS) or requires_retrieval or requires_tools:
            execution_mode = ExecutionMode.SUPERVISOR
        else:
            execution_mode = ExecutionMode.SINGLE

        complexity = "low"
        notes: list[str] = []
        if execution_mode in {ExecutionMode.SUPERVISOR, ExecutionMode.SWARM_HANDOFF}:
            complexity = "medium"
        if execution_mode is ExecutionMode.DEEP_AGENTS:
            complexity = "high"
            notes.append("适合开放式任务，允许动态创建子 worker")
        if requires_retrieval:
            notes.append("需要检索层")
        if requires_tools:
            notes.append("需要工具执行层")
        if requires_mcp:
            notes.append("需要 MCP 能力接入")

        return AgentIntent(
            original_request=text,
            inferred_name=self._derive_name(text, execution_mode=execution_mode),
            summary=self._summarize_request(text),
            execution_mode=execution_mode,
            complexity=complexity,
            requires_retrieval=requires_retrieval,
            requires_tools=requires_tools,
            requires_mcp=requires_mcp,
            allows_dynamic_workers=execution_mode in {ExecutionMode.DEEP_AGENTS, ExecutionMode.SWARM_HANDOFF},
            notes=notes,
        )

    async def draft_blueprint(
        self,
        *,
        prompt: str,
        available_resources: dict[str, list[str]] | None = None,
        model_name: str | None = None,
        use_ai: bool = True,
    ) -> DraftBlueprintResult:
        intent = self.parse_intent(prompt)
        if use_ai:
            try:
                blueprint = await self._draft_with_llm(
                    prompt=prompt,
                    intent=intent,
                    available_resources=available_resources or {},
                    model_name=model_name or app_config.default_model,
                )
                return DraftBlueprintResult(source="llm", intent=intent, blueprint=blueprint)
            except Exception as exc:
                logger.warning("AgentDesignService llm draft failed, fallback to rules: {}", exc)

        matched_template = self._match_blueprint_template(prompt, intent)
        if matched_template is not None:
            return DraftBlueprintResult(
                source="template",
                intent=intent,
                blueprint=self._draft_from_template(
                    matched_template,
                    intent=intent,
                    available_resources=available_resources or {},
                ),
            )

        return DraftBlueprintResult(
            source="rules",
            intent=intent,
            blueprint=self._draft_with_rules(intent, available_resources=available_resources or {}),
        )

    def validate_blueprint(self, blueprint: AgentBlueprint | dict[str, Any]) -> dict[str, Any]:
        result = self._validator.validate(blueprint)
        return result.model_dump(mode="json")

    def compile_blueprint(self, blueprint: AgentBlueprint | dict[str, Any]) -> AgentSpec:
        return self._compiler.compile(blueprint)

    def list_blueprint_templates(self) -> list[dict[str, Any]]:
        return [template.model_dump(mode="json") for template in self._blueprint_templates.list()]

    def list_worker_templates(self) -> list[dict[str, Any]]:
        return [template.model_dump(mode="json") for template in self._worker_templates.list()]

    def list_templates(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "blueprint_templates": self.list_blueprint_templates(),
            "worker_templates": self.list_worker_templates(),
        }

    def list_examples(self) -> list[dict[str, Any]]:
        return [example.model_dump(mode="json") for example in self._examples.list()]

    async def draft_template(
        self,
        *,
        template_id: str,
        prompt: str = "",
        available_resources: dict[str, list[str]] | None = None,
    ) -> DraftBlueprintResult:
        template = self._blueprint_templates.get(template_id)
        effective_prompt = (prompt or "").strip()
        intent = self.parse_intent(effective_prompt or template.name)
        if not effective_prompt:
            intent.inferred_name = template.blueprint.name
            intent.summary = template.blueprint.goal
            intent.original_request = template.blueprint.task_scope or template.blueprint.goal
            intent.execution_mode = template.blueprint.execution_mode
            intent.allows_dynamic_workers = template.blueprint.execution_mode in {
                ExecutionMode.DEEP_AGENTS,
                ExecutionMode.SWARM_HANDOFF,
            }
        return DraftBlueprintResult(
            source="template",
            intent=intent,
            blueprint=self._draft_from_template(
                template,
                intent=intent,
                available_resources=available_resources or {},
            ),
        )

    async def deploy_blueprint(
        self,
        *,
        repo: AgentConfigRepository,
        department_id: int,
        user_id: str,
        blueprint: AgentBlueprint | dict[str, Any],
        spec: AgentSpec | dict[str, Any] | None = None,
        name: str | None = None,
        description: str | None = None,
        icon: str | None = None,
        pics: list[str] | None = None,
        examples: list[str] | None = None,
        set_default: bool = False,
    ):
        blueprint_model = (
            blueprint if isinstance(blueprint, AgentBlueprint) else AgentBlueprint.model_validate(blueprint)
        )
        spec_model = (
            spec
            if isinstance(spec, AgentSpec)
            else AgentSpec.model_validate(spec)
            if isinstance(spec, dict)
            else self.compile_blueprint(blueprint_model)
        )

        config = await repo.create(
            department_id=department_id,
            agent_id=AGENT_PLATFORM_CONFIG_ID,
            name=name or blueprint_model.name,
            description=description or blueprint_model.description,
            icon=icon,
            pics=pics,
            examples=examples,
            config_json={
                "version": "agent_platform_v2",
                "blueprint": blueprint_model.model_dump(mode="json"),
                "spec": spec_model.model_dump(mode="json"),
            },
            is_default=set_default,
            created_by=user_id,
        )
        if set_default:
            config = await repo.set_default(config=config, updated_by=user_id)
        return config

    async def _draft_with_llm(
        self,
        *,
        prompt: str,
        intent: AgentIntent,
        available_resources: dict[str, list[str]],
        model_name: str,
    ) -> AgentBlueprint:
        model = load_chat_model(model_name)
        baseline = self._draft_with_rules(intent, available_resources=available_resources)
        system_prompt = (
            "你是 Agent 架构设计器。"
            "请基于用户需求返回一个严格的 JSON 对象，用于描述 AgentBlueprint。"
            "只能返回 JSON，不要附加解释。"
            "execution_mode 只能是 single/supervisor/deep_agents/swarm_handoff。"
            "worker.kind 只能是 reasoning/tool/retrieval。"
            "如果没有必要，不要创建超过 4 个 worker。"
        )
        human_prompt = json.dumps(
            {
                "request": prompt,
                "intent": intent.model_dump(mode="json"),
                "available_resources": available_resources,
                "baseline_blueprint": baseline.model_dump(mode="json"),
                "required_fields": [
                    "name",
                    "description",
                    "goal",
                    "task_scope",
                    "execution_mode",
                    "system_prompt",
                    "workers",
                ],
            },
            ensure_ascii=False,
        )
        response = await model.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)])
        payload = self._parse_llm_json_response(response.content)
        return AgentBlueprint.model_validate(payload)

    def _draft_with_rules(
        self,
        intent: AgentIntent,
        *,
        available_resources: dict[str, list[str]],
    ) -> AgentBlueprint:
        tools = self._pick_resources(available_resources, "tools", intent.requires_tools)
        knowledges = self._pick_resources(available_resources, "knowledges", intent.requires_retrieval)
        mcps = self._pick_resources(available_resources, "mcps", intent.requires_mcp)
        skills = self._pick_resources(available_resources, "skills", intent.execution_mode is ExecutionMode.DEEP_AGENTS)

        workers: list[BlueprintWorker]
        if intent.execution_mode is ExecutionMode.SINGLE:
            workers = [
                BlueprintWorker(
                    key="assistant_worker",
                    name="Assistant Worker",
                    description="处理用户请求并输出最终结果。",
                    objective=intent.summary,
                    system_prompt="你负责理解请求、调用必要能力并给出最终答案。",
                    kind=WorkerKind.TOOL if tools else WorkerKind.REASONING,
                    tools=tools,
                    knowledge_ids=knowledges,
                    mcps=mcps,
                    skills=skills,
                )
            ]
        elif intent.execution_mode is ExecutionMode.SWARM_HANDOFF:
            workers = [
                BlueprintWorker(
                    key="reception_worker",
                    name="Reception Worker",
                    description="接收任务并判断应该移交给哪个角色。",
                    objective="分发会话控制权。",
                    system_prompt="你负责识别当前任务适合哪个角色继续处理。",
                    allow_dynamic_spawn=True,
                ),
                BlueprintWorker(
                    key="specialist_worker",
                    name="Specialist Worker",
                    description="执行主要任务。",
                    objective=intent.summary,
                    system_prompt="你负责处理核心任务并在必要时交接。",
                    kind=WorkerKind.TOOL if tools else WorkerKind.RETRIEVAL if knowledges else WorkerKind.REASONING,
                    tools=tools,
                    knowledge_ids=knowledges,
                    mcps=mcps,
                    skills=skills,
                    depends_on=["reception_worker"],
                ),
                BlueprintWorker(
                    key="closer_worker",
                    name="Closer Worker",
                    description="汇总结果并结束会话。",
                    objective="收敛输出。",
                    system_prompt="你负责汇总结果并输出最终答复。",
                    depends_on=["specialist_worker"],
                ),
            ]
        elif intent.execution_mode is ExecutionMode.DEEP_AGENTS:
            workers = [
                BlueprintWorker(
                    key="planner_worker",
                    name="Planner Worker",
                    description="规划任务并决定是否派生新的 worker。",
                    objective="把复杂任务拆解为子任务。",
                    system_prompt="你负责规划、分派和收敛复杂任务。",
                    allow_dynamic_spawn=True,
                    skills=skills,
                ),
                BlueprintWorker(
                    key="research_worker",
                    name="Research Worker",
                    description="检索资料、文档或知识库信息。",
                    objective="为复杂任务补充证据。",
                    system_prompt="你负责检索、归纳并返回证据。",
                    kind=WorkerKind.RETRIEVAL if knowledges else WorkerKind.REASONING,
                    knowledge_ids=knowledges,
                    depends_on=["planner_worker"],
                ),
                BlueprintWorker(
                    key="tool_worker",
                    name="Tool Worker",
                    description="执行工具或外部能力。",
                    objective="完成副作用或数据处理。",
                    system_prompt="你负责调用工具并返回结构化结果。",
                    kind=WorkerKind.TOOL if tools or mcps else WorkerKind.REASONING,
                    tools=tools,
                    mcps=mcps,
                    depends_on=["planner_worker"],
                ),
                BlueprintWorker(
                    key="synthesis_worker",
                    name="Synthesis Worker",
                    description="整合结果并输出结论。",
                    objective="收敛复杂任务的最终结果。",
                    system_prompt="你负责整合多个子任务结果并输出最终结论。",
                    depends_on=["research_worker", "tool_worker"],
                ),
            ]
        else:
            first_kind = WorkerKind.RETRIEVAL if knowledges else WorkerKind.REASONING
            second_kind = WorkerKind.TOOL if tools or mcps else WorkerKind.REASONING
            workers = [
                BlueprintWorker(
                    key="intake_worker",
                    name="Intake Worker",
                    description="理解用户请求并收集必要上下文。",
                    objective="明确任务范围和输入信息。",
                    system_prompt="你负责理解需求、收集必要上下文并为后续执行做准备。",
                    kind=first_kind,
                    knowledge_ids=knowledges,
                ),
                BlueprintWorker(
                    key="execution_worker",
                    name="Execution Worker",
                    description="执行核心步骤。",
                    objective=intent.summary,
                    system_prompt="你负责执行核心步骤并输出结构化结果。",
                    kind=second_kind,
                    tools=tools,
                    mcps=mcps,
                    depends_on=["intake_worker"],
                ),
                BlueprintWorker(
                    key="review_worker",
                    name="Review Worker",
                    description="检查结果并输出最终版本。",
                    objective="保证结果稳定和可读。",
                    system_prompt="你负责复核结果、指出风险并输出最终版本。",
                    depends_on=["execution_worker"],
                ),
            ]

        return AgentBlueprint(
            name=intent.inferred_name,
            description=intent.summary,
            goal=intent.summary,
            task_scope=intent.original_request,
            execution_mode=intent.execution_mode,
            system_prompt=f"你是 {intent.inferred_name}，需要稳定地完成用户请求。",
            default_model=app_config.default_model,
            max_parallel_workers=1 if intent.execution_mode is not ExecutionMode.DEEP_AGENTS else 3,
            max_dynamic_workers=3 if intent.allows_dynamic_workers else 0,
            workers=workers,
        )

    def _match_blueprint_template(self, prompt: str, intent: AgentIntent) -> BlueprintTemplate | None:
        lowered = (prompt or "").strip().lower()
        best_template: BlueprintTemplate | None = None
        best_score = 0
        best_hint_hits = 0

        for template in self._blueprint_templates.list():
            score = 0
            hint_hits = 0
            if template.blueprint.execution_mode is intent.execution_mode:
                score += 1
            for hint in template.prompt_hints:
                candidate = str(hint or "").strip().lower()
                if candidate and candidate in lowered:
                    score += 3
                    hint_hits += 1
            if score > best_score or (score == best_score and hint_hits > best_hint_hits):
                best_score = score
                best_hint_hits = hint_hits
                best_template = template

        return best_template if best_hint_hits > 0 else None

    def _draft_from_template(
        self,
        template: BlueprintTemplate,
        *,
        intent: AgentIntent,
        available_resources: dict[str, list[str]],
    ) -> AgentBlueprint:
        blueprint = template.blueprint.model_copy(deep=True)
        blueprint.name = intent.inferred_name
        blueprint.description = intent.summary
        blueprint.goal = intent.summary
        blueprint.task_scope = intent.original_request
        blueprint.default_model = app_config.default_model

        has_template_tool_worker = any(worker.kind is WorkerKind.TOOL for worker in blueprint.workers)
        has_template_retrieval_worker = any(worker.kind is WorkerKind.RETRIEVAL for worker in blueprint.workers)
        uses_template_skills = blueprint.execution_mode in {ExecutionMode.DEEP_AGENTS, ExecutionMode.SWARM_HANDOFF}

        tools = self._pick_resources(
            available_resources,
            "tools",
            intent.requires_tools or has_template_tool_worker or bool(blueprint.tools),
        )
        knowledges = self._pick_resources(
            available_resources,
            "knowledges",
            intent.requires_retrieval or has_template_retrieval_worker or bool(blueprint.knowledge_ids),
        )
        mcps = self._pick_resources(
            available_resources,
            "mcps",
            intent.requires_mcp or has_template_tool_worker or bool(blueprint.mcps),
        )
        skills = self._pick_resources(
            available_resources,
            "skills",
            intent.execution_mode in {ExecutionMode.DEEP_AGENTS, ExecutionMode.SWARM_HANDOFF} or uses_template_skills,
        )

        has_tool_worker = False
        has_retrieval_worker = False
        has_skill_target = False

        for worker in blueprint.workers:
            if worker.kind is WorkerKind.TOOL:
                has_tool_worker = True
                worker.tools = dedupe_strings([*worker.tools, *tools])
                worker.mcps = dedupe_strings([*worker.mcps, *mcps])
            if worker.kind is WorkerKind.RETRIEVAL:
                has_retrieval_worker = True
                worker.knowledge_ids = dedupe_strings([*worker.knowledge_ids, *knowledges])
            if worker.allow_dynamic_spawn or worker.kind is WorkerKind.REASONING:
                if skills:
                    has_skill_target = True
                    worker.skills = dedupe_strings([*worker.skills, *skills])

        if not has_tool_worker:
            blueprint.tools = dedupe_strings([*blueprint.tools, *tools])
            blueprint.mcps = dedupe_strings([*blueprint.mcps, *mcps])
        if not has_retrieval_worker:
            blueprint.knowledge_ids = dedupe_strings([*blueprint.knowledge_ids, *knowledges])
        if not has_skill_target:
            blueprint.skills = dedupe_strings([*blueprint.skills, *skills])

        return blueprint

    @staticmethod
    def _pick_resources(
        available_resources: dict[str, list[str]],
        key: str,
        enabled: bool,
        *,
        limit: int = 2,
    ) -> list[str]:
        if not enabled:
            return []
        items = available_resources.get(key) or []
        return [str(item).strip() for item in items if str(item).strip()][:limit]

    @staticmethod
    def _parse_llm_json_response(content: Any) -> dict[str, Any]:
        text = content if isinstance(content, str) else str(content)
        text = text.strip()
        if text.startswith("```json"):
            text = text.removeprefix("```json").removesuffix("```").strip()
        try:
            return json.loads(text)
        except Exception:
            import json_repair

            return json_repair.loads(text)

    @staticmethod
    def _summarize_request(prompt: str) -> str:
        text = re.sub(r"\s+", " ", prompt).strip()
        return text[:120]

    @staticmethod
    def _derive_name(prompt: str, *, execution_mode: ExecutionMode) -> str:
        text = re.sub(r"[，。！？、,.!?]", " ", prompt).strip()
        for prefix in _LEADING_PHRASES:
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                break
        text = re.sub(r"\s+", " ", text)
        if not text:
            return "未命名Agent"
        if re.search(r"[\u4e00-\u9fff]", text):
            suffix = "团队" if execution_mode is not ExecutionMode.SINGLE else "助手"
            return f"{text[:12]}{suffix}"
        words = [segment for segment in re.split(r"[^a-zA-Z0-9]+", text) if segment]
        base = " ".join(words[:3]) if words else "Generated Agent"
        suffix = "Team" if execution_mode is not ExecutionMode.SINGLE else "Assistant"
        return f"{base.title()} {suffix}".strip()


agent_design_service = AgentDesignService()
