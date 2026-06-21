from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cf2amp.config import AppConfig, BackupPolicy, SourceConfig, UpdatePolicy


def default_config_path() -> Path:
    configured = os.environ.get("CF2AMP_WEB_CONFIG")
    if configured:
        return Path(configured)
    config_dir = Path("/config")
    if config_dir.exists():
        return config_dir / "cf2amp-web.json"
    return Path.cwd() / "cf2amp-web.json"


def default_pack_dir() -> Path:
    configured = os.environ.get("CF2AMP_PACK_DIR")
    if configured:
        return Path(configured)
    pack_dir = Path("/packs")
    if pack_dir.exists():
        return pack_dir
    return Path.cwd() / "packs"


@dataclass
class WebSettings:
    source_type: str = "localServerPack"
    curseforge_api_key: str | None = None
    modpack_id: int = 0
    minecraft_version: str | None = None
    server_dir: str = "/server"
    local_server_pack: str | None = None
    amp_instances_dir: str = "/opt/cubecoders/amp/instances"
    java_path: str = "java"
    java_opts: str = "-Xmx4G -Xms2G"
    loader: str | None = None
    remove_missing: bool = False
    prefer_server_pack: bool = True
    rollback_on_failure: bool = True
    startup_validation_seconds: int = 20
    backups_to_keep: int = 3

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WebSettings":
        current = cls()
        values = asdict(current)
        for key in values:
            if key in data:
                values[key] = data[key]
        return cls(**values)

    def sanitized(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("curseforge_api_key", None)
        data["has_api_key"] = bool(self.curseforge_api_key)
        return data

    def to_app_config(self) -> AppConfig:
        source_path = Path(self.local_server_pack) if self.local_server_pack else None
        return AppConfig(
            curseforge_api_key=self.curseforge_api_key or os.environ.get("CURSEFORGE_API_KEY"),
            modpack_id=int(self.modpack_id or 0),
            minecraft_version=self.minecraft_version or None,
            server_dir=Path(self.server_dir),
            source=SourceConfig(type=self.source_type, path=source_path),
            java_path=self.java_path,
            java_opts=self.java_opts,
            loader=self.loader,
            update_policy=UpdatePolicy(
                mode="delta",
                remove_missing=self.remove_missing,
                prefer_server_pack=self.prefer_server_pack,
                rollback_on_failure=self.rollback_on_failure,
                startup_validation_seconds=self.startup_validation_seconds,
            ),
            backup_policy=BackupPolicy(
                enabled=True,
                keep_last=self.backups_to_keep,
                include_world=True,
                include_config=True,
            ),
        )


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()

    def load(self) -> WebSettings:
        env_server_dir = os.environ.get("SERVER_DIR")
        env_amp_instances_dir = os.environ.get("AMP_INSTANCES_DIR")
        if not self.path.exists():
            return WebSettings(
                curseforge_api_key=os.environ.get("CURSEFORGE_API_KEY"),
                server_dir=env_server_dir or "/server",
                amp_instances_dir=env_amp_instances_dir or "/opt/cubecoders/amp/instances",
            )
        data = json.loads(self.path.read_text(encoding="utf-8"))
        settings = WebSettings.from_dict(data)
        if not settings.curseforge_api_key:
            settings.curseforge_api_key = os.environ.get("CURSEFORGE_API_KEY")
        if env_server_dir and settings.server_dir in {"", "/server"}:
            settings.server_dir = env_server_dir
        if env_amp_instances_dir and settings.amp_instances_dir in {"", "/opt/cubecoders/amp/instances"}:
            settings.amp_instances_dir = env_amp_instances_dir
        return settings

    def save(self, settings: WebSettings) -> WebSettings:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        return settings
