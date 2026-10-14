from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class TerminalResult:
    command: str
    cwd: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "command": self.command,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
        }


class TerminalToolset:
    def run_command(self, command: str, cwd: str | Path | None = None, timeout_seconds: int = 120) -> TerminalResult:
        working_dir = str(Path(cwd).resolve()) if cwd else None
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            return TerminalResult(command=command, cwd=working_dir or "", exit_code=process.returncode, stdout=stdout, stderr=stderr)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            return TerminalResult(command=command, cwd=working_dir or "", exit_code=None, stdout=stdout, stderr=stderr, timed_out=True)

    def start_program(self, command: str, cwd: str | Path | None = None) -> dict[str, object]:
        working_dir = str(Path(cwd).resolve()) if cwd else None
        process = subprocess.Popen(command, shell=True, cwd=working_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"command": command, "cwd": working_dir or "", "pid": process.pid}

    def get_processes(self) -> dict[str, object]:
        command = ["tasklist", "/fo", "csv"]
        process = subprocess.run(command, capture_output=True, text=True, check=False)
        return {"stdout": process.stdout, "stderr": process.stderr, "exit_code": process.returncode}
