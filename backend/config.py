from __future__ import annotations

import os
import socket
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path


def _has_resolvable_hostname(url: str) -> bool:
    if not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False
        socket.getaddrinfo(hostname, None)
        return True
    except Exception:
        return False


def _public_url_default() -> str:
    raw = os.getenv("BACKEND_PUBLIC_URL")
    if raw and _has_resolvable_hostname(raw):
        return raw
    return "http://127.0.0.1:8010"


def _split_paths(raw_value: str | None) -> list[Path]:
    if not raw_value:
        return []
    normalized = raw_value
    for separator in [";", ",", "|"]:
        normalized = normalized.replace(separator, ";")
    parts = [part.strip() for part in normalized.split(";") if part.strip()]
    return [Path(part).expanduser().resolve() for part in parts]


def _default_allowed_roots() -> list[Path]:
    home = Path.home()
    candidates = [home / "Desktop", home / "Projects", home / "Desktop" / "AIProjects"]
    resolved = [candidate.resolve() for candidate in candidates if candidate.exists()]
    return resolved or [home.resolve()]


@dataclass(slots=True)
class Settings:
    app_name: str = "AI PC Agent"
    backend_host: str = field(default_factory=lambda: os.getenv("BACKEND_HOST", "0.0.0.0"))
    backend_port: int = field(default_factory=lambda: int(os.getenv("BACKEND_PORT", "8010")))
    backend_public_url: str = field(default_factory=_public_url_default)
    frontend_access_token: str = field(default_factory=lambda: os.getenv("FRONTEND_ACCESS_TOKEN", "change-me-panel-token"))
    agent_token: str = field(default_factory=lambda: os.getenv("AGENT_TOKEN", "change-me-agent-token"))
    frontend_cookie_name: str = field(default_factory=lambda: os.getenv("FRONTEND_COOKIE_NAME", "ai_agent_session"))
    session_ttl_minutes: int = field(default_factory=lambda: int(os.getenv("SESSION_TTL_MINUTES", "720")))
    allowed_workspace_roots: list[Path] = field(
        default_factory=lambda: _split_paths(os.getenv("ALLOWED_WORKSPACE_ROOTS")) or _default_allowed_roots()
    )
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    @property
    def frontend_url(self) -> str:
        if self.backend_public_url:
            return self.backend_public_url.rstrip("/")
        if self.backend_host in {"0.0.0.0", "::", "[::]"}:
            return f"http://127.0.0.1:{self.backend_port}"
        return f"http://{self.backend_host}:{self.backend_port}"

    @property
    def websocket_agent_url(self) -> str:
        if self.backend_public_url:
            ws_scheme = "wss" if self.backend_public_url.startswith("https://") else "ws"
            return f"{ws_scheme}://{self.backend_public_url.replace('http://', '').replace('https://', '')}/ws/agent"
        if self.backend_host in {"0.0.0.0", "::", "[::]"}:
            return f"ws://127.0.0.1:{self.backend_port}/ws/agent"
        return f"ws://{self.backend_host}:{self.backend_port}/ws/agent"


def load_settings() -> Settings:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass
    settings = Settings()
    settings.allowed_workspace_roots = [root.resolve() for root in settings.allowed_workspace_roots]
    return settings
