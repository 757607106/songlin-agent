from __future__ import annotations

from src.agent_platform.blueprint.models import AgentBlueprint, BlueprintWorker
from src.agent_platform.blueprint.registry import BlueprintTemplate, BlueprintTemplateRegistry
from src.agent_platform.types import ExecutionMode, RetrievalMode, WorkerKind
from src.agent_platform.workers.registry import WorkerTemplate, WorkerTemplateRegistry

_DEFAULT_WORKER_TEMPLATES = [
    WorkerTemplate(
        template_id="legacy/knowledge_retriever",
        name="Knowledge Retriever",
        kind=WorkerKind.RETRIEVAL,
        description="继承原 ChatbotAgent 的知识检索职责，负责从知识库或资料中提取证据。",
        objective="检索与问题相关的知识证据。",
    ),
    WorkerTemplate(
        template_id="legacy/answer_reviewer",
        name="Answer Reviewer",
        kind=WorkerKind.REASONING,
        description="继承原 ChatbotAgent 的答复收敛职责，负责整合证据并输出最终答复。",
        objective="整合信息并输出稳定答案。",
    ),
    WorkerTemplate(
        template_id="legacy/research_planner",
        name="Research Planner",
        kind=WorkerKind.REASONING,
        description="继承原 DeepAgent 的规划职责，负责拆解复杂任务并协调整体执行。",
        objective="拆解任务并协调多步执行。",
    ),
    WorkerTemplate(
        template_id="legacy/tool_operator",
        name="Tool Operator",
        kind=WorkerKind.TOOL,
        description="继承原 DeepAgent 的工具执行职责，负责调用外部工具、MCP 和副作用能力。",
        objective="执行工具调用并返回结构化结果。",
    ),
    WorkerTemplate(
        template_id="legacy/document_curator",
        name="Document Curator",
        kind=WorkerKind.TOOL,
        description="继承原 DocOrganizerAgent 的文档整理职责，负责整理、归档和输出文档结果。",
        objective="整理文档并输出可复用结果。",
    ),
]

