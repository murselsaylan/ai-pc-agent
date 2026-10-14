from __future__ import annotations

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

try:
    from backend.agent_manager import AgentManager
    from backend.auth import AuthService
    from backend.models import WebSocketEnvelope
except ImportError:  # pragma: no cover - fallback for direct script execution
    from agent_manager import AgentManager
    from auth import AuthService
    from models import WebSocketEnvelope


async def frontend_socket_handler(websocket: WebSocket, auth: AuthService, manager: AgentManager) -> None:
    session_id = websocket.cookies.get(auth.settings.frontend_cookie_name) or websocket.query_params.get("session_id")
    try:
        session = auth.validate_session(session_id)
    except Exception as exc:
        await websocket.close(code=4401, reason=getattr(exc, "detail", "Authentication required"))
        return
    await websocket.accept()
    await manager.register_frontend(session.session_id, websocket)
    await websocket.send_json({"type": "state", "payload": manager.state_payload(session.session_id)})
    try:
        while True:
            raw_message = await websocket.receive_text()
            envelope = WebSocketEnvelope.model_validate_json(raw_message)
            await manager.handle_frontend_message(session.session_id, envelope.model_dump())
    except WebSocketDisconnect:
        await manager.unregister_frontend(session.session_id, websocket)
    except Exception:
        await manager.unregister_frontend(session.session_id, websocket)
        raise


async def agent_socket_handler(websocket: WebSocket, auth: AuthService, manager: AgentManager) -> None:
    token = websocket.query_params.get("token")
    agent_name = websocket.query_params.get("agent_name")
    try:
        auth.validate_agent_token(token)
    except Exception as exc:
        await websocket.close(code=4401, reason=getattr(exc, "detail", "Authentication required"))
        return

    try:
        await websocket.accept()
    except Exception:
        return

    try:
        await manager.register_agent(websocket, agent_name)
    except Exception:
        await websocket.close(code=1011, reason="Agent registration failed")
        return

    try:
        while True:
            raw_message = await websocket.receive_text()
            envelope = WebSocketEnvelope.model_validate_json(raw_message)
            await manager.handle_agent_message(envelope.model_dump())
    except WebSocketDisconnect:
        await manager.unregister_agent(websocket)
    except RuntimeError:
        await manager.unregister_agent(websocket)
    except Exception:
        await manager.unregister_agent(websocket)
        raise
