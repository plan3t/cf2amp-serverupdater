from __future__ import annotations

import shutil
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from cf2amp.backup import BackupManager
from cf2amp.curseforge import CurseForgeClient, CurseForgeError
from cf2amp.models import DeltaPlan, ModMetadata
from cf2amp.state import ServerState
from cf2amp.updater import ServerUpdater, UpdateOptions

from .amp import AmpScanner
from .jobs import JobManager, run_rollback_job, run_update_job, sse_payload
from .settings import SettingsStore, WebSettings, default_pack_dir


PACKAGE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
jobs = JobManager()


@lru_cache(maxsize=1)
def settings_store() -> SettingsStore:
    return SettingsStore()


def create_app() -> FastAPI:
    app = FastAPI(title="cf2amp Web", version="0.1.0")
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html", {})

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return settings_store().load().sanitized()

    @app.post("/api/settings")
    async def save_settings(payload: dict[str, Any]) -> dict[str, Any]:
        current = settings_store().load()
        data = current.sanitized()
        data.update(payload)
        if payload.get("curseforge_api_key"):
            data["curseforge_api_key"] = payload["curseforge_api_key"]
        else:
            data["curseforge_api_key"] = current.curseforge_api_key
        settings = WebSettings.from_dict(data)
        settings_store().save(settings)
        return settings.sanitized()

    @app.get("/api/state")
    def get_state() -> dict[str, Any]:
        settings = settings_store().load()
        server_dir = Path(settings.server_dir)
        state = ServerState.load(server_dir)
        backups = list_backups(server_dir)
        return {
            "server_dir": str(server_dir),
            "state": {
                "modpack_project_id": state.modpack_project_id,
                "modpack_file_id": state.modpack_file_id,
                "managed_count": len(state.managed_files),
                "managed_files": [
                    {
                        "key": key,
                        "project_id": item.project_id,
                        "file_id": item.file_id,
                        "path": item.path,
                        "sha256": item.sha256,
                    }
                    for key, item in sorted(state.managed_files.items())
                ],
            },
            "backups": backups,
        }

    @app.get("/api/instances")
    def get_instances(path: str | None = None) -> dict[str, Any]:
        settings = settings_store().load()
        roots = [
            Path(path) if path else Path(settings.amp_instances_dir),
            Path("/home/amp/.ampdata/instances"),
        ]
        instances = AmpScanner(roots).scan()
        return {"instances": [instance.__dict__ for instance in instances]}

    @app.post("/api/search")
    async def search_modpacks(payload: dict[str, Any]) -> dict[str, Any]:
        settings = settings_store().load()
        api_key = payload.get("api_key") or settings.curseforge_api_key
        query = str(payload.get("query") or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="query is required")
        if not api_key:
            raise HTTPException(status_code=400, detail="CurseForge Core API key is required for search")
        try:
            matches = CurseForgeClient(api_key).search_modpacks(query)
        except CurseForgeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "matches": [
                {"id": item["id"], "name": item.get("name"), "slug": item.get("slug")}
                for item in matches
            ]
        }

    @app.post("/api/upload")
    async def upload_server_pack(file: UploadFile = File(...)) -> dict[str, Any]:
        if not file.filename or not file.filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Upload a .zip server pack")
        pack_dir = default_pack_dir()
        try:
            pack_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Cannot create pack directory {pack_dir}: {exc}") from exc
        safe_name = Path(file.filename).name
        target = pack_dir / f"{int(time.time())}-{safe_name}"
        try:
            with target.open("wb") as handle:
                shutil.copyfileobj(file.file, handle)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Cannot write uploaded pack to {target}: {exc}") from exc
        settings = settings_store().load()
        settings.local_server_pack = str(target)
        settings.source_type = "localServerPack"
        settings_store().save(settings)
        return {"path": str(target), "settings": settings.sanitized()}

    @app.post("/api/preview")
    async def preview(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = settings_store().load()
        if payload:
            data = settings.sanitized()
            data.update(payload)
            data["curseforge_api_key"] = settings.curseforge_api_key
            settings = WebSettings.from_dict(data)
        try:
            result = preview_update(settings)
        except (CurseForgeError, RuntimeError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "modpack_file": {
                "id": result.modpack_file.id,
                "display_name": result.modpack_file.display_name,
                "file_name": result.modpack_file.file_name,
            },
            "mode": result.mode,
            "delta": delta_payload(result.delta),
            "summary": {
                "added": len(result.delta.added),
                "updated": len(result.delta.updated),
                "removed": len(result.delta.removed),
                "unchanged": len(result.delta.unchanged),
            },
        }

    @app.post("/api/jobs/update")
    async def start_update(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = settings_store().load()
        dry_run = bool((payload or {}).get("dry_run", False))
        job = jobs.create("update", lambda current: run_update_job(jobs, current, settings, dry_run=dry_run))
        return jobs.snapshot(job)

    @app.post("/api/jobs/rollback")
    async def start_rollback(payload: dict[str, Any]) -> dict[str, Any]:
        settings = settings_store().load()
        backup_dir = payload.get("backup_dir")
        if not backup_dir:
            raise HTTPException(status_code=400, detail="backup_dir is required")
        job = jobs.create(
            "rollback",
            lambda current: run_rollback_job(jobs, current, Path(settings.server_dir), Path(backup_dir)),
        )
        return jobs.snapshot(job)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return jobs.snapshot(job)

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str) -> StreamingResponse:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")

        def event_stream():
            sent = 0
            while sent < len(job.events):
                yield sse_payload(job.events[sent])
                sent += 1
            while job.status in {"queued", "running"}:
                try:
                    event = job.queue.get(timeout=10)
                except Exception:
                    yield ": keep-alive\n\n"
                    continue
                if event.get("terminal"):
                    break
                if event.get("seq", sent) < sent:
                    continue
                yield sse_payload(event)
                sent = max(sent, int(event.get("seq", sent)) + 1)
            while sent < len(job.events):
                yield sse_payload(job.events[sent])
                sent += 1

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app


def preview_update(settings: WebSettings):
    config = settings.to_app_config()
    source_type = config.source.type.lower()
    if source_type in {"localserverpack", "local-server-pack", "local_server_pack"}:
        if config.source.path is None:
            raise RuntimeError("Upload or select a local server-pack ZIP first")
        return ServerUpdater(None).update_from_local_server_pack(
            server_dir=config.server_dir,
            archive_path=config.source.path,
            minecraft_version=config.minecraft_version,
            remove_missing=config.update_policy.remove_missing,
            dry_run=True,
        )
    if not config.curseforge_api_key:
        raise RuntimeError("CurseForge Core API key is required for API preview")
    return ServerUpdater(CurseForgeClient(config.curseforge_api_key)).update(
        UpdateOptions(
            server_dir=config.server_dir,
            modpack_project_id=config.modpack_id,
            minecraft_version=config.minecraft_version,
            use_server_pack=config.update_policy.prefer_server_pack,
            remove_missing=config.update_policy.remove_missing,
            dry_run=True,
        )
    )


def list_backups(server_dir: Path) -> list[dict[str, str]]:
    backup_root = server_dir / "backups" / "cf2amp"
    if not backup_root.exists():
        return []
    backups = []
    for item in sorted([path for path in backup_root.iterdir() if path.is_dir()], reverse=True):
        backups.append({"id": item.name, "path": str(item)})
    return backups


def delta_payload(delta: DeltaPlan) -> dict[str, Any]:
    return {
        "added": [mod_payload(item) for item in delta.added],
        "updated": [
            {"from": mod_payload(old), "to": mod_payload(new)}
            for old, new in delta.updated
        ],
        "removed": [mod_payload(item) for item in delta.removed],
        "unchanged": [mod_payload(item) for item in delta.unchanged],
    }


def mod_payload(mod: ModMetadata) -> dict[str, Any]:
    return {
        "mod_id": mod.mod_id,
        "file_id": mod.file_id,
        "file_name": mod.file_name,
        "version": mod.version,
        "sha256": mod.sha256,
        "dependencies": mod.dependencies,
        "server_side": mod.server_side,
        "loader": mod.loader,
    }


app = create_app()


def main() -> None:
    uvicorn.run("cf2amp_web.main:app", host="0.0.0.0", port=8080, reload=False)


if __name__ == "__main__":
    main()
