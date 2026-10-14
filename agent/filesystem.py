from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path

from security import SecurityPolicy


@dataclass(slots=True)
class FileSystemToolset:
    security: SecurityPolicy

    def list_directory(self, path: str | Path) -> dict[str, object]:
        resolved = self.security.resolve_path(path)
        if not resolved.exists():
            raise FileNotFoundError(str(resolved))
        if not resolved.is_dir():
            raise NotADirectoryError(str(resolved))
        entries: list[dict[str, object]] = []
        for entry in sorted(resolved.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            entries.append(
                {
                    "name": entry.name,
                    "path": str(entry),
                    "type": "directory" if entry.is_dir() else "file",
                    "size": entry.stat().st_size if entry.is_file() else None,
                }
            )
        return {"path": str(resolved), "entries": entries}

    def read_file(self, path: str | Path, max_bytes: int = 200_000) -> dict[str, object]:
        resolved = self.security.resolve_path(path)
        if not resolved.exists():
            raise FileNotFoundError(str(resolved))
        if not resolved.is_file():
            raise IsADirectoryError(str(resolved))
        data = resolved.read_bytes()
        if len(data) > max_bytes:
            data = data[:max_bytes]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        return {"path": str(resolved), "content": text, "truncated": resolved.stat().st_size > len(data)}

    def write_file(self, path: str | Path, content: str) -> dict[str, object]:
        resolved = self.security.resolve_path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return {"path": str(resolved), "bytes_written": len(content.encode("utf-8"))}

    def delete_file(self, path: str | Path) -> dict[str, object]:
        resolved = self.security.resolve_path(path)
        if not resolved.exists():
            return {"path": str(resolved), "deleted": False}
        if resolved.is_dir():
            raise IsADirectoryError(str(resolved))
        resolved.unlink()
        return {"path": str(resolved), "deleted": True}

    def search_files(self, query: str, root: str | Path | None = None, limit: int = 50) -> dict[str, object]:
        base_roots = [self.security.resolve_path(root)] if root else [candidate for candidate in self.security.allowed_workspace_roots]
        results: list[dict[str, str]] = []
        lowered_query = query.lower().strip()
        for base_root in base_roots:
            if not base_root.exists():
                continue
            for current_root, directories, filenames in os.walk(base_root):
                directories[:] = [directory for directory in directories if not directory.startswith(".")]
                for name in filenames:
                    if lowered_query in name.lower() or fnmatch.fnmatch(name.lower(), lowered_query):
                        candidate = Path(current_root) / name
                        results.append({"name": name, "path": str(candidate), "root": str(base_root)})
                        if len(results) >= limit:
                            return {"query": query, "results": results}
        return {"query": query, "results": results}
