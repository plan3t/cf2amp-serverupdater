from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BackupPolicy:
    enabled: bool = True
    keep_last: int = 3
    include_world: bool = True
    include_config: bool = True


@dataclass(frozen=True)
class UpdatePolicy:
    mode: str = "delta"
    remove_missing: bool = False
    prefer_server_pack: bool = True
    rollback_on_failure: bool = True
    startup_validation_seconds: int = 20


@dataclass(frozen=True)
class AppConfig:
    curseforge_api_key: str | None
    modpack_id: int
    minecraft_version: str | None
    server_dir: Path
    java_path: str = "java"
    java_opts: str = "-Xmx2G -Xms1G"
    loader: str | None = None
    update_policy: UpdatePolicy = UpdatePolicy()
    backup_policy: BackupPolicy = BackupPolicy()


def load_config(path: Path) -> AppConfig:
    data = _load_document(path)
    curseforge_api_key = data.get("curseforgeApiKey") or os.environ.get("CURSEFORGE_API_KEY")
    policy = data.get("updatePolicy", {})
    backup = data.get("backupPolicy", {})
    return AppConfig(
        curseforge_api_key=curseforge_api_key,
        modpack_id=int(data["modpackId"]),
        minecraft_version=data.get("minecraftVersion"),
        server_dir=Path(data["serverDir"]),
        java_path=data.get("javaPath", "java"),
        java_opts=data.get("javaOpts", "-Xmx2G -Xms1G"),
        loader=data.get("loader"),
        update_policy=UpdatePolicy(
            mode=policy.get("mode", "delta"),
            remove_missing=bool(policy.get("removeMissing", False)),
            prefer_server_pack=bool(policy.get("preferServerPack", True)),
            rollback_on_failure=bool(policy.get("rollbackOnFailure", True)),
            startup_validation_seconds=int(policy.get("startupValidationSeconds", 20)),
        ),
        backup_policy=BackupPolicy(
            enabled=bool(backup.get("enabled", True)),
            keep_last=int(backup.get("keepLast", 3)),
            include_world=bool(backup.get("includeWorld", True)),
            include_config=bool(backup.get("includeConfig", True)),
        ),
    )


def _load_document(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return _parse_minimal_yaml(text)


def _parse_minimal_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, _, value = line.strip().partition(":")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value.strip() == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _coerce_scalar(value.strip())
    return root


def _coerce_scalar(value: str) -> Any:
    value = value.strip('"').strip("'")
    if value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1])
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        return value
