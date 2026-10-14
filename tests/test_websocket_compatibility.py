import asyncio
import json

from agent.ai import PlannedStep
from agent.config import load_settings
from agent.executor import AgentExecutor, ApprovalGate
from backend.agent_manager import AgentManager
from backend.config import Settings
from backend.models import WebSocketEnvelope, TaskStatus


def test_frontend_chat_message_legacy_shape_is_normalized() -> None:
    envelope = WebSocketEnvelope.model_validate({"type": "chat_message", "message": "merhaba"})
    assert envelope.type == "chat_message"
    assert envelope.payload == {"message": "merhaba"}


def test_frontend_approval_decision_legacy_shape_is_normalized() -> None:
    envelope = WebSocketEnvelope.model_validate({"type": "approval_decision", "approval_id": "abc", "approved": True, "note": "ok"})
    assert envelope.type == "approval_decision"
    assert envelope.payload == {"approval_id": "abc", "approved": True, "note": "ok"}


def test_wrapped_payload_is_preserved() -> None:
    envelope = WebSocketEnvelope.model_validate({"type": "status", "payload": {"text": "agent ready"}})
    assert envelope.type == "status"
    assert envelope.payload == {"text": "agent ready"}


def test_task_finished_event_is_broadcast_to_frontend() -> None:
    async def run_test() -> None:
        manager = AgentManager(Settings())

        class FakeSocket:
            def __init__(self) -> None:
                self.sent: list[str] = []
                self.closed = False

            async def send_text(self, text: str) -> None:
                self.sent.append(text)

            async def close(self) -> None:
                self.closed = True

        frontend = FakeSocket()
        agent = FakeSocket()
        await manager.register_frontend("session-1", frontend)
        await manager.register_agent(agent, "demo")

        task = await manager.create_task("session-1", "List the root folder")
        await manager.handle_agent_message(
            {
                "type": "task_finished",
                "payload": {
                    "task_id": task.task_id,
                    "status": "completed",
                    "summary": "İşlem tamamlandı",
                    "details": ["ok"],
                },
            }
        )

        messages = [json.loads(item) for item in frontend.sent]
        assert any(
            item.get("type") == "task_finished" and item.get("payload", {}).get("summary") == "İşlem tamamlandı"
            for item in messages
        )
        assert manager._tasks[task.task_id].status == TaskStatus.completed

    asyncio.run(run_test())


def test_duplicate_agent_connections_replace_stale_socket() -> None:
    async def run_test() -> None:
        manager = AgentManager(Settings())

        class FakeSocket:
            def __init__(self, name: str) -> None:
                self.name = name
                self.closed = False

            async def close(self) -> None:
                self.closed = True

        old_socket = FakeSocket("old")
        new_socket = FakeSocket("new")

        await manager.register_agent(old_socket, "old-agent")
        await manager.register_agent(new_socket, "new-agent")

        assert manager._agent_ws is new_socket
        assert old_socket.closed is True
        assert manager._agent_name == "new-agent"

    asyncio.run(run_test())


def test_directory_listing_emits_readable_result() -> None:
    async def run_test() -> None:
        settings = load_settings()
        sent: list[dict] = []

        async def send_event(payload):
            sent.append(payload)

        executor = AgentExecutor(settings, send_event, ApprovalGate())
        result = await executor._execute_step(PlannedStep(tool="list_workspace", args={}), {"task_id": "t1", "session_id": "s1"})
        assert isinstance(result, dict)
        assert any(
            item.get("type") == "message"
            and isinstance(item.get("payload", {}).get("content"), str)
            and any(keyword in item.get("payload", {}).get("content", "").lower() for keyword in ["path", "entries", "klasör", "directory"])
            for item in sent
        )

    asyncio.run(run_test())


def test_desktop_listing_uses_requested_root() -> None:
    async def run_test() -> None:
        from pathlib import Path

        settings = load_settings()
        sent: list[dict] = []

        async def send_event(payload):
            sent.append(payload)

        executor = AgentExecutor(settings, send_event, ApprovalGate())
        desktop_root = str(Path.home() / "Desktop")
        result = await executor._execute_step(PlannedStep(tool="list_workspace", args={"root": desktop_root}), {"task_id": "t1", "session_id": "s1"})
        assert isinstance(result, dict)
        assert result.get("roots")
        first_root = result["roots"][0]
        assert first_root.get("path") == desktop_root or first_root.get("path") == str(Path(desktop_root).resolve())
        assert isinstance(first_root.get("entries"), list)
        assert any(
            item.get("type") == "message"
            and isinstance(item.get("payload", {}).get("content"), str)
            and "path:" in item.get("payload", {}).get("content", "").lower()
            for item in sent
        )

    asyncio.run(run_test())


