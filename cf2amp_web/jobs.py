from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from cf2amp.backup import BackupManager
from cf2amp.models import BackupRecord
from cf2amp.orchestrator import Orchestrator
from cf2amp.curseforge import CurseForgeClient

from .settings import WebSettings


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    queue: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, kind: str, target: Callable[[Job], None]) -> Job:
        job = Job(id=str(uuid.uuid4()), kind=kind)
        with self._lock:
            self._jobs[job.id] = job
        thread = threading.Thread(target=self._run, args=(job, target), daemon=True)
        thread.start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def snapshot(self, job: Job) -> dict[str, Any]:
        return {
            "id": job.id,
            "kind": job.kind,
            "status": job.status,
            "created_at": job.created_at,
            "finished_at": job.finished_at,
            "result": job.result,
            "error": job.error,
            "events": job.events[-100:],
        }

    def emit(self, job: Job, step: str, message: str, level: str = "info") -> None:
        event = {
            "seq": len(job.events),
            "time": time.time(),
            "level": level,
            "step": step,
            "message": message,
        }
        job.events.append(event)
        job.queue.put(event)

    def _run(self, job: Job, target: Callable[[Job], None]) -> None:
        job.status = "running"
        self.emit(job, "start", f"{job.kind} started")
        try:
            target(job)
            if job.status == "running":
                job.status = "success"
            self.emit(job, "done", f"{job.kind} finished with status {job.status}")
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            self.emit(job, "error", str(exc), level="error")
        finally:
            job.finished_at = time.time()
            job.queue.put({"terminal": True})


def run_update_job(manager: JobManager, job: Job, settings: WebSettings, dry_run: bool = False) -> None:
    config = settings.to_app_config()
    manager.emit(job, "preflight", f"Server directory: {config.server_dir}")
    if config.source.type.lower() in {"localserverpack", "local-server-pack", "local_server_pack"}:
        manager.emit(job, "source", f"Using local server pack: {config.source.path}")
        client = None
    else:
        manager.emit(job, "source", f"Using CurseForge modpack ID: {config.modpack_id}")
        if not config.curseforge_api_key:
            raise RuntimeError("CurseForge API key is required for CurseForge mode")
        client = CurseForgeClient(config.curseforge_api_key)

    manager.emit(job, "backup", "Creating backup before applying changes" if not dry_run else "Dry run: backup skipped")
    report = Orchestrator(client).run(config, dry_run=dry_run)
    job.result = report.to_dict()
    delta = report.to_dict()["delta"]
    manager.emit(
        job,
        "summary",
        f"Added {len(delta['added'])}, updated {len(delta['updated'])}, removed {len(delta['removed'])}, unchanged {len(delta['unchanged'])}",
    )


def run_rollback_job(manager: JobManager, job: Job, server_dir: Path, backup_dir: Path) -> None:
    manager.emit(job, "rollback", f"Restoring {backup_dir}")
    backup = BackupRecord(
        backup_id=backup_dir.name,
        path=backup_dir,
        manifest_file_id=None,
        created_at=backup_dir.name,
    )
    BackupManager().restore(server_dir, backup)
    job.result = {"server_dir": str(server_dir), "backup_dir": str(backup_dir)}


def sse_payload(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"
