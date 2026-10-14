from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

try:
    from agent.ai import Planner, PlannedStep, PlanResult
    from agent.config import AgentSettings
    from agent.filesystem import FileSystemToolset
    from agent.security import SecurityPolicy
    from agent.terminal import TerminalToolset
except ImportError:  # pragma: no cover - fallback for direct script execution
    from ai import Planner, PlannedStep, PlanResult
    from config import AgentSettings
    from filesystem import FileSystemToolset
    from security import SecurityPolicy
    from terminal import TerminalToolset


SendEvent = Callable[[dict[str, Any]], Awaitable[None]]


class ApprovalGate:
    def __init__(self) -> None:
        self._waiters: dict[str, asyncio.Future[dict[str, Any]]] = {}

    def create(self, approval_id: str) -> asyncio.Future[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._waiters[approval_id] = future
        return future

    def resolve(self, approval_id: str, payload: dict[str, Any]) -> None:
        future = self._waiters.pop(approval_id, None)
        if future and not future.done():
            future.set_result(payload)


class AgentExecutor:
    def __init__(self, settings: AgentSettings, send_event: SendEvent, approval_gate: ApprovalGate):
        self.settings = settings
        self.send_event = send_event
        self.approval_gate = approval_gate
        self.security = SecurityPolicy(settings.allowed_workspace_roots)
        self.filesystem = FileSystemToolset(self.security)
        self.terminal = TerminalToolset()
        self.planner = Planner(settings)

    async def handle_task(self, task: dict[str, Any]) -> None:
        task_id = task["task_id"]
        session_id = task["session_id"]
        prompt = task["message"]
        await self.send_event({"type": "status", "payload": {"level": "info", "text": "Görev alındı", "task_id": task_id, "session_id": session_id}})
        plan = self.planner.build_plan(prompt, [str(root) for root in self.settings.allowed_workspace_roots])
        details = [plan.summary] if plan.summary else []
        await self.send_event({"type": "task_update", "payload": {"task_id": task_id, "status": "running", "summary": plan.summary, "details": details, "session_id": session_id}})
        try:
            context = {"task_id": task_id, "session_id": session_id, "prompt": prompt}
            result_text = await self._execute_plan(plan, context)
            final_summary = result_text or plan.summary or "İşlem tamamlandı"
            await self.send_event({"type": "task_finished", "payload": {"task_id": task_id, "status": "completed", "summary": final_summary, "details": details, "session_id": session_id}})
        except Exception as exc:
            await self.send_event({"type": "task_finished", "payload": {"task_id": task_id, "status": "failed", "summary": f"Görev başarısız: {exc}", "details": details, "session_id": session_id}})

    def _stringify_result(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            if "content" in result and isinstance(result["content"], str):
                return result["content"]
            if "roots" in result:
                lines: list[str] = []
                for root in result.get("roots", []):
                    path = str(root.get("path", ""))
                    entries = root.get("entries", [])
                    if path:
                        lines.append(f"Path: {path}")
                    lines.append("Entries:")
                    if not entries:
                        lines.append("  (No entries)")
                    for entry in entries[:20]:
                        kind = "directory" if entry.get("type") == "directory" else "file"
                        lines.append(f"  - {entry.get('name', '')} ({kind})")
                    if len(entries) > 20:
                        lines.append(f"  ... ({len(entries) - 20} more items)")
                return "\n".join(lines) or "Klasör içeriği boş."
            return json.dumps(result, ensure_ascii=False, indent=2)
        if isinstance(result, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        return str(result)

    def _infer_list_root(self, prompt: str | None) -> str | None:
        if not prompt:
            return None
        lower = prompt.lower()
        if "masaüst" in lower or "desktop" in lower:
            return str((Path.home() / "Desktop").resolve())
        return None

    async def _execute_plan(self, plan: PlanResult, context: dict[str, Any]) -> str:
        last_message = ""
        for step in plan.steps:
            result = await self._execute_step(step, context)
            if isinstance(result, str):
                last_message = result
            elif isinstance(result, dict):
                if "content" in result:
                    last_message = str(result["content"])
                else:
                    last_message = self._stringify_result(result)
            else:
                last_message = self._stringify_result(result)
        return last_message

    async def _execute_step(self, step: PlannedStep, context: dict[str, Any]) -> str | dict[str, Any]:
        if step.tool == "inspect_project":
            result = await self._inspect_project()
            await self.send_event({"type": "message", "payload": {"role": "assistant", "content": self._stringify_result(result), "session_id": context["session_id"]}})
            return result
        if step.tool == "list_workspace":
            requested_root = step.args.get("root") or self._infer_list_root(context.get("prompt"))
            result = await self._list_workspace(requested_root)
            await self.send_event({"type": "message", "payload": {"role": "assistant", "content": self._stringify_result(result), "session_id": context["session_id"]}})
            return result
        if step.tool == "search_files":
            query = str(step.args.get("query", ""))
            limit = int(step.args.get("limit", 20))
            result = self.filesystem.search_files(query, limit=limit)
            await self.send_event({"type": "message", "payload": {"role": "assistant", "content": json.dumps(result, ensure_ascii=False), "session_id": context["session_id"]}})
            return result
        if step.tool == "read_file":
            path = await self._resolve_target_path(str(step.args.get("path", "")))
            if not path:
                raise FileNotFoundError("Uygun dosya bulunamadı")
            result = self.filesystem.read_file(path)
            await self.send_event({"type": "message", "payload": {"role": "assistant", "content": f"{result['path']} okundu", "session_id": context["session_id"]}})
            await self.send_event({"type": "message", "payload": {"role": "assistant", "content": result["content"], "session_id": context["session_id"]}})
            return result
        if step.tool == "write_file":
            path = self.security.resolve_path(step.args["path"])
            result = self.filesystem.write_file(path, str(step.args.get("content", "")))
            await self.send_event({"type": "message", "payload": {"role": "assistant", "content": f"Dosya yazıldı: {result['path']}", "session_id": context["session_id"]}})
            return result
        if step.tool == "run_project":
            return await self._run_project(context)
        if step.tool == "run_command":
            command = str(step.args.get("command", ""))
            cwd = step.args.get("cwd")
            return await self._run_command(command, cwd, step.requires_approval, context)
        if step.tool == "start_program":
            command = str(step.args.get("command", ""))
            cwd = step.args.get("cwd")
            if self.security.requires_approval("start_program", command):
                await self._request_approval(context, command, "medium", "Program başlatma işlemi")
            result = self.terminal.start_program(command, cwd)
            await self.send_event({"type": "message", "payload": {"role": "assistant", "content": f"Program başlatıldı: {json.dumps(result, ensure_ascii=False)}", "session_id": context["session_id"]}})
            return result
        if step.tool == "capture_and_analyze_camera":
            result = await self._capture_and_analyze_camera(context, step.args)
            await self.send_event({"type": "message", "payload": {"role": "assistant", "content": self._stringify_result(result), "session_id": context["session_id"]}})
            return result
        if step.tool == "get_processes":
            result = self.terminal.get_processes()
            await self.send_event({"type": "message", "payload": {"role": "assistant", "content": result["stdout"], "session_id": context["session_id"]}})
            return result
        raise ValueError(f"Bilinmeyen tool: {step.tool}")

    async def _inspect_project(self, root: str | Path | None = None) -> dict[str, Any]:
        overview: list[dict[str, Any]] = []
        targets = [Path(root).resolve()] if root else self.settings.allowed_workspace_roots
        for item in targets:
            candidate = Path(item).resolve()
            if candidate.exists() and candidate.is_dir():
                overview.append(self.filesystem.list_directory(candidate))
        return {"roots": overview}

    async def _list_workspace(self, root: str | Path | None = None) -> dict[str, Any]:
        return await self._inspect_project(root)

    async def _resolve_target_path(self, target: str) -> Path | None:
        if not target:
            return None
        candidate = Path(target)
        if candidate.is_absolute():
            try:
                return self.security.resolve_path(candidate)
            except Exception:
                return None
        search_result = self.filesystem.search_files(target, limit=1)
        results = search_result.get("results", [])
        if results:
            return self.security.resolve_path(results[0]["path"])
        for root in self.settings.allowed_workspace_roots:
            resolved = root / target
            if resolved.exists():
                try:
                    return self.security.resolve_path(resolved)
                except Exception:
                    continue
        return None

    async def _run_command(self, command: str, cwd: str | Path | None, requires_approval: bool, context: dict[str, Any]) -> dict[str, Any]:
        risk = self.security.command_risk(command)
        if requires_approval or risk != "safe":
            await self._request_approval(context, command, risk, "Terminal komutu çalıştırma isteği")
        working_dir = None
        if cwd:
            working_dir = self.security.resolve_path(cwd)
        result = self.terminal.run_command(command, cwd=working_dir, timeout_seconds=self.settings.command_timeout_seconds)
        await self.send_event({"type": "message", "payload": {"role": "assistant", "content": f"Komut tamamlandı: {command}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}", "session_id": context["session_id"]}})
        return result.to_dict()

    async def _run_project(self, context: dict[str, Any]) -> dict[str, Any]:
        project_root = await self._locate_project_root()
        if project_root is None:
            raise FileNotFoundError("Uygun proje kökü bulunamadı")
        package_json = project_root / "package.json"
        pyproject = project_root / "pyproject.toml"
        requirements = project_root / "requirements.txt"
        command = None
        if package_json.exists():
            package_data = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = package_data.get("scripts", {})
            command = "npm run dev" if "dev" in scripts else ("npm start" if "start" in scripts else "npm run build")
        elif pyproject.exists() or requirements.exists():
            command = "python -m pytest"
        else:
            command = "dir"
        return await self._run_command(command, project_root, True, context)

    async def _capture_and_analyze_camera(self, context: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        prompt = str(args.get("prompt") or context.get("prompt") or "Kamera görüntüsünü incele.")
        camera_dir = Path.home() / ".ai_pc_agent" / "camera"
        camera_dir.mkdir(parents=True, exist_ok=True)
        image_path = camera_dir / f"capture_{int(asyncio.get_running_loop().time() * 1000)}.png"
        try:
            import cv2
        except ImportError:
            return {
                "status": "error",
                "image_path": str(image_path),
                "analysis": "OpenCV yüklü değil. Kamera yakalama için opencv-python-headless kurulmalı.",
            }

        capture = cv2.VideoCapture(0)
        if not capture.isOpened():
            return {
                "status": "error",
                "image_path": str(image_path),
                "analysis": "Webcam erişilemedi. Kamera cihazı açık mı?",
            }

        try:
            ok, frame = capture.read()
            if not ok or frame is None:
                return {
                    "status": "error",
                    "image_path": str(image_path),
                    "analysis": "Webcamden görüntü alınamadı.",
                }
            success = cv2.imwrite(str(image_path), frame)
            if not success:
                return {
                    "status": "error",
                    "image_path": str(image_path),
                    "analysis": "Görüntü kaydedilemedi.",
                }
        finally:
            capture.release()

        if not self.settings.gemini_api_key:
            return {
                "status": "partial",
                "image_path": str(image_path),
                "analysis": "Kamera görüntüsü yakalandı. Gemini API anahtarı yok olduğu için görsel analizi yapılmadı.",
                "prompt": prompt,
            }

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.settings.gemini_api_key)
            image_bytes = image_path.read_bytes()
            response = client.models.generate_content(
                model=self.settings.gemini_model,
                contents=[
                    prompt,
                    types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                ],
            )
            analysis = getattr(response, "text", None) or str(response)
            return {
                "status": "ok",
                "image_path": str(image_path),
                "analysis": analysis,
                "prompt": prompt,
            }
        except Exception as exc:
            return {
                "status": "partial",
                "image_path": str(image_path),
                "analysis": f"Kamera görüntüsü yakalandı; Gemini analizi başarısız oldu: {exc}",
                "prompt": prompt,
            }

    async def _locate_project_root(self) -> Path | None:
        for root in self.settings.allowed_workspace_roots:
            if (root / "package.json").exists() or (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
                return root
        for root in self.settings.allowed_workspace_roots:
            for child in root.iterdir():
                if child.is_dir() and ((child / "package.json").exists() or (child / "pyproject.toml").exists() or (child / "requirements.txt").exists()):
                    return child
        return None

    async def _request_approval(self, context: dict[str, Any], command: str, risk: str, reason: str) -> None:
        approval_id = str(uuid4())
        await self.send_event({"type": "approval_request", "payload": {"approval_id": approval_id, "task_id": context["task_id"], "session_id": context["session_id"], "command": command, "risk": risk, "reason": reason}})
        future = self.approval_gate.create(approval_id)
        decision = await future
        if not decision.get("approved"):
            raise PermissionError(decision.get("note") or "Kullanıcı komutu reddetti")
