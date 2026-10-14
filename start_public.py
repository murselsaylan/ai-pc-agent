from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from pyngrok import conf, ngrok

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"


def build_public_urls(public_url: str) -> tuple[str, str]:
    public_url = public_url.strip().rstrip("/")
    if not public_url:
        raise ValueError("Public URL boş olamaz")
    ws_url = public_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/agent"
    return public_url, ws_url


def update_env_file(env_path: Path, public_url: str) -> None:
    public_url, ws_url = build_public_urls(public_url)
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = text.splitlines()
    mapping = {}
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            mapping[key.strip()] = value.strip()

    mapping["BACKEND_PUBLIC_URL"] = public_url
    mapping["BACKEND_WS_URL"] = ws_url

    new_lines = []
    seen = set()
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            key, _ = line.split("=", 1)
            if key.strip() in {"BACKEND_PUBLIC_URL", "BACKEND_WS_URL"}:
                new_lines.append(f"{key.strip()}={mapping[key.strip()]}")
                seen.add(key.strip())
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    for key in ["BACKEND_PUBLIC_URL", "BACKEND_WS_URL"]:
        if key not in seen:
            new_lines.append(f"{key}={mapping[key]}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def ensure_ngrok_config() -> None:
    conf.get_default().region = "us"
    conf.get_default().authtoken = os.getenv("NGROK_AUTHTOKEN")


def start_tunnel(port: int = 8010) -> str:
    ensure_ngrok_config()
    try:
        tunnel = ngrok.connect(port, "http")
        return tunnel.public_url
    except Exception as exc:
        raise RuntimeError(f"ngrok başlatılamadı: {exc}") from exc


def start_backend_and_agent() -> str:
    backend_path = PROJECT_ROOT / "backend" / "main.py"
    agent_path = PROJECT_ROOT / "agent" / "main.py"

    if not backend_path.exists() or not agent_path.exists():
        raise FileNotFoundError("backend/main.py veya agent/main.py bulunamadı")

    public_url = start_tunnel(8010)
    update_env_file(ENV_PATH, public_url)

    backend_cmd = [sys.executable, str(backend_path)]
    agent_cmd = [sys.executable, str(agent_path)]

    with open(PROJECT_ROOT / "logs" / "backend.log", "ab") as backend_log, open(PROJECT_ROOT / "logs" / "agent.log", "ab") as agent_log:
        subprocess.Popen(backend_cmd, cwd=str(PROJECT_ROOT / "backend"), stdout=backend_log, stderr=backend_log, shell=False)
        time.sleep(2)
        subprocess.Popen(agent_cmd, cwd=str(PROJECT_ROOT / "agent"), stdout=agent_log, stderr=agent_log, shell=False)

    print(f"\nPublic URL: {public_url}")
    print(f"Panel: {public_url}")
    print(f"Token: demo-panel-token")
    print("\nAçık tut: ngrok bağlantısı çalışırken uygulama erişilebilir olur.")
    return public_url


def main() -> None:
    Path(PROJECT_ROOT / "logs").mkdir(exist_ok=True)
    try:
        start_backend_and_agent()
    except KeyboardInterrupt:
        print("Durduruldu.")


if __name__ == "__main__":
    main()
