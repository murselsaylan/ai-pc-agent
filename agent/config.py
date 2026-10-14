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


def _backend_ws_url_default() -> str:
    raw = os.getenv("BACKEND_WS_URL")
    if raw and _has_resolvable_hostname(raw):
        return raw
    return "ws://127.0.0.1:8010/ws/agent"


def _split_paths(raw_value: str | None) -> list[Path]:
    if not raw_value:
        return []
    normalized = raw_value
    for separator in [";", ",", "|"]:
        normalized = normalized.replace(separator, ";")
    return [Path(item.strip()).expanduser().resolve() for item in normalized.split(";") if item.strip()]


def _default_roots() -> list[Path]:
    home = Path.home()
    candidates = [home / "Desktop", home / "Projects", home / "Desktop" / "AIProjects"]
    existing = [candidate.resolve() for candidate in candidates if candidate.exists()]
    return existing or [home.resolve()]


@dataclass(slots=True)
class AgentSettings:
    backend_ws_url: str = field(default_factory=_backend_ws_url_default)
    agent_token: str = field(default_factory=lambda: os.getenv("AGENT_TOKEN", "change-me-agent-token"))
    agent_name: str = field(default_factory=lambda: os.getenv("AGENT_NAME", os.getenv("COMPUTERNAME", "My AI PC")))
    allowed_workspace_roots: list[Path] = field(default_factory=lambda: _split_paths(os.getenv("ALLOWED_WORKSPACE_ROOTS")) or _default_roots())
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))
    command_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("COMMAND_TIMEOUT_SECONDS", "120")))


def load_settings() -> AgentSettings:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass
    settings = AgentSettings()
    settings.allowed_workspace_roots = [root.resolve() for root in settings.allowed_workspace_roots]
    return settings
