from __future__ import annotations

from src.agent_platform.blueprint.models import AgentBlueprint, BlueprintWorker
from src.agent_platform.examples.registry import AgentExample, AgentExampleRegistry
from src.agent_platform.spec.compiler import AgentSpecCompiler
from src.agent_platform.types import ExecutionMode, RetrievalMode, WorkerKind

_compiler = AgentSpecCompiler()


def _build_example(
    *,
    example_id: str,
    name: str,
    category: str,
    description: str,
    sample_prompts: list[str],
    blueprint: AgentBlueprint,
) -> AgentExample:
    return AgentExample(
        example_id=example_id,
        name=name,
        category=category,
        description=description,
        sample_prompts=sample_prompts,
        blueprint=blueprint,
        spec=_compiler.compile(blueprint),
    )


_DEFAULT_AGENT_EXAMPLES = [
    _build_example(
        example_id="legacy/knowledge_qa_minimal",
        name="Knowledge QA Minimal",
        category="legacy",
        description="保留原 ChatbotAgent 的知识问答链路，适合文档问答、FAQ 和知识库客服。",
        sample_prompts=[
            "帮我创建一个 FAQ 问答助手",
            "做一个知识库检索后再回答的客服 Agent",
        ],
        blueprint=AgentBlueprint(
            name="知识问答示例",
            description="面向知识库和 FAQ 的受控问答示例。",
            goal="先检索证据，再输出稳定答案。",
            task_scope="知识库问答、FAQ 和资料检索",
            execution_mode=ExecutionMode.SUPERVISOR,
            retrieval_mode=RetrievalMode.HYBRID,
            system_prompt="你负责组织知识问答流程，先检索证据，再给出可解释答复。",
            supervisor_prompt="先路由到检索 worker，再交由答复 worker 整理结果。",
            workers=[
                BlueprintWorker(
                    key="intake_worker",
                    name="Intake Worker",
                    description="理解问题范围。",
                    objective="明确用户真实问题。",
                    system_prompt="识别问题目标、上下文和必要约束。",
                ),
                BlueprintWorker(
                    key="retrieval_worker",
                    name="Knowledge Retriever",
                    description="检索知识和文档证据。",
                    objective="提供高相关证据。",
                    system_prompt="从知识库或文档中提取高相关证据并保留来源。",
                    kind=WorkerKind.RETRIEVAL,
                    depends_on=["intake_worker"],
                ),
                BlueprintWorker(
                    key="answer_worker",
                    name="Answer Reviewer",
                    description="整合证据并输出最终答案。",
                    objective="输出清晰稳定的最终答复。",
                    system_prompt="基于证据回答问题，不确定时明确说明边界。",
                    depends_on=["retrieval_worker"],
                ),
            ],
        ),
    ),
    _build_example(
        example_id="legacy/research_analyst_deep",
        name="Research Analyst Deep",
        category="legacy",
        description="保留原 DeepAgent 的规划与执行能力，适合开放式研究和复杂分析。",
        sample_prompts=[
            "创建一个能规划并执行市场调研的 Agent",
            "做一个会拆解任务、检索信息并综合结论的研究团队",
        ],
        blueprint=AgentBlueprint(
            name="深度研究示例",
            description="面向复杂研究、调研和开放式分析的深度执行示例。",
            goal="规划、执行并收敛复杂研究任务。",
            task_scope="研究、调研、开放式分析",
            execution_mode=ExecutionMode.DEEP_AGENTS,
            system_prompt="你负责规划、委派和整合复杂研究任务。",
            max_parallel_workers=3,
            max_dynamic_workers=3,
            workers=[
                BlueprintWorker(
                    key="planner_worker",
                    name="Research Planner",
                    description="规划研究步骤并拆解任务。",
                    objective="拆解复杂研究任务。",
                    system_prompt="负责拆解任务、协调执行并决定是否需要派生 worker。",
                    allow_dynamic_spawn=True,
                ),
                BlueprintWorker(
                    key="research_worker",
                    name="Research Worker",
                    description="检索资料并补充证据。",
                    objective="提供外部证据和知识支持。",
                    system_prompt="负责检索和整理研究证据。",
                    kind=WorkerKind.RETRIEVAL,
                    depends_on=["planner_worker"],
                ),
                BlueprintWorker(
                    key="tool_worker",
                    name="Tool Operator",
                    description="执行工具和外部能力。",
                    objective="完成工具调用和副作用执行。",
                    system_prompt="负责调用工具并返回结构化结果。",
                    kind=WorkerKind.TOOL,
                    depends_on=["planner_worker"],
                ),
                BlueprintWorker(
                    key="synthesis_worker",
                    name="Synthesis Worker",
                    description="收敛研究结果。",
                    objective="整合结果并输出最终结论。",
                    system_prompt="整合研究证据和执行结果，输出最终结论。",
                    depends_on=["research_worker", "tool_worker"],
                ),
            ],
        ),
    ),
    _build_example(
        example_id="legacy/document_organizer_review",
        name="Document Organizer Review",
        category="legacy",
        description="保留原 DocOrganizerAgent 的文档整理与复核链路，适合资料整理和归档。",
        sample_prompts=[
            "做一个文档整理助手，把资料归档成结构化结果",
            "创建一个能整理输入资料并复核输出的 Agent",
        ],
        blueprint=AgentBlueprint(
            name="文档整理示例",
            description="面向资料整理、归档和结构化输出的示例。",
            goal="整理输入资料并输出结构化文档。",
            task_scope="文档整理、资料归档、结构化输出",
            execution_mode=ExecutionMode.SUPERVISOR,
            retrieval_mode=RetrievalMode.HYBRID,
            system_prompt="你负责组织文档整理流程，确保输出结构清晰、可复用。",
            supervisor_prompt="先理解整理目标，再执行整理，最后复核输出。",
            workers=[
                BlueprintWorker(
                    key="intake_worker",
                    name="Intake Worker",
                    description="识别资料范围和输出目标。",
                    objective="明确整理目标。",
                    system_prompt="识别资料类型、范围和预期产物。",
                ),
                BlueprintWorker(
                    key="curation_worker",
                    name="Document Curator",
                    description="执行归档和结构化整理。",
                    objective="整理资料并生成结构化输出。",
                    system_prompt="完成文档整理、归档和结构化输出。",
                    kind=WorkerKind.TOOL,
                    depends_on=["intake_worker"],
                ),
                BlueprintWorker(
                    key="review_worker",
                    name="Review Worker",
                    description="检查结果质量。",
                    objective="复核并输出最终版本。",
                    system_prompt="复核整理结果的完整性、可读性和边界。",
                    depends_on=["curation_worker"],
                ),
            ],
        ),
    ),
]

agent_example_registry = AgentExampleRegistry(_DEFAULT_AGENT_EXAMPLES)
