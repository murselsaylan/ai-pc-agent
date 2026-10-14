from pathlib import Path

from start_public import build_public_urls, update_env_file


def test_build_public_urls() -> None:
    public_url, ws_url = build_public_urls("https://abc.ngrok-free.app")
    assert public_url == "https://abc.ngrok-free.app"
    assert ws_url == "wss://abc.ngrok-free.app/ws/agent"


def test_update_env_file(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "BACKEND_PUBLIC_URL=http://127.0.0.1:8010\n"
        "BACKEND_WS_URL=ws://127.0.0.1:8010/ws/agent\n",
        encoding="utf-8",
    )

    update_env_file(env_path, "https://abc.ngrok-free.app")

    text = env_path.read_text(encoding="utf-8")
    assert "BACKEND_PUBLIC_URL=https://abc.ngrok-free.app" in text
    assert "BACKEND_WS_URL=wss://abc.ngrok-free.app/ws/agent" in text
