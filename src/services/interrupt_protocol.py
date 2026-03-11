from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ApprovalDecision = Literal["approve", "reject", "edit"]
DEFAULT_APPROVAL_DECISIONS: list[ApprovalDecision] = ["approve", "reject", "edit"]


class ApprovalInterruptInfo(BaseModel):
    kind: Literal["approval"] = "approval"
    question: str = "是否批准以下操作？"
    operation: str = "需要人工审批的操作"
    allowed_decisions: list[ApprovalDecision] = Field(default_factory=lambda: list(DEFAULT_APPROVAL_DECISIONS))

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump()


class ApprovalResumePayload(BaseModel):
    kind: Literal["approval"] = "approval"
    decision: ApprovalDecision
    edited_text: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {"kind": self.kind, "decision": self.decision}
        if self.decision == "edit":
            payload["edited_text"] = self.edited_text or ""
        return payload

    @property
    def is_approved(self) -> bool:
        return self.decision in {"approve", "edit"}


def normalize_approval_interrupt_info(raw_interrupt: Any) -> ApprovalInterruptInfo:
    payload = _coerce_interrupt_payload(raw_interrupt)
    return ApprovalInterruptInfo(
        question=str(payload.get("question") or "是否批准以下操作？"),
        operation=str(payload.get("operation") or "需要人工审批的操作"),
        allowed_decisions=_normalize_allowed_decisions(payload.get("allowed_decisions")),
    )


def parse_approval_resume_payload(raw_payload: Any) -> ApprovalResumePayload:
    payload = _coerce_interrupt_payload(raw_payload)
    if not isinstance(payload, dict):
        raise TypeError("approval resume payload must be a dict")
    return ApprovalResumePayload.model_validate(payload)


def approval_resume_is_approved(raw_payload: Any) -> bool:
    return parse_approval_resume_payload(raw_payload).is_approved


def _coerce_interrupt_payload(raw_payload: Any) -> Any:
    if hasattr(raw_payload, "value"):
        return getattr(raw_payload, "value")
    if isinstance(raw_payload, BaseModel):
        return raw_payload.model_dump(exclude_none=True)
    if isinstance(raw_payload, dict):
        return raw_payload

    payload: dict[str, Any] = {}
    for field_name in ("kind", "question", "operation", "allowed_decisions", "decision", "edited_text"):
        if hasattr(raw_payload, field_name):
            payload[field_name] = getattr(raw_payload, field_name)
    return payload or raw_payload


def _normalize_allowed_decisions(raw_decisions: Any) -> list[ApprovalDecision]:
    if not isinstance(raw_decisions, list):
        return list(DEFAULT_APPROVAL_DECISIONS)

    normalized: list[ApprovalDecision] = []
    for decision in raw_decisions:
        text = str(decision).strip().lower()
        if text in {"approve", "reject", "edit"} and text not in normalized:
            normalized.append(text)  # type: ignore[arg-type]

    return normalized or list(DEFAULT_APPROVAL_DECISIONS)
