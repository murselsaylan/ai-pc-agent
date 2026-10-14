from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

try:
    from backend.agent_manager import AgentManager
    from backend.auth import AuthService
    from backend.config import load_settings
    from backend.models import ApprovalDecisionRequest, ChatRequest, LogoutResponse, StateResponse
    from backend.websocket import agent_socket_handler, frontend_socket_handler
except ImportError:  # pragma: no cover - fallback for direct script execution
    from agent_manager import AgentManager
    from auth import AuthService
    from config import load_settings
    from models import ApprovalDecisionRequest, ChatRequest, LogoutResponse, StateResponse
    from websocket import agent_socket_handler, frontend_socket_handler


settings = load_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dir = (Path(__file__).resolve().parent.parent / "frontend").resolve()
if frontend_dir.exists():
    app.mount("/frontend", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

auth_service = AuthService(settings)
agent_manager = AgentManager(settings)


@app.on_event("startup")
async def startup_event() -> None:
    logging.getLogger(__name__).info("AI PC Agent backend starting")


@app.get("/")
async def root() -> FileResponse:
    index_path = frontend_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)


@app.get("/api/health")
async def health() -> dict[str, object]:
    return {"ok": True, "agent_connected": agent_manager.agent_connected, "agent_name": agent_manager.agent_name, "active_sessions": auth_service.active_session_count}


@app.get("/api/state")
async def get_state(request: Request) -> StateResponse:
    session = auth_service.session_from_request(request)
    payload = agent_manager.state_payload(session.session_id)
    return StateResponse(
        agent_connected=payload["agent_connected"],
        agent_name=payload["agent_name"],
        tasks=agent_manager.task_summaries(session.session_id),
        approvals=agent_manager.approval_summaries(session.session_id),
        recent_events=payload["recent_events"],
    )


@app.post("/api/auth/login")
async def login(request: Request) -> JSONResponse:
    form = await request.json()
    token = str(form.get("token", "")).strip()
    login_response = auth_service.login(token)
    response = JSONResponse(login_response.model_dump(mode="json"))
    response.set_cookie(
        key=settings.frontend_cookie_name,
        value=login_response.session_id,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=settings.session_ttl_minutes * 60,
        path="/",
    )
    return response


@app.post("/api/auth/logout")
async def logout(request: Request) -> LogoutResponse:
    session_id = request.cookies.get(settings.frontend_cookie_name)
    auth_service.logout(session_id)
    return LogoutResponse(message="Logged out")


@app.post("/api/chat")
async def post_chat(request: Request) -> dict[str, str]:
    session = auth_service.session_from_request(request)
    data = await request.json()
    message = str(data.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message required")
    task = await agent_manager.create_task(session.session_id, message)
    return {"task_id": task.task_id, "status": task.status.value}


@app.post("/api/approval")
async def approval(request: Request) -> dict[str, object]:
    session = auth_service.session_from_request(request)
    data = await request.json()
    approval_payload = ApprovalDecisionRequest.model_validate(data)
    await agent_manager.handle_approval_decision(session.session_id, approval_payload.approval_id, approval_payload.approved, approval_payload.note)
    return {"ok": True}


@app.websocket("/ws/frontend")
async def frontend_socket(websocket: WebSocket) -> None:
    try:
        await frontend_socket_handler(websocket, auth_service, agent_manager)
    except HTTPException as exc:
        await websocket.close(code=4401, reason=exc.detail)


@app.websocket("/ws/agent")
async def agent_socket(websocket: WebSocket) -> None:
    try:
        await agent_socket_handler(websocket, auth_service, agent_manager)
    except HTTPException as exc:
        await websocket.close(code=4401, reason=exc.detail)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.backend_host, port=settings.backend_port, reload=False)
