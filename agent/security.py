from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


@dataclass(slots=True)
class SecurityPolicy:
    allowed_workspace_roots: list[Path]

    def resolve_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path).expanduser()
        if not path.is_absolute() and self.allowed_workspace_roots:
            path = (self.allowed_workspace_roots[0] / path).resolve()
        else:
            path = path.resolve()
        if not any(_is_within(path, root) or path == root.resolve() for root in self.allowed_workspace_roots):
            raise PermissionError(f"Path is outside allowed workspace roots: {path}")
        return path

    def command_risk(self, command: str) -> str:
        normalized = command.lower().strip()
        high_risk_markers = [
            "del ",
            "erase ",
            "rm ",
            "rmdir ",
            "shutdown",
            "restart",
            "reboot",
            "format ",
            "git push",
            "git reset --hard",
            "npm install",
            "npm ci",
            "npm add",
            "pip install",
            "pip uninstall",
            "yarn add",
            "pnpm add",
        ]
        if any(marker in normalized for marker in high_risk_markers):
            return "high"
        if normalized.startswith(("git status", "git diff", "git log", "dir", "ls", "pwd", "whoami")):
            return "safe"
        if normalized.startswith(("python ", "python3 ", "node ", "npm run ", "npm test", "pytest", "uvicorn ", "dotnet ")):
            return "medium"
        return "medium"

    def requires_approval(self, tool_name: str, command: str | None = None) -> bool:
        if tool_name in {"read_file", "list_directory", "search_files", "get_processes", "write_file"}:
            return False
        if tool_name in {"delete_file", "install_package", "shutdown", "restart", "git_push"}:
            return True
        if tool_name == "run_command":
            return self.command_risk(command or "") != "safe"
        return True
