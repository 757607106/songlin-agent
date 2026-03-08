from __future__ import annotations

from src.agents.dynamic_agent.supervisor import _compute_eligible_targets


def test_compute_eligible_targets_respects_dependency_communication_and_retry():
    eligible = _compute_eligible_targets(
        agent_names=["planner", "researcher", "writer"],
        active_agent="planner",
        completed_agents=[],
        dependency_map={
            "planner": set(),
            "researcher": {"planner"},
            "writer": set(),
        },
        communication_matrix={"planner": ["researcher", "writer"]},
        route_history=["writer"],
        retry_counts={"writer": 1},
        retry_limits={"planner": 1, "researcher": 1, "writer": 1},
    )

    # researcher has unmet dependency, writer exceeds retry guard.
    assert eligible == []

    eligible_after_planner_done = _compute_eligible_targets(
        agent_names=["planner", "researcher", "writer"],
        active_agent="planner",
        completed_agents=["planner"],
        dependency_map={
            "planner": set(),
            "researcher": {"planner"},
            "writer": set(),
        },
        communication_matrix={"planner": ["researcher", "writer"]},
        route_history=["writer"],
        retry_counts={"writer": 1},
        retry_limits={"planner": 1, "researcher": 1, "writer": 1},
    )

    assert eligible_after_planner_done == ["researcher"]
