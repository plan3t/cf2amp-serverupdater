from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


STATE_FILE = ".cf2amp-state.json"


@dataclass
class ManagedFile:
    project_id: int
    file_id: int
    path: str
    sha256: str | None = None


@dataclass
class ServerState:
    modpack_project_id: int | None = None
    modpack_file_id: int | None = None
    managed_files: dict[str, ManagedFile] = field(default_factory=dict)

    @classmethod
    def load(cls, server_dir: Path) -> "ServerState":
        path = server_dir / STATE_FILE
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            modpack_project_id=data.get("modpack_project_id"),
            modpack_file_id=data.get("modpack_file_id"),
            managed_files={
                key: ManagedFile(**value)
                for key, value in data.get("managed_files", {}).items()
            },
        )

    def save(self, server_dir: Path) -> None:
        path = server_dir / STATE_FILE
        data: dict[str, Any] = {
            "modpack_project_id": self.modpack_project_id,
            "modpack_file_id": self.modpack_file_id,
            "managed_files": {
                key: vars(value) for key, value in sorted(self.managed_files.items())
            },
        }
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