def test_natural_language_desktop_listing_is_recognized() -> None:
    settings = load_settings()
    planner = planner_for_test = __import__("agent.ai", fromlist=["LocalPlanner"]).LocalPlanner(settings)

    prompts = [
        "masaüstündeki klasörleri bana söyle",
        "hangi klasörler var",
        "desktop klasörlerini göster",
    ]

    for prompt in prompts:
        plan = planner.build_plan(prompt)
        assert plan.steps and plan.steps[0].tool == "list_workspace", f"Prompt should list workspace: {prompt!r} -> {plan}"


def test_explicit_commands_bypass_generic_analysis() -> None:
    settings = load_settings()
    planner = __import__("agent.ai", fromlist=["LocalPlanner"]).LocalPlanner(settings)

    prompts = [
        "Masaüstündeki klasörleri listele",
        "README.md oku",
        "desktop klasörlerini göster",
        "kamerayı aç",
        "uygulamayı başlat",
    ]

    for prompt in prompts:
        plan = planner.build_plan(prompt)
        assert plan.steps, f"Explicit command must create a direct action: {prompt!r} -> {plan}"
        assert plan.steps[0].tool != "inspect_project", f"Explicit command should not fall back to generic analysis: {prompt!r} -> {plan}"


def test_generic_chat_prompts_do_not_trigger_workspace_listing() -> None:
    settings = load_settings()
    planner = __import__("agent.ai", fromlist=["LocalPlanner"]).LocalPlanner(settings)

    for prompt in ["merhaba", "naber", "nasılsın", "ne yapabilirsin", "selam"]:
        plan = planner.build_plan(prompt)
        assert not plan.steps, f"Generic conversation should not trigger workspace listing: {prompt!r} -> {plan}"


def test_session_from_request_accepts_query_session_id_fallback() -> None:
    from starlette.requests import Request

    from backend.auth import AuthService
    from backend.config import Settings

    auth = AuthService(Settings())
    session_id = auth.login("demo-panel-token").session_id
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": f"session_id={session_id}".encode(),
        "cookies": {},
    })
    assert auth.session_from_request(request).session_id == session_id


def test_agent_websocket_accepts_before_receive_and_closes_invalid_auth() -> None:
    async def run_test() -> None:
        from backend.auth import AuthService
        from backend.websocket import agent_socket_handler
        from starlette.websockets import WebSocketDisconnect, WebSocketState

        class FakeWebSocket:
            def __init__(self, token: str | None) -> None:
                self.query_params = {"token": token}
                self.accepted = False
                self.closed_code = None
                self.closed_reason = None
                self._state = WebSocketState.CONNECTED

            async def accept(self) -> None:
                self.accepted = True
                self._state = WebSocketState.CONNECTED

            async def close(self, code: int = 1000, reason: str | None = None) -> None:
                self.closed_code = code
                self.closed_reason = reason
                self._state = WebSocketState.DISCONNECTED

            async def receive_text(self) -> str:
                if not self.accepted:
                    raise RuntimeError('WebSocket is not connected. Need to call "accept" first.')
                raise WebSocketDisconnect()

        settings = Settings(agent_token="demo-agent-token")
        auth = AuthService(settings)
        manager = AgentManager(settings)

        valid_socket = FakeWebSocket("demo-agent-token")
        await agent_socket_handler(valid_socket, auth, manager)
        assert valid_socket.accepted is True

        invalid_socket = FakeWebSocket("bad-token")
        await agent_socket_handler(invalid_socket, auth, manager)
        assert invalid_socket.closed_code == 4401
        assert invalid_socket.accepted is False

    asyncio.run(run_test())


def test_camera_launch_is_routed_to_start_program() -> None:
    settings = load_settings()
    planner = __import__("agent.ai", fromlist=["LocalPlanner"]).LocalPlanner(settings)

    plan = planner.build_plan("kamerayı aç")
    assert plan.steps and plan.steps[0].tool == "start_program"
    assert "camera" in str(plan.steps[0].args.get("command", "")).lower()


def test_camera_prompt_routes_to_vision_tool() -> None:
    settings = load_settings()
    planner = __import__("agent.ai", fromlist=["LocalPlanner"]).LocalPlanner(settings)

    plan = planner.build_plan("kamerayı aç ve ne gördüğünü söyle")
    assert plan.steps and plan.steps[0].tool == "capture_and_analyze_camera"
    assert "gördüğünü" in plan.summary.lower() or "görüntü" in plan.summary.lower()


def test_explicit_camera_prompt_prefers_local_planner_over_bad_gemini() -> None:
    from agent.ai import PlanResult, Planner, PlannedStep

    settings = load_settings()
    planner = Planner(settings)

    class FakeGemini:
        available = True

        def build_plan(self, prompt: str, workspace_roots: list[str]) -> PlanResult:
            return PlanResult(
                summary="bad",
                steps=[PlannedStep(tool="search_files", args={"query": "README.md"}, explanation="wrong")],
            )

    planner.gemini = FakeGemini()
    plan = planner.build_plan("kamerayı aç ve ne gördüğünü söyle", ["C:/tmp"])
    assert plan.steps and plan.steps[0].tool == "capture_and_analyze_camera"
