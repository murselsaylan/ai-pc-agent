from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException, Request, status

try:
    from backend.config import Settings
    from backend.models import FrontendSession, LoginResponse, utc_now
except ImportError:  # pragma: no cover - fallback for direct script execution
    from config import Settings
    from models import FrontendSession, LoginResponse, utc_now


class AuthService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._sessions: dict[str, FrontendSession] = {}

    def _expiry(self) -> datetime:
        return utc_now() + timedelta(minutes=self.settings.session_ttl_minutes)

    def login(self, token: str) -> LoginResponse:
        if not secrets.compare_digest(token, self.settings.frontend_access_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
        session_id = secrets.token_urlsafe(32)
        session = FrontendSession(session_id=session_id, created_at=utc_now(), expires_at=self._expiry(), last_seen_at=utc_now())
        self._sessions[session_id] = session
        return LoginResponse(message="Login successful", session_id=session_id, expires_at=session.expires_at)

    def logout(self, session_id: str | None) -> None:
        if session_id:
            self._sessions.pop(session_id, None)

    def validate_session(self, session_id: str | None) -> FrontendSession:
        if not session_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        session = self._sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session not found")
        if session.expires_at <= utc_now():
            self._sessions.pop(session_id, None)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
        session.last_seen_at = utc_now()
        return session

    def validate_agent_token(self, token: str | None) -> None:
        if not token or not secrets.compare_digest(token, self.settings.agent_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token")

    def session_from_request(self, request: Request) -> FrontendSession:
        session_id = request.cookies.get(self.settings.frontend_cookie_name) or request.query_params.get("session_id")
        return self.validate_session(session_id)

    def prune_expired_sessions(self) -> None:
        now = utc_now()
        for session_id, session in list(self._sessions.items()):
            if session.expires_at <= now:
                self._sessions.pop(session_id, None)

    @property
    def active_session_count(self) -> int:
        self.prune_expired_sessions()
        return len(self._sessions)
