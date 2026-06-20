from __future__ import annotations

import shutil
import time
from pathlib import Path

from .models import BackupRecord
from .state import ServerState


class BackupManager:
    def create(self, server_dir: Path, state: ServerState, keep_last: int = 3) -> BackupRecord:
        backup_root = server_dir / "backups" / "cf2amp"
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_id = time.strftime("%Y%m%d-%H%M%S")
        target = backup_root / backup_id
        target.mkdir(parents=True, exist_ok=False)

        for name in ("world", "world_nether", "world_the_end", "config", "mods", ".cf2amp-state.json"):
            source = server_dir / name
            if not source.exists():
                continue
            destination = target / name
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)

        self.prune(backup_root, keep_last)
        return BackupRecord(
            backup_id=backup_id,
            path=target,
            manifest_file_id=state.modpack_file_id,
            created_at=backup_id,
        )

    def restore(self, server_dir: Path, backup: BackupRecord) -> None:
        if not backup.path.exists():
            raise FileNotFoundError(f"Backup not found: {backup.path}")
        for child in backup.path.iterdir():
            destination = server_dir / child.name
            if destination.exists():
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()
            if child.is_dir():
                shutil.copytree(child, destination)
            else:
                shutil.copy2(child, destination)

    @staticmethod
    def prune(backup_root: Path, keep_last: int) -> None:
        backups = sorted([item for item in backup_root.iterdir() if item.is_dir()])
        for old in backups[:-keep_last]:
            shutil.rmtree(old)
