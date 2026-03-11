from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.services.interrupt_protocol import (  # noqa: E402
    ApprovalResumePayload,
    approval_resume_is_approved,
    normalize_approval_interrupt_info,
    parse_approval_resume_payload,
)


class FakeInterruptEnvelope:
    def __init__(self, value):
        self.value = value


def test_normalize_approval_interrupt_info_unwraps_interrupt_value():
    interrupt_info = normalize_approval_interrupt_info(
        FakeInterruptEnvelope(
            {
                "question": "是否批准执行 SQL？",
                "operation": "db_execute_query",
                "allowed_decisions": ["approve", "reject", "approve", "unknown"],
            }
        )
    )

    assert interrupt_info.kind == "approval"
    assert interrupt_info.question == "是否批准执行 SQL？"
    assert interrupt_info.operation == "db_execute_query"
    assert interrupt_info.allowed_decisions == ["approve", "reject"]


def test_parse_approval_resume_payload_supports_edit_and_approval_flags():
    payload = parse_approval_resume_payload(
        {
            "kind": "approval",
            "decision": "edit",
            "edited_text": "改成只查近 30 天数据",
        }
    )

    assert payload == ApprovalResumePayload(
        decision="edit",
        edited_text="改成只查近 30 天数据",
    )
    assert approval_resume_is_approved(payload.to_payload()) is True
    assert approval_resume_is_approved({"kind": "approval", "decision": "reject"}) is False
