from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.agent_platform.blueprint.models import AgentBlueprint  # noqa: E402
from src.agent_platform.runtime.memory_service import resolve_memory_namespaces  # noqa: E402
from src.agent_platform.runtime.models import RunContext  # noqa: E402
from src.agent_platform.spec.compiler import AgentSpecCompiler  # noqa: E402


def test_resolve_memory_namespaces_expands_user_scoped_store_paths():
    spec = AgentSpecCompiler().compile(
        AgentBlueprint(
            name="Playbook Agent",
            goal="Keep reusable response playbooks",
            long_term_memory_namespace="shared/assistant",
        )
    )
    run_context = RunContext(
        thread_id="thread-1",
        user_id="user/ops",
        agent_spec_id=spec.spec_id,
    )

    namespaces = resolve_memory_namespaces(spec, run_context)

    assert namespaces.user_preferences == "/memory/users/user-ops/preferences"
    assert namespaces.user_facts == "/memory/users/user-ops/facts"
    assert namespaces.agent_playbooks == "/memory/agents/shared/assistant/playbooks"
