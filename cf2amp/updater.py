from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .curseforge import CurseForgeClient, CurseForgeError, ModpackFile
from .models import DeltaPlan, ModMetadata, ModpackManifest
from .state import ManagedFile, ServerState


@dataclass(frozen=True)
class UpdateOptions:
    server_dir: Path
    modpack_project_id: int
    modpack_file_id: int | None = None
    minecraft_version: str | None = None
    use_server_pack: bool = True
    remove_missing: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class UpdateResult:
    modpack_file: ModpackFile
    mode: str
    added: list[str]
    updated: list[str]
    removed: list[str]
    skipped: list[str]
    delta: DeltaPlan


class ServerUpdater:
    def __init__(self, client: CurseForgeClient | None) -> None:
        self.client = client

    def update(self, options: UpdateOptions) -> UpdateResult:
        if self.client is None:
            raise CurseForgeError("CurseForge client is required for CurseForge API updates")
        server_dir = options.server_dir.resolve()
        mods_dir = server_dir / "mods"
        if not options.dry_run:
            server_dir.mkdir(parents=True, exist_ok=True)
            mods_dir.mkdir(parents=True, exist_ok=True)

        state = ServerState.load(server_dir)
        modpack_file = self._select_modpack_file(options)

        with tempfile.TemporaryDirectory(prefix="cf2amp-") as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / modpack_file.file_name
            source_file = modpack_file
            mode = "manifest"

            if options.use_server_pack and modpack_file.server_pack_file_id:
                source_file = self.client.get_file(options.modpack_project_id, modpack_file.server_pack_file_id)
                mode = "server-pack"

            self._download_file(options.modpack_project_id, source_file, archive)
            with zipfile.ZipFile(archive) as zf:
                if mode == "server-pack":
                    return self._apply_server_pack(zf, options, state, modpack_file)
                return self._apply_manifest_pack(zf, options, state, modpack_file)

    def update_from_local_server_pack(
        self,
        server_dir: Path,
        archive_path: Path,
        minecraft_version: str | None = None,
        remove_missing: bool = False,
        dry_run: bool = False,
    ) -> UpdateResult:
        server_dir = server_dir.resolve()
        mods_dir = server_dir / "mods"
        archive_path = archive_path.resolve()
        if not archive_path.exists():
            raise CurseForgeError(f"Local server pack not found: {archive_path}")
        if not dry_run:
            server_dir.mkdir(parents=True, exist_ok=True)
            mods_dir.mkdir(parents=True, exist_ok=True)

        digest = self._sha256_file(archive_path)
        modpack_file = ModpackFile(
            id=int(digest[:12], 16),
            display_name=archive_path.name,
            file_name=archive_path.name,
            download_url=None,
            release_type=1,
            game_versions=[],
            server_pack_file_id=None,
            file_date=None,
        )
        options = UpdateOptions(
            server_dir=server_dir,
            modpack_project_id=0,
            modpack_file_id=modpack_file.id,
            minecraft_version=minecraft_version,
            use_server_pack=True,
            remove_missing=remove_missing,
            dry_run=dry_run,
        )
        state = ServerState.load(server_dir)
        with zipfile.ZipFile(archive_path) as zf:
            return self._apply_server_pack(zf, options, state, modpack_file)

    def update_from_local_curseforge_export(
        self,
        server_dir: Path,
        archive_path: Path,
        minecraft_version: str | None = None,
        remove_missing: bool = False,
        dry_run: bool = False,
    ) -> UpdateResult:
        if self.client is None:
            raise CurseForgeError("CurseForge client is required for CurseForge export ZIP updates")
        server_dir = server_dir.resolve()
        mods_dir = server_dir / "mods"
        archive_path = archive_path.resolve()
        if not archive_path.exists():
            raise CurseForgeError(f"Local CurseForge export not found: {archive_path}")
        if not dry_run:
            server_dir.mkdir(parents=True, exist_ok=True)
            mods_dir.mkdir(parents=True, exist_ok=True)

        digest = self._sha256_file(archive_path)
        with zipfile.ZipFile(archive_path) as zf:
            manifest = self._read_manifest(zf)
            manifest_minecraft = manifest.get("minecraft", {}).get("version")
            if minecraft_version and manifest_minecraft and manifest_minecraft != minecraft_version:
                raise CurseForgeError(
                    f"CurseForge export targets Minecraft {manifest_minecraft}, expected {minecraft_version}"
                )
            modpack_file = ModpackFile(
                id=int(digest[:12], 16),
                display_name=manifest.get("name") or archive_path.name,
                file_name=archive_path.name,
                download_url=None,
                release_type=1,
                game_versions=[manifest_minecraft] if manifest_minecraft else [],
                server_pack_file_id=None,
                file_date=None,
            )
            options = UpdateOptions(
                server_dir=server_dir,
                modpack_project_id=0,
                modpack_file_id=modpack_file.id,
                minecraft_version=minecraft_version,
                use_server_pack=False,
                remove_missing=remove_missing,
                dry_run=dry_run,
            )
            state = ServerState.load(server_dir)
            return self._apply_manifest_pack(zf, options, state, modpack_file)

    def _select_modpack_file(self, options: UpdateOptions) -> ModpackFile:
        if self.client is None:
            raise CurseForgeError("CurseForge client is required for CurseForge API updates")
        if options.modpack_file_id:
            return self.client.get_file(options.modpack_project_id, options.modpack_file_id)
        files = self.client.get_files(options.modpack_project_id, options.minecraft_version)
        if not files:
            suffix = f" for Minecraft {options.minecraft_version}" if options.minecraft_version else ""
            raise CurseForgeError(f"No modpack files found{suffix}")
        return files[0]

    def _apply_server_pack(
        self,
        archive: zipfile.ZipFile,
        options: UpdateOptions,
        state: ServerState,
        modpack_file: ModpackFile,
    ) -> UpdateResult:
        server_dir = options.server_dir.resolve()
        planned = self._server_pack_mods(archive)
        manifest = ModpackManifest(
            project_id=options.modpack_project_id,
            file_id=modpack_file.id,
            name=modpack_file.display_name,
            minecraft_version=options.minecraft_version,
            loader=None,
            loader_version=None,
            mods=[
                ModMetadata(mod_id=0, file_id=0, file_name=name, sha256=self._zip_member_sha256(archive, member))
                for name, member in sorted(planned.items())
            ],
        )
        delta = self._server_pack_delta(state, manifest, options.remove_missing)
        existing = state.managed_files
        desired_keys = set(planned)
        existing_keys = set(existing)
        added: list[str] = []
        updated: list[str] = []
        removed: list[str] = []

        if not options.dry_run:
            self._backup_managed_files(server_dir, state)

        for name, member in planned.items():
            destination = server_dir / "mods" / name
            digest = self._zip_member_sha256(archive, member)
            previous = existing.get(name)
            if previous and previous.sha256 == digest and destination.exists():
                continue
            if previous and previous.path != str(Path("mods") / name):
                self._remove_if_exists(server_dir / previous.path, options.dry_run)
            if not options.dry_run:
                self._extract_member_to(archive, member, destination)
            if previous:
                updated.append(name)
            else:
                added.append(name)
            state.managed_files[name] = ManagedFile(
                project_id=0,
                file_id=0,
                path=str(Path("mods") / name),
                sha256=digest,
            )

        if options.remove_missing:
            removable = sorted(existing_keys - desired_keys)
        else:
            removable = []
        for name in removable:
            managed = existing[name]
            self._remove_if_exists(server_dir / managed.path, options.dry_run)
            removed.append(managed.path)
            state.managed_files.pop(name, None)

        state.modpack_project_id = options.modpack_project_id
        state.modpack_file_id = modpack_file.id
        if not options.dry_run:
            state.save(server_dir)

        return UpdateResult(modpack_file, "server-pack", sorted(added), sorted(updated), removed, [], delta)

    def _apply_manifest_pack(
        self,
        archive: zipfile.ZipFile,
        options: UpdateOptions,
        state: ServerState,
        modpack_file: ModpackFile,
    ) -> UpdateResult:
        if self.client is None:
            raise CurseForgeError("CurseForge client is required for manifest-based updates")
        manifest = self._read_manifest(archive)
        manifest_minecraft = manifest.get("minecraft", {}).get("version")
        if options.minecraft_version and manifest_minecraft and manifest_minecraft != options.minecraft_version:
            raise CurseForgeError(
                f"Modpack manifest targets Minecraft {manifest_minecraft}, expected {options.minecraft_version}"
            )
        files = [item for item in manifest.get("files", []) if item.get("required", True)]
        server_dir = options.server_dir.resolve()
        existing = state.managed_files
        desired_keys: set[str] = set()
        added: list[str] = []
        updated: list[str] = []
        skipped: list[str] = []
        desired_manifest = self._manifest_to_model(options.modpack_project_id, modpack_file, manifest)
        from .delta import DeltaEngine

        delta = DeltaEngine().calculate(state, desired_manifest, options.remove_missing)

        if options.dry_run:
            return UpdateResult(
                modpack_file,
                "manifest",
                sorted(item.file_name for item in delta.added),
                sorted(item.file_name for _, item in delta.updated),
                sorted(item.file_name for item in delta.removed),
                [],
                delta,
            )

        if not options.dry_run:
            self._backup_managed_files(server_dir, state)

        with tempfile.TemporaryDirectory(prefix="cf2amp-files-") as tmp:
            tmp_path = Path(tmp)
            for item in files:
                project_id = int(item["projectID"])
                file_id = int(item["fileID"])
                key = str(project_id)
                desired_keys.add(key)
                previous = existing.get(key)
                if previous and previous.file_id == file_id and (server_dir / previous.path).exists():
                    continue
                try:
                    cf_file = self.client.get_file(project_id, file_id)
                    target_name = self._safe_jar_name(cf_file.file_name, project_id, file_id)
                    download_to = tmp_path / target_name
                    self._download_file(project_id, cf_file, download_to)
                except CurseForgeError as exc:
                    skipped.append(f"{project_id}:{file_id} ({exc})")
                    continue

                if previous:
                    self._remove_if_exists(server_dir / previous.path, options.dry_run)
                if not options.dry_run:
                    shutil.copy2(download_to, server_dir / "mods" / target_name)
                state.managed_files[key] = ManagedFile(
                    project_id=project_id,
                    file_id=file_id,
                    path=str(Path("mods") / target_name),
                    sha256=self._sha256_file(download_to),
                )
                if previous:
                    updated.append(target_name)
                else:
                    added.append(target_name)

        removed: list[str] = []
        if options.remove_missing:
            removable = sorted(set(existing) - desired_keys)
        else:
            removable = []
        for key in removable:
            managed = existing[key]
            self._remove_if_exists(server_dir / managed.path, options.dry_run)
            removed.append(managed.path)
            state.managed_files.pop(key, None)

        state.modpack_project_id = options.modpack_project_id
        state.modpack_file_id = modpack_file.id
        if not options.dry_run:
            state.save(server_dir)

        return UpdateResult(modpack_file, "manifest", sorted(added), sorted(updated), removed, skipped, delta)

    def _download_file(self, project_id: int, cf_file: ModpackFile, destination: Path) -> None:
        if self.client is None:
            raise CurseForgeError("CurseForge client is required for downloads")
        url = cf_file.download_url or self.client.get_download_url(project_id, cf_file.id)
        self.client.download(url, str(destination))

    @staticmethod
    def _read_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
        try:
            with archive.open("manifest.json") as handle:
                return json.loads(handle.read().decode("utf-8"))
        except KeyError as exc:
            raise CurseForgeError("Modpack archive does not contain manifest.json") from exc

    @staticmethod
    def _manifest_to_model(
        project_id: int,
        modpack_file: ModpackFile,
        manifest: dict[str, Any],
    ) -> ModpackManifest:
        minecraft = manifest.get("minecraft", {})
        loaders = minecraft.get("modLoaders", [])
        loader_id = loaders[0].get("id") if loaders else None
        loader = None
        loader_version = None
        if loader_id and "-" in loader_id:
            loader, loader_version = loader_id.split("-", 1)
        elif loader_id:
            loader = loader_id
        return ModpackManifest(
            project_id=project_id,
            file_id=modpack_file.id,
            name=manifest.get("name") or modpack_file.display_name,
            minecraft_version=minecraft.get("version"),
            loader=loader,
            loader_version=loader_version,
            mods=[
                ModMetadata(
                    mod_id=int(item["projectID"]),
                    file_id=int(item["fileID"]),
                    file_name=f"{item['projectID']}-{item['fileID']}.jar",
                )
                for item in manifest.get("files", [])
                if item.get("required", True)
            ],
        )

    @staticmethod
    def _server_pack_mods(archive: zipfile.ZipFile) -> dict[str, str]:
        mods: dict[str, str] = {}
        for member in archive.namelist():
            normalized = member.replace("\\", "/")
            if normalized.endswith("/") or "/mods/" not in f"/{normalized}":
                continue
            name = Path(normalized).name
            if name.lower().endswith(".jar"):
                mods[name] = member
        if not mods:
            raise CurseForgeError("Server pack archive contains no mods/*.jar files")
        return mods

    @staticmethod
    def _server_pack_delta(
        state: ServerState,
        desired: ModpackManifest,
        remove_missing: bool,
    ) -> DeltaPlan:
        current = {
            Path(item.path).name: ModMetadata(
                mod_id=0,
                file_id=0,
                file_name=Path(item.path).name,
                sha256=item.sha256,
            )
            for item in state.managed_files.values()
        }
        desired_by_name = {item.file_name: item for item in desired.mods}
        added: list[ModMetadata] = []
        updated: list[tuple[ModMetadata, ModMetadata]] = []
        unchanged: list[ModMetadata] = []
        for name, desired_mod in desired_by_name.items():
            current_mod = current.get(name)
            if current_mod is None:
                added.append(desired_mod)
            elif current_mod.sha256 != desired_mod.sha256:
                updated.append((current_mod, desired_mod))
            else:
                unchanged.append(desired_mod)
        removed = []
        if remove_missing:
            removed = [current[name] for name in sorted(set(current) - set(desired_by_name))]
        return DeltaPlan(added=added, updated=updated, removed=removed, unchanged=unchanged)

    @staticmethod
    def _extract_member_to(archive: zipfile.ZipFile, member: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, open(destination, "wb") as target:
            shutil.copyfileobj(source, target)

    @staticmethod
    def _zip_member_sha256(archive: zipfile.ZipFile, member: str) -> str:
        digest = hashlib.sha256()
        with archive.open(member) as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _safe_jar_name(file_name: str, project_id: int, file_id: int) -> str:
        base = Path(file_name).name
        if not base.lower().endswith(".jar"):
            base = f"{project_id}-{file_id}.jar"
        return base

    @staticmethod
    def _remove_if_exists(path: Path, dry_run: bool) -> None:
        if dry_run or not path.exists():
            return
        path.unlink()

    @staticmethod
    def _backup_managed_files(server_dir: Path, state: ServerState) -> None:
        if not state.managed_files:
            return
        backup_dir = server_dir / "backups" / "cf2amp-last"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        for managed in state.managed_files.values():
            source = server_dir / managed.path
            if source.exists() and source.is_file():
                target = backup_dir / managed.path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
