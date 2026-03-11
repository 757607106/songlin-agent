from __future__ import annotations

from src.agent_platform.reporter.blueprint import build_reporter_blueprint
from src.agent_platform.spec.compiler import AgentSpecCompiler
from src.agent_platform.spec.models import AgentSpec
from src.agents.reporter.context import ReporterContext


def build_reporter_spec(
    context: ReporterContext,
    *,
    compiler: AgentSpecCompiler | None = None,
    resolved_skill_sources: list[str] | None = None,
) -> AgentSpec:
    return (compiler or AgentSpecCompiler()).compile(
        build_reporter_blueprint(context, resolved_skill_sources=resolved_skill_sources)
    )
