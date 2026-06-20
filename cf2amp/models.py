from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModMetadata:
    mod_id: int
    file_id: int
    file_name: str
    version: str | None = None
    sha256: str | None = None
    dependencies: list[int] = field(default_factory=list)
    server_side: bool | None = None
    loader: str | None = None


@dataclass(frozen=True)
class ModpackManifest:
    project_id: int
    file_id: int
    name: str
    minecraft_version: str | None
    loader: str | None
    loader_version: str | None
    mods: list[ModMetadata]


@dataclass(frozen=True)
class DeltaPlan:
    added: list[ModMetadata]
    updated: list[tuple[ModMetadata, ModMetadata]]
    removed: list[ModMetadata]
    unchanged: list[ModMetadata]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.updated or self.removed)


@dataclass(frozen=True)
class BackupRecord:
    backup_id: str
    path: Path
    manifest_file_id: int | None
    created_at: str


@dataclass(frozen=True)
class RunReport:
    run_id: str
    status: str
    mode: str
    backup: BackupRecord | None
    delta: DeltaPlan
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "mode": self.mode,
            "backup": None if self.backup is None else {
                "backup_id": self.backup.backup_id,
                "path": str(self.backup.path),
                "manifest_file_id": self.backup.manifest_file_id,
                "created_at": self.backup.created_at,
            },
            "delta": {
                "added": [mod.file_name for mod in self.delta.added],
                "updated": [
                    {"from": old.file_name, "to": new.file_name}
                    for old, new in self.delta.updated
                ],
                "removed": [mod.file_name for mod in self.delta.removed],
                "unchanged": [mod.file_name for mod in self.delta.unchanged],
            },
            "warnings": self.warnings,
        }
