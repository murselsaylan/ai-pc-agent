from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from agent.config import AgentSettings
except ImportError:  # pragma: no cover - fallback for direct script execution
    from config import AgentSettings


@dataclass(slots=True)
class PlannedStep:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    requires_approval: bool = False
    explanation: str = ""


@dataclass(slots=True)
class PlanResult:
    summary: str
    steps: list[PlannedStep] = field(default_factory=list)


class LocalPlanner:
    def __init__(self, settings: AgentSettings):
        self.settings = settings

    def build_plan(self, prompt: str) -> PlanResult:
        text = prompt.lower().strip()
        has_camera = any(keyword in text for keyword in ["kamera", "camera", "webcam"])
        asks_for_vision = any(keyword in text for keyword in ["ne gördüğünü", "ne gordugunu", "gördüğünü", "gordugunu", "görüntü", "görüntuyu", "görünüm", "anlat", "what do you see", "what's in view", "see"])
        if has_camera and asks_for_vision:
            return PlanResult(
                summary="Kamera görüntüsünü yakalayıp değerlendireceğim.",
                steps=[
                    PlannedStep(tool="capture_and_analyze_camera", args={"prompt": prompt}, requires_approval=True, explanation="Webcam görüntüsü yakalanıp analiz ediliyor"),
                ],
            )
        if has_camera:
            command = "start microsoft.windows.camera:"
            return PlanResult(
                summary="Kamerayı açacağım.",
                steps=[
                    PlannedStep(tool="start_program", args={"command": command}, requires_approval=True, explanation="Kamera başlatılıyor"),
                ],
            )
        is_listing_request = any(
            keyword in text for keyword in ["listele", "list", "bul", "find", "klasör", "klasor", "söyle", "göster", "goster", "hangi", "nerede", "desktop", "masaüst"]
        )
        if is_listing_request:
            root_arg = {"root": str((Path.home() / "Desktop").resolve())} if "masaüst" in text or "desktop" in text else {}
            return PlanResult(summary="Klasör içeriğini inceleyeceğim.", steps=[PlannedStep(tool="list_workspace", args=root_arg, explanation="Çalışma alanı taranıyor")])
        if any(keyword in text for keyword in ["uygulama", "app", "program"]):
            return PlanResult(
                summary="İstenen uygulamayı açacağım.",
                steps=[
                    PlannedStep(tool="start_program", args={"command": "start "}, requires_approval=True, explanation="Uygulama başlatılıyor"),
                ],
            )
        if any(keyword in text for keyword in ["oku", "read", "açıkla", "readme"]):
            filename = self._extract_filename(prompt) or "README.md"
            return PlanResult(
                summary="İstenen dosyayı bulup okuyacağım.",
                steps=[
                    PlannedStep(tool="search_files", args={"query": filename, "limit": 10}, explanation=f"{filename} aranıyor"),
                    PlannedStep(tool="read_file", args={"path": filename}, explanation=f"{filename} okunuyor"),
                ],
            )
        if any(keyword in text for keyword in ["çalıştır", "run", "başlat", "start"]):
            return PlanResult(
                summary="Projeyi çalıştırmak için uygun giriş noktasını arayacağım.",
                steps=[
                    PlannedStep(tool="inspect_project", args={}, explanation="Proje yapısı inceleniyor"),
                    PlannedStep(tool="run_project", args={}, requires_approval=True, explanation="Çalıştırma komutu hazırlanıyor"),
                ],
            )
        if any(keyword in text for keyword in ["hata", "fix", "düzelt", "repair"]):
            return PlanResult(
                summary="Hata ayıklama için proje özetini çıkaracağım.",
                steps=[
                    PlannedStep(tool="inspect_project", args={}, explanation="Proje taranıyor"),
                    PlannedStep(tool="read_file", args={"path": self._extract_filename(prompt) or "README.md"}, explanation="Olası hedef dosya okunuyor"),
                ],
            )
        return PlanResult(
            summary="Yalnızca açık komutları uygularım; ek analiz yapmam.",
            steps=[],
        )

    def _extract_filename(self, prompt: str) -> str | None:
        known = ["package.json", "README.md", "readme.md", "pyproject.toml", "requirements.txt"]
        lower = prompt.lower()
        for name in known:
            if name.lower() in lower:
                return name
        return None