_DEFAULT_BLUEPRINT_TEMPLATES = [
    BlueprintTemplate(
        template_id="legacy/knowledge_qa",
        name="Knowledge QA Template",
        category="legacy",
        description="保留原 ChatbotAgent 的知识问答能力，适合知识库问答与资料检索场景。",
        prompt_hints=["知识库", "问答", "文档问答", "faq", "资料", "客服知识"],
        blueprint=AgentBlueprint(
            name="知识问答助手",
            description="面向知识库和文档的问答助手。",
            goal="基于知识和资料稳定回答用户问题。",
            task_scope="知识问答",
            execution_mode=ExecutionMode.SUPERVISOR,
            retrieval_mode=RetrievalMode.HYBRID,
            system_prompt="你负责组织知识问答流程，确保答案有依据、表达清晰。",
            supervisor_prompt="优先让检索 worker 提供证据，再由答复 worker 汇总输出。",
            workers=[
                BlueprintWorker(
                    key="intake_worker",
                    name="Intake Worker",
                    description="理解用户问题和上下文。",
                    objective="明确用户问题范围。",
                    system_prompt="你负责识别问题意图，并为检索提供清晰查询目标。",
                ),
                BlueprintWorker(
                    key="retrieval_worker",
                    name="Knowledge Retriever",
                    description="从知识库和资料中检索证据。",
                    objective="返回高相关证据。",
                    system_prompt="你负责检索证据并给出可追踪来源。",
                    kind=WorkerKind.RETRIEVAL,
                    depends_on=["intake_worker"],
                ),
                BlueprintWorker(
                    key="answer_worker",
                    name="Answer Reviewer",
                    description="整合证据并输出最终答复。",
                    objective="给出稳定且可解释的最终答案。",
                    system_prompt="你负责整合证据、指出不确定性并输出最终答复。",
                    depends_on=["retrieval_worker"],
                ),
            ],
        ),
    ),
    BlueprintTemplate(
        template_id="legacy/research_analyst",
        name="Research Analyst Template",
        category="legacy",
        description="保留原 DeepAgent 的规划执行能力，适合研究、调研和开放式分析。",
        prompt_hints=["研究", "调研", "分析", "规划并执行", "深度分析", "复杂任务"],
        blueprint=AgentBlueprint(
            name="研究分析团队",
            description="面向复杂研究和多步分析任务的执行模板。",
            goal="规划并完成复杂研究任务。",
            task_scope="复杂研究",
            execution_mode=ExecutionMode.DEEP_AGENTS,
            system_prompt="你负责规划、调度和收敛复杂研究任务，必要时可派生临时 worker。",
            max_parallel_workers=3,
            max_dynamic_workers=3,
            workers=[
                BlueprintWorker(
                    key="planner_worker",
                    name="Research Planner",
                    description="拆解任务并规划执行路径。",
                    objective="制定研究计划并协调执行。",
                    system_prompt="你负责拆解任务、安排执行顺序，并决定是否需要派生 worker。",
                    allow_dynamic_spawn=True,
                ),
                BlueprintWorker(
                    key="research_worker",
                    name="Research Worker",
                    description="补充资料和证据。",
                    objective="提供研究证据。",
                    system_prompt="你负责查找、归纳并返回证据。",
                    kind=WorkerKind.RETRIEVAL,
                    depends_on=["planner_worker"],
                ),
                BlueprintWorker(
                    key="tool_worker",
                    name="Tool Operator",
                    description="执行工具或外部能力。",
                    objective="完成工具执行。",
                    system_prompt="你负责执行工具调用并返回结构化结果。",
                    kind=WorkerKind.TOOL,
                    depends_on=["planner_worker"],
                ),
                BlueprintWorker(
                    key="synthesis_worker",
                    name="Synthesis Worker",
                    description="整合并收敛最终结果。",
                    objective="汇总研究结论。",
                    system_prompt="你负责整合多个子结果并输出最终结论。",
                    depends_on=["research_worker", "tool_worker"],
                ),
            ],
        ),
    ),
    BlueprintTemplate(
        template_id="legacy/document_organizer",
        name="Document Organizer Template",
        category="legacy",
        description="保留原 DocOrganizerAgent 的文档整理能力，适合整理资料、归档和输出结构化文档。",
        prompt_hints=["文档整理", "资料整理", "归档", "文件整理", "知识整理", "整理文档"],
        blueprint=AgentBlueprint(
            name="文档整理助手",
            description="用于整理资料、归档内容和输出结构化文档。",
            goal="整理输入资料并产出结构化结果。",
            task_scope="文档整理",
            execution_mode=ExecutionMode.SUPERVISOR,
            retrieval_mode=RetrievalMode.HYBRID,
            system_prompt="你负责组织文档整理流程，确保产出结构化、可复用。",
            supervisor_prompt="先识别资料内容，再进行整理和复核。",
            workers=[
                BlueprintWorker(
                    key="intake_worker",
                    name="Intake Worker",
                    description="识别资料范围和整理目标。",
                    objective="明确整理目标。",
                    system_prompt="你负责识别资料类型、范围和预期输出。",
                ),
                BlueprintWorker(
                    key="curation_worker",
                    name="Document Curator",
                    description="执行归档、整理和结构化输出。",
                    objective="生成整理后的结构化文档。",
                    system_prompt="你负责整理资料、归档结构并生成结构化输出。",
                    kind=WorkerKind.TOOL,
                    depends_on=["intake_worker"],
                ),
                BlueprintWorker(
                    key="review_worker",
                    name="Review Worker",
                    description="检查整理结果的完整性和可读性。",
                    objective="输出最终整理结果。",
                    system_prompt="你负责复核整理结果并输出最终版本。",
                    depends_on=["curation_worker"],
                ),
            ],
        ),
    ),
]

blueprint_template_registry = BlueprintTemplateRegistry(_DEFAULT_BLUEPRINT_TEMPLATES)
worker_template_registry = WorkerTemplateRegistry(_DEFAULT_WORKER_TEMPLATES)
