from __future__ import annotations

import traceback
from collections.abc import AsyncIterator, Awaitable, Callable

from src.services.chat_stream_event_adapter import (
    human_approval_required_chunk,
    runtime_append_event,
    runtime_transition,
)
from src.services.interrupt_protocol import normalize_approval_interrupt_info
from src.utils.logging_config import logger


async def check_and_handle_interrupts(
    graph,
    langgraph_config: dict,
    make_chunk,
    meta: dict,
    thread_id: str,
    on_interrupt: Callable[[str, str], Awaitable[None]] | None = None,
) -> AsyncIterator[bytes]:
    try:
        state = await graph.aget_state(langgraph_config)

        if not state or not state.values:
            return

        interrupt_info = None

        if hasattr(state, "tasks") and state.tasks:
            for task in state.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    interrupt_info = task.interrupts[0]
                    break

        if not interrupt_info and state.values:
            interrupt_data = state.values.get("__interrupt__")
            if interrupt_data and isinstance(interrupt_data, list) and len(interrupt_data) > 0:
                interrupt_info = interrupt_data[0]

        if interrupt_info:
            approval_interrupt = normalize_approval_interrupt_info(interrupt_info)
            question = approval_interrupt.question
            operation = approval_interrupt.operation
            allowed_decisions = approval_interrupt.allowed_decisions

            meta["interrupt"] = approval_interrupt.to_payload() | {"thread_id": thread_id}
            await runtime_transition(
                meta=meta,
                next_status="paused",
                actor_type="system",
                actor_name="chat_stream_service",
                reason=operation,
            )
            await runtime_append_event(
                meta=meta,
                event_type="run.paused",
                actor_type="system",
                actor_name="chat_stream_service",
                payload={
                    "thread_id": thread_id,
                    "question": question,
                    "operation": operation,
                    "allowed_decisions": allowed_decisions,
                },
            )
            if on_interrupt:
                await on_interrupt(question, operation)
            yield human_approval_required_chunk(
                meta=meta,
                message=question,
                thread_id=thread_id,
                interrupt_info=approval_interrupt.to_payload(),
            )

    except Exception as e:
        logger.error(f"Error checking interrupts: {e}")
        logger.error(traceback.format_exc())