class GeminiPlanner:
    def __init__(self, settings: AgentSettings):
        self.settings = settings
        self._client = None
        self._types = None
        if settings.gemini_api_key:
            try:
                from google import genai
                from google.genai import types

                self._client = genai.Client(api_key=settings.gemini_api_key)
                self._types = types
            except Exception:
                self._client = None
                self._types = None

    @property
    def available(self) -> bool:
        return self._client is not None and self._types is not None

    def _tool_declarations(self) -> list[Any]:
        if self._types is None:
            return []
        safe_string = self._types.Schema(type=self._types.Type.STRING)
        return [
            self._types.Tool(
                function_declarations=[
                    self._types.FunctionDeclaration(
                        name="read_file",
                        description="Read a file inside the safe workspace root.",
                        parameters=self._types.Schema(
                            type=self._types.Type.OBJECT,
                            properties={
                                "path": self._types.Schema(type=self._types.Type.STRING, description="Absolute or relative path inside allowed workspace"),
                            },
                            required=["path"],
                        ),
                    ),
                    self._types.FunctionDeclaration(
                        name="write_file",
                        description="Write or overwrite a file inside the safe workspace root.",
                        parameters=self._types.Schema(
                            type=self._types.Type.OBJECT,
                            properties={
                                "path": self._types.Schema(type=self._types.Type.STRING, description="Absolute or relative file path inside workspace"),
                                "content": self._types.Schema(type=self._types.Type.STRING, description="Content to write"),
                            },
                            required=["path", "content"],
                        ),
                    ),
                    self._types.FunctionDeclaration(
                        name="list_directory",
                        description="List directory entries inside the allowed workspace.",
                        parameters=self._types.Schema(
                            type=self._types.Type.OBJECT,
                            properties={"path": self._types.Schema(type=self._types.Type.STRING, description="Directory path to inspect")},
                            required=["path"],
                        ),
                    ),
                    self._types.FunctionDeclaration(
                        name="search_files",
                        description="Search for files by filename or pattern inside the allowed workspace.",
                        parameters=self._types.Schema(
                            type=self._types.Type.OBJECT,
                            properties={
                                "query": self._types.Schema(type=self._types.Type.STRING, description="Filename or pattern to search"),
                                "root": self._types.Schema(type=self._types.Type.STRING, description="Optional base path"),
                                "limit": self._types.Schema(type=self._types.Type.INTEGER, description="Max results"),
                            },
                            required=["query"],
                        ),
                    ),
                    self._types.FunctionDeclaration(
                        name="run_command",
                        description="Run a shell command only after approval when the command is risky.",
                        parameters=self._types.Schema(
                            type=self._types.Type.OBJECT,
                            properties={
                                "command": self._types.Schema(type=self._types.Type.STRING, description="Shell command to run"),
                                "cwd": self._types.Schema(type=self._types.Type.STRING, description="Working directory if needed"),
                            },
                            required=["command"],
                        ),
                    ),
                    self._types.FunctionDeclaration(
                        name="start_program",
                        description="Start a program or service in the safe workspace context.",
                        parameters=self._types.Schema(
                            type=self._types.Type.OBJECT,
                            properties={
                                "command": self._types.Schema(type=self._types.Type.STRING, description="Program command to start"),
                                "cwd": self._types.Schema(type=self._types.Type.STRING, description="Optional working directory"),
                            },
                            required=["command"],
                        ),
                    ),
                    self._types.FunctionDeclaration(
                        name="capture_and_analyze_camera",
                        description="Open the webcam, capture a single frame, and analyze the scene from the image.",
                        parameters=self._types.Schema(
                            type=self._types.Type.OBJECT,
                            properties={
                                "prompt": self._types.Schema(type=self._types.Type.STRING, description="User request to guide the camera analysis"),
                            },
                            required=["prompt"],
                        ),
                    ),
                    self._types.FunctionDeclaration(
                        name="get_processes",
                        description="List running processes on the machine for diagnostics.",
                        parameters=self._types.Schema(type=self._types.Type.OBJECT, properties={}),
                    ),
                ]
            )
        ]

    def _step_from_function_call(self, function_call: Any) -> PlannedStep:
        name = getattr(function_call, "name", None) or str(function_call.get("name", ""))
        args = getattr(function_call, "args", None) or function_call.get("args", {}) or {}
        command = args.get("command", "") if isinstance(args, dict) else ""
        requires_approval = name in {"run_command", "start_program"} or (name == "write_file" and "delete" in str(command).lower())
        if isinstance(args, dict):
            return PlannedStep(tool=name, args=args, requires_approval=requires_approval, explanation=f"{name} çağrılıyor")
        return PlannedStep(tool=name, args={}, requires_approval=requires_approval, explanation=f"{name} çağrılıyor")

    def build_plan(self, prompt: str, workspace_roots: list[str]) -> PlanResult:
        if not self.available:
            return LocalPlanner(self.settings).build_plan(prompt)
        tool_manifest = {
            "read_file": "read_file(path)",
            "write_file": "write_file(path, content)",
            "list_directory": "list_directory(path)",
            "search_files": "search_files(query, root, limit)",
            "run_command": "run_command(command, cwd)",
            "start_program": "start_program(command, cwd)",
            "capture_and_analyze_camera": "capture_and_analyze_camera(prompt)",
            "get_processes": "get_processes()",
        }
        instruction = (
            "You are a planning agent. Decide the safest tool sequence to satisfy the user's request. "
            "Use tool calls for file and command operations. Request approval before risky commands. "
            f"Workspace roots: {workspace_roots}. Tools: {json.dumps(tool_manifest, ensure_ascii=False)}. "
            f"User prompt: {prompt}"
        )
        try:
            response = self._client.models.generate_content(
                model=self.settings.gemini_model,
                contents=instruction,
                config=self._types.GenerateContentConfig(tools=self._tool_declarations()),
            )
            if getattr(response, "function_calls", None):
                calls = response.function_calls
                steps = [self._step_from_function_call(item) for item in calls]
                if steps:
                    return PlanResult(summary=getattr(response, "text", "") or "Gemini tool plan created.", steps=steps)
            text = getattr(response, "text", "") or ""
            try:
                parsed = json.loads(text)
                steps = [PlannedStep(**step) for step in parsed.get("steps", [])]
                return PlanResult(summary=parsed.get("summary", "Gemini plan created"), steps=steps)
            except Exception:
                return LocalPlanner(self.settings).build_plan(prompt)
        except Exception:
            return LocalPlanner(self.settings).build_plan(prompt)


class Planner:
    def __init__(self, settings: AgentSettings):
        self.local = LocalPlanner(settings)
        self.gemini = GeminiPlanner(settings)

    def build_plan(self, prompt: str, workspace_roots: list[str]) -> PlanResult:
        local_plan = self.local.build_plan(prompt)
        if local_plan.steps:
            return local_plan
        if not self.gemini.available:
            raise RuntimeError("GEMINI_API_KEY boş. Lütfen .env içine gerçek Gemini API anahtarını ekleyin.")
        return self.gemini.build_plan(prompt, workspace_roots)
