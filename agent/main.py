from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse

import websockets

try:
    from agent.config import load_settings
    from agent.executor import AgentExecutor, ApprovalGate
except ImportError:  # pragma: no cover - fallback for direct script execution
    from config import load_settings
    from executor import AgentExecutor, ApprovalGate


settings = load_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


class AgentRuntime:
    def __init__(self, websocket: websockets.WebSocketClientProtocol):
        self.websocket = websocket
        self.approval_gate = ApprovalGate()

    async def send_event(self, payload: dict[str, object]) -> None:
        await self.websocket.send(json.dumps(payload, ensure_ascii=False))


async def run_agent() -> None:
    while True:
        uri = f"{settings.backend_ws_url}?token={urllib.parse.quote(settings.agent_token)}&agent_name={urllib.parse.quote(settings.agent_name)}"
        try:
            async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as websocket:
                runtime = AgentRuntime(websocket)
                executor = AgentExecutor(settings, runtime.send_event, runtime.approval_gate)
                await runtime.send_event({"type": "hello", "payload": {"message": f"Agent hazır: {settings.agent_name}"}})
                await runtime.send_event({"type": "status", "payload": {"level": "success", "text": "Backend bağlantısı kuruldu", "agent_name": settings.agent_name}})
                async for raw_message in websocket:
                    payload = json.loads(raw_message)
                    message_type = payload.get("type")
                    body = payload.get("payload", {})
                    if message_type == "task":
                        asyncio.create_task(executor.handle_task(body["task"]))
                        continue
                    if message_type == "approval_decision":
                        runtime.approval_gate.resolve(body["approval_id"], body)
                        continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Agent connection failed: %s", exc)
            await asyncio.sleep(3)


def main() -> None:
    asyncio.run(run_agent())


if __name__ == "__main__":
    main()
