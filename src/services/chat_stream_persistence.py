from __future__ import annotations

import json
import traceback
from datetime import datetime

from src.repositories.conversation_repository import ConversationRepository
from src.utils.logging_config import logger


def runtime_status_metadata(
    status: str,
    *,
    has_interrupt: bool = False,
    error_message: str | None = None,
) -> dict:
    metadata = {
        "runtime_status": status,
        "status_updated_at": datetime.utcnow().isoformat() + "+00:00",
        "has_interrupt": has_interrupt,
    }
    if error_message:
        metadata["last_error_message"] = str(error_message)[:1000]
    elif status in ("running", "completed", "idle"):
        metadata["last_error_message"] = ""
    return metadata


async def update_thread_runtime_status(
    conv_repo: ConversationRepository,
    thread_id: str,
    status: str,
    *,
    has_interrupt: bool = False,
    error_message: str | None = None,
    extra_metadata: dict | None = None,
) -> None:
    metadata = runtime_status_metadata(
        status,
        has_interrupt=has_interrupt,
        error_message=error_message,
    )
    if extra_metadata:
        metadata.update(extra_metadata)
    await conv_repo.update_conversation(
        thread_id=thread_id,
        metadata=metadata,
    )


async def get_langgraph_messages(config_dict, graph):
    state = await graph.aget_state(config_dict)

    if not state or not state.values:
        logger.warning("No state found in LangGraph")
        return None

    return state.values.get("messages", [])


async def get_existing_message_ids(conv_repo: ConversationRepository, thread_id: str) -> set[str]:
    existing_messages = await conv_repo.get_messages_by_thread_id(thread_id)
    return {
        msg.extra_metadata["id"]
        for msg in existing_messages
        if msg.extra_metadata and "id" in msg.extra_metadata and isinstance(msg.extra_metadata["id"], str)
    }


async def save_ai_message(conv_repo: ConversationRepository, thread_id: str, msg_dict: dict) -> None:
    content = msg_dict.get("content", "")
    tool_calls_data = msg_dict.get("tool_calls", [])

    ai_msg = await conv_repo.add_message_by_thread_id(
        thread_id=thread_id,
        role="assistant",
        content=content,
        message_type="text",
        extra_metadata=msg_dict,
    )

    if ai_msg and tool_calls_data:
        for tc in tool_calls_data:
            await conv_repo.add_tool_call(
                message_id=ai_msg.id,
                tool_name=tc.get("name", "unknown"),
                tool_input=tc.get("args", {}),
                status="pending",
                langgraph_tool_call_id=tc.get("id"),
            )


async def save_tool_message(conv_repo: ConversationRepository, msg_dict: dict) -> None:
    tool_call_id = msg_dict.get("tool_call_id")
    content = msg_dict.get("content", "")

    if not tool_call_id:
        return

    if isinstance(content, list):
        tool_output = json.dumps(content) if content else ""
    else:
        tool_output = str(content)

    await conv_repo.update_tool_call_output(
        langgraph_tool_call_id=tool_call_id,
        tool_output=tool_output,
        status="success",
    )


async def save_partial_message(
    conv_repo: ConversationRepository,
    thread_id: str,
    full_msg=None,
    error_message: str | None = None,
    error_type: str = "interrupted",
):
    try:
        extra_metadata = {
            "error_type": error_type,
            "is_error": True,
            "error_message": error_message or f"发生错误: {error_type}",
        }
        if full_msg:
            msg_dict = full_msg.model_dump() if hasattr(full_msg, "model_dump") else {}
            content = full_msg.content if hasattr(full_msg, "content") else str(full_msg)
            extra_metadata = msg_dict | extra_metadata
        else:
            content = ""

        return await conv_repo.add_message_by_thread_id(
            thread_id=thread_id,
            role="assistant",
            content=content,
            message_type="text",
            extra_metadata=extra_metadata,
        )

    except Exception as e:
        logger.error(f"Error saving message: {e}")
        logger.error(traceback.format_exc())
        return None


async def save_partial_assistant_message(
    conv_repo: ConversationRepository,
    thread_id: str,
    content: str,
    *,
    stop_reason: str,
):
    text = str(content or "")
    if not text.strip():
        return None
    try:
        return await conv_repo.add_message_by_thread_id(
            thread_id=thread_id,
            role="assistant",
            content=text,
            message_type="text",
            extra_metadata={
                "is_partial": True,
                "stop_reason": stop_reason,
            },
        )
    except Exception as e:
        logger.error(f"Error saving partial assistant message: {e}")
        logger.error(traceback.format_exc())
        return None


async def save_messages_from_langgraph_state(
    graph,
    thread_id: str,
    conv_repo: ConversationRepository,
    config_dict: dict,
    excluded_ai_names: set[str] | None = None,
) -> None:
    try:
        messages = await get_langgraph_messages(config_dict, graph)
        if messages is None:
            return

        existing_ids = await get_existing_message_ids(conv_repo, thread_id)

        for msg in messages:
            msg_dict = msg.model_dump() if hasattr(msg, "model_dump") else {}
            msg_type = msg_dict.get("type", "unknown")

            if msg_type == "human" or getattr(msg, "id", None) in existing_ids:
                continue

            if msg_type == "ai":
                msg_name = str(msg_dict.get("name") or "").strip()
                if excluded_ai_names and msg_name and msg_name in excluded_ai_names:
                    continue
                await save_ai_message(conv_repo, thread_id, msg_dict)
            elif msg_type == "tool":
                await save_tool_message(conv_repo, msg_dict)

    except Exception as e:
        logger.error(f"Error saving messages from LangGraph state: {e}")
        logger.error(traceback.format_exc())
