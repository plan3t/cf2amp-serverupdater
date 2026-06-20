from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from .backup import BackupManager
from .config import AppConfig
from .curseforge import CurseForgeClient, CurseForgeError
from .models import RunReport
from .state import ServerState
from .updater import ServerUpdater, UpdateOptions
from .validator import ValidationError, Validator


LOGGER = logging.getLogger("cf2amp")


class Orchestrator:
    def __init__(
        self,
        client: CurseForgeClient,
        backup_manager: BackupManager | None = None,
        validator: Validator | None = None,
    ) -> None:
        self.client = client
        self.backup_manager = backup_manager or BackupManager()
        self.validator = validator or Validator()

    def run(self, config: AppConfig, dry_run: bool = False) -> RunReport:
        run_id = str(uuid.uuid4())
        server_dir = config.server_dir.resolve()
        warnings = self.validator.validate_layout(server_dir)
        state = ServerState.load(server_dir)
        backup = None

        if config.backup_policy.enabled and not dry_run:
            backup = self.backup_manager.create(server_dir, state, config.backup_policy.keep_last)
            LOGGER.info("backup_created", extra={"run_id": run_id, "backup": str(backup.path)})

        try:
            result = ServerUpdater(self.client).update(
                UpdateOptions(
                    server_dir=server_dir,
                    modpack_project_id=config.modpack_id,
                    minecraft_version=config.minecraft_version,
                    use_server_pack=config.update_policy.prefer_server_pack,
                    remove_missing=config.update_policy.remove_missing,
                    dry_run=dry_run,
                )
            )
            warnings.extend(result.skipped)
            warnings.extend(
                self.validator.smoke_test(
                    server_dir,
                    config.java_path,
                    config.java_opts,
                    config.update_policy.startup_validation_seconds,
                )
            )
            report = RunReport(
                run_id=run_id,
                status="success",
                mode=result.mode,
                backup=backup,
                delta=result.delta,
                warnings=warnings,
            )
            self._write_report(server_dir, report)
            return report
        except (CurseForgeError, ValidationError, OSError) as exc:
            LOGGER.exception("update_failed", extra={"run_id": run_id})
            if backup and config.update_policy.rollback_on_failure:
                self.backup_manager.restore(server_dir, backup)
                warnings.append(f"rollback restored backup {backup.backup_id}")
            raise RuntimeError(f"update failed: {exc}") from exc

    @staticmethod
    def _write_report(server_dir: Path, report: RunReport) -> None:
        reports = server_dir / "logs" / "cf2amp"
        reports.mkdir(parents=True, exist_ok=True)
        path = reports / f"{report.run_id}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
