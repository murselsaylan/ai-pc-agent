from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    waiting_approval = "waiting_approval"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class LoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    ok: bool = True
    message: str
    session_id: str
    expires_at: datetime


class LogoutResponse(BaseModel):
    ok: bool = True
    message: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ApprovalDecisionRequest(BaseModel):
    approval_id: str = Field(min_length=1, max_length=128)
    approved: bool
    note: str | None = Field(default=None, max_length=500)


class TaskSummary(BaseModel):
    task_id: str
    message: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    summary: str = ""
    details: list[str] = Field(default_factory=list)


class ApprovalSummary(BaseModel):
    approval_id: str
    task_id: str
    command: str
    risk: str
    reason: str
    approved: bool | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime


class StateResponse(BaseModel):
    ok: bool = True
    agent_connected: bool
    agent_name: str | None
    tasks: list[TaskSummary]
    approvals: list[ApprovalSummary]
    recent_events: list[str]


class WebSocketEnvelope(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "payload" in value:
            return value
        msg_type = value.get("type")
        if not msg_type:
            return value
        payload = {key: item for key, item in value.items() if key != "type"}
        return {"type": msg_type, "payload": payload}


@dataclass(slots=True)
class FrontendSession:
    session_id: str
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime = field(default_factory=utc_now)
    last_seen_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    session_id: str
    message: str
    status: TaskStatus = TaskStatus.queued
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    summary: str = ""
    details: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ApprovalRecord:
    approval_id: str
    task_id: str
    session_id: str
    command: str
    risk: str
    reason: str
    approved: bool | None = None
    note: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
