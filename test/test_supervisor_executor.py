from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.agent_platform.blueprint.models import AgentBlueprint, BlueprintWorker  # noqa: E402
from src.agent_platform.executors.supervisor_executor import SupervisorExecutor  # noqa: E402
from src.agent_platform.runtime.models import RunContext  # noqa: E402
from src.agent_platform.spec.compiler import AgentSpecCompiler  # noqa: E402
from src.agent_platform.types import ExecutionMode, WorkerKind  # noqa: E402


def test_supervisor_executor_prepare_run_preserves_worker_order_and_disables_dynamic_spawn():
    spec = AgentSpecCompiler().compile(
        AgentBlueprint(
            name="SQL Review Team",
            goal="Route SQL review steps in order",
            execution_mode=ExecutionMode.SUPERVISOR,
            max_dynamic_workers=4,
            workers=[
                BlueprintWorker(key="schema_worker", name="Schema Worker", kind=WorkerKind.RETRIEVAL),
                BlueprintWorker(
                    key="sql_worker",
                    name="SQL Worker",
                    kind=WorkerKind.TOOL,
                    depends_on=["schema_worker"],
                    allow_dynamic_spawn=True,
                ),
            ],
        )
    )
    run_context = RunContext(
        thread_id="thread-1",
        user_id="user-1",
        agent_spec_id=spec.spec_id,
    )

    plan = SupervisorExecutor().prepare_run(spec, run_context)

    assert plan.executor_mode is ExecutionMode.SUPERVISOR
    assert plan.entry_worker == "schema_worker"
    assert plan.worker_order == ["schema_worker", "sql_worker"]
    assert plan.dynamic_worker_enabled is False
    assert plan.max_dynamic_workers == 0
