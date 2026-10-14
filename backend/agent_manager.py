from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

try:
    from backend.config import Settings
    from backend.models import ApprovalRecord, ApprovalSummary, TaskRecord, TaskStatus, TaskSummary, utc_now
except ImportError:  # pragma: no cover - fallback for direct script execution
    from config import Settings
    from models import ApprovalRecord, ApprovalSummary, TaskRecord, TaskStatus, TaskSummary, utc_now


logger = logging.getLogger(__name__)


def _event_text(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "message":
        return payload.get("content", "")
    if event_type == "status":
        return payload.get("text", "")
    if event_type == "approval_request":
        return f"Onay istendi: {payload.get('command', '')}"
    if event_type == "task_update":
        return payload.get("summary", "")
    return json.dumps(payload, ensure_ascii=False)


class AgentManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = asyncio.Lock()
        self._frontends: dict[str, set[WebSocket]] = {}
        self._agent_ws: WebSocket | None = None
        self._agent_name: str | None = None
        self._tasks: dict[str, TaskRecord] = {}
        self._approvals: dict[str, ApprovalRecord] = {}
        self._recent_events: deque[str] = deque(maxlen=100)

    @property
    def agent_connected(self) -> bool:
        return self._agent_ws is not None

    @property
    def agent_name(self) -> str | None:
        return self._agent_name

    async def register_frontend(self, session_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._frontends.setdefault(session_id, set()).add(websocket)

    async def unregister_frontend(self, session_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self._frontends.get(session_id)
            if sockets and websocket in sockets:
                sockets.remove(websocket)
            if sockets is not None and not sockets:
                self._frontends.pop(session_id, None)

    async def register_agent(self, websocket: WebSocket, agent_name: str | None) -> None:
        async with self._lock:
            existing = self._agent_ws
            if existing is not None and existing is not websocket:
                try:
                    await existing.close()
                except Exception:
                    pass
            self._agent_ws = websocket
            self._agent_name = agent_name or "PC Agent"
        await self.broadcast({"type": "status", "payload": {"level": "success", "text": f"Agent bağlandı: {self._agent_name}"}})

    async def unregister_agent(self, websocket: WebSocket) -> None:
        async with self._lock:
            if self._agent_ws is websocket:
                self._agent_ws = None
                self._agent_name = None
        await self.broadcast({"type": "status", "payload": {"level": "warning", "text": "Agent bağlantısı kesildi"}})

    async def broadcast(self, payload: dict[str, Any], session_id: str | None = None) -> None:
        message = json.dumps(payload, ensure_ascii=False)
        async with self._lock:
            if session_id is None:
                targets = [socket for sockets in self._frontends.values() for socket in sockets]
            else:
                targets = list(self._frontends.get(session_id, set()))

        stale: list[tuple[str, WebSocket]] = []
        for socket in targets:
            try:
                await socket.send_text(message)
            except Exception:
                for sid, sockets in self._frontends.items():
                    if socket in sockets:
                        stale.append((sid, socket))
                continue

        if stale:
            async with self._lock:
                for session, socket in stale:
                    sockets = self._frontends.get(session)
                    if sockets and socket in sockets:
                        sockets.remove(socket)

    async def send_to_agent(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            agent_ws = self._agent_ws
        if agent_ws is None:
            raise RuntimeError("Agent is not connected")
        await agent_ws.send_text(json.dumps(payload, ensure_ascii=False))

    async def create_task(self, session_id: str, message: str) -> TaskRecord:
        task = TaskRecord(task_id=str(uuid4()), session_id=session_id, message=message, status=TaskStatus.queued)
        self._tasks[task.task_id] = task
        self._append_event(f"Yeni görev: {message}")
        await self.broadcast({"type": "task_update", "payload": self.task_to_payload(task)}, session_id=session_id)
        if not self.agent_connected:
            task.status = TaskStatus.failed
            task.summary = "Agent bağlı olmadığı için görev başlatılamadı"
            task.updated_at = utc_now()
            await self.broadcast({"type": "status", "payload": {"level": "error", "text": task.summary}}, session_id=session_id)
            return task
        task.status = TaskStatus.running
        task.updated_at = utc_now()
        await self.send_to_agent({"type": "task", "payload": {"task": self.task_to_payload(task)}})
        await self.broadcast({"type": "task_update", "payload": self.task_to_payload(task)}, session_id=session_id)
        return task

    async def handle_frontend_message(self, session_id: str, payload: dict[str, Any]) -> None:
        message_type = payload.get("type")
        body = payload.get("payload", payload)
        if message_type == "chat_message":
            text = str(body.get("message", "")).strip()
            if not text:
                return
            await self.create_task(session_id, text)
            return
        if message_type == "approval_decision":
            approval_id = str(body.get("approval_id", "")).strip()
            approved = bool(body.get("approved", False))
            note = body.get("note")
            await self.handle_approval_decision(session_id, approval_id, approved, note)
            return
        if message_type == "refresh_state":
            await self.push_state(session_id)
            return

    async def handle_agent_message(self, payload: dict[str, Any]) -> None:
        message_type = payload.get("type")
        body = payload.get("payload", payload)
        if message_type == "hello":
            await self.broadcast({"type": "status", "payload": {"level": "success", "text": body.get("message", "Agent hazır")}})
            return
        if message_type == "status":
            await self.broadcast({"type": "status", "payload": body})
            return
        if message_type == "message":
            session_id = body.get("session_id")
            await self.broadcast({"type": "message", "payload": body}, session_id=session_id)
            self._append_event(_event_text(message_type, body))
            return
        if message_type == "task_update":
            task_id = body.get("task_id")
            task = self._tasks.get(task_id)
            if task:
                status_value = body.get("status")
                if status_value:
                    task.status = TaskStatus(status_value)
                task.summary = body.get("summary", task.summary)
                details = body.get("details")
                if isinstance(details, list):
                    task.details = [str(item) for item in details]
                task.updated_at = utc_now()
                await self.broadcast({"type": "task_update", "payload": self.task_to_payload(task)}, session_id=task.session_id)
            self._append_event(_event_text(message_type, body))
            return
        if message_type == "approval_request":
            approval = ApprovalRecord(
                approval_id=str(body.get("approval_id") or uuid4()),
                task_id=str(body.get("task_id", "")),
                session_id=str(body.get("session_id", "")),
                command=str(body.get("command", "")),
                risk=str(body.get("risk", "medium")),
                reason=str(body.get("reason", "")),
            )
            self._approvals[approval.approval_id] = approval
            await self.broadcast({"type": "approval_request", "payload": self.approval_to_payload(approval)}, session_id=approval.session_id)
            task = self._tasks.get(approval.task_id)
            if task:
                task.status = TaskStatus.waiting_approval
                task.updated_at = utc_now()
                await self.broadcast({"type": "task_update", "payload": self.task_to_payload(task)}, session_id=task.session_id)
            self._append_event(_event_text(message_type, body))
            return
        if message_type == "task_finished":
            task_id = body.get("task_id")
            task = self._tasks.get(task_id)
            if task:
                task.status = TaskStatus(body.get("status", "completed"))
                task.summary = str(body.get("summary", task.summary))
                details = body.get("details")
                if isinstance(details, list):
                    task.details = [str(item) for item in details]
                task.updated_at = utc_now()
                final_payload = self.task_to_payload(task)
                await self.broadcast({"type": "task_update", "payload": final_payload}, session_id=task.session_id)
                await self.broadcast({"type": "task_finished", "payload": final_payload}, session_id=task.session_id)
            self._append_event(_event_text(message_type, body))
            return
        if message_type == "error":
            await self.broadcast({"type": "status", "payload": {"level": "error", "text": str(body.get("message", "Agent error"))}})
            self._append_event(_event_text(message_type, body))

    async def handle_approval_decision(self, session_id: str, approval_id: str, approved: bool, note: str | None) -> None:
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise RuntimeError("Approval not found")
        if approval.session_id != session_id:
            raise RuntimeError("Approval does not belong to this session")
        approval.approved = approved
        approval.note = note
        approval.updated_at = utc_now()
        await self.send_to_agent(
            {
                "type": "approval_decision",
                "payload": {
                    "approval_id": approval.approval_id,
                    "task_id": approval.task_id,
                    "approved": approved,
                    "note": note,
                },
            }
        )
        await self.broadcast({"type": "approval_resolved", "payload": self.approval_to_payload(approval)}, session_id=session_id)

    async def push_state(self, session_id: str) -> None:
        await self.broadcast({"type": "state", "payload": self.state_payload(session_id)}, session_id=session_id)

    def state_payload(self, session_id: str | None = None) -> dict[str, Any]:
        tasks = [self.task_to_payload(task) for task in self._tasks.values() if session_id is None or task.session_id == session_id]
        approvals = [self.approval_to_payload(approval) for approval in self._approvals.values() if session_id is None or approval.session_id == session_id]
        return {
            "agent_connected": self.agent_connected,
            "agent_name": self.agent_name,
            "tasks": tasks,
            "approvals": approvals,
            "recent_events": list(self._recent_events),
        }

    def task_to_payload(self, task: TaskRecord) -> dict[str, Any]:
        return {
            "task_id": task.task_id,
            "session_id": task.session_id,
            "message": task.message,
            "status": task.status.value,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
            "summary": task.summary,
            "details": list(task.details),
        }

    def approval_to_payload(self, approval: ApprovalRecord) -> dict[str, Any]:
        return {
            "approval_id": approval.approval_id,
            "task_id": approval.task_id,
            "session_id": approval.session_id,
            "command": approval.command,
            "risk": approval.risk,
            "reason": approval.reason,
            "approved": approval.approved,
            "note": approval.note,
            "created_at": approval.created_at.isoformat(),
            "updated_at": approval.updated_at.isoformat(),
        }

    def task_summaries(self, session_id: str) -> list[TaskSummary]:
        return [TaskSummary(**self.task_to_payload(task)) for task in self._tasks.values() if task.session_id == session_id]

    def approval_summaries(self, session_id: str) -> list[ApprovalSummary]:
        return [ApprovalSummary(**self.approval_to_payload(item)) for item in self._approvals.values() if item.session_id == session_id]

    def recent_events(self) -> list[str]:
        return list(self._recent_events)

    def _append_event(self, message: str) -> None:
        if not message:
            return
        stamped = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        self._recent_events.appendleft(stamped)
        logger.info(message)
