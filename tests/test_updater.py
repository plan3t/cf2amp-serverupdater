from __future__ import annotations

import zipfile
from pathlib import Path

from cf2amp.config import load_config
from cf2amp.curseforge import CurseForgeError, ModpackFile
from cf2amp.delta import DeltaEngine
from cf2amp.models import ModMetadata, ModpackManifest
from cf2amp.state import ManagedFile, ServerState
from cf2amp.updater import ServerUpdater


def test_server_pack_mod_discovery_handles_nested_pack(tmp_path: Path) -> None:
    archive_path = tmp_path / "server.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("overrides/mods/example.jar", b"jar")
        zf.writestr("overrides/config/example.toml", b"config")

    with zipfile.ZipFile(archive_path) as zf:
        assert ServerUpdater._server_pack_mods(zf) == {"example.jar": "overrides/mods/example.jar"}


def test_safe_jar_name_rejects_paths() -> None:
    assert ServerUpdater._safe_jar_name("../bad.jar", 1, 2) == "bad.jar"
    assert ServerUpdater._safe_jar_name("not-a-jar.zip", 1, 2) == "1-2.jar"


def test_delta_engine_tracks_added_updated_and_optional_removals() -> None:
    state = ServerState(
        managed_files={
            "100": ManagedFile(project_id=100, file_id=1, path="mods/a-1.jar"),
            "300": ManagedFile(project_id=300, file_id=1, path="mods/c-1.jar"),
        }
    )
    manifest = ModpackManifest(
        project_id=1,
        file_id=2,
        name="Example",
        minecraft_version="1.21.1",
        loader="forge",
        loader_version="52.0.0",
        mods=[
            ModMetadata(mod_id=100, file_id=2, file_name="a-2.jar"),
            ModMetadata(mod_id=200, file_id=1, file_name="b-1.jar"),
        ],
    )

    plan = DeltaEngine().calculate(state, manifest, remove_missing=True)

    assert [item.file_name for item in plan.added] == ["b-1.jar"]
    assert [(old.file_id, new.file_id) for old, new in plan.updated] == [(1, 2)]
    assert [item.file_name for item in plan.removed] == ["mods/c-1.jar"]


def test_local_curseforge_export_preview_uses_manifest_delta(tmp_path: Path) -> None:
    archive_path = make_curseforge_export(tmp_path)
    server_dir = tmp_path / "server"

    result = ServerUpdater(FakeCurseForgeClient()).update_from_local_curseforge_export(
        server_dir=server_dir,
        archive_path=archive_path,
        minecraft_version="1.21.1",
        dry_run=True,
    )

    assert result.mode == "manifest"
    assert [item.file_name for item in result.delta.added] == ["example.jar"]
    assert not (server_dir / "mods" / "example.jar").exists()


def test_local_curseforge_export_adopts_existing_matching_mods(tmp_path: Path) -> None:
    archive_path = make_curseforge_export(tmp_path)
    server_dir = tmp_path / "server"
    mods_dir = server_dir / "mods"
    mods_dir.mkdir(parents=True)
    (mods_dir / "example.jar").write_bytes(b"jar")

    result = ServerUpdater(FakeCurseForgeClient()).update_from_local_curseforge_export(
        server_dir=server_dir,
        archive_path=archive_path,
        minecraft_version="1.21.1",
    )

    assert result.added == []
    assert [item.file_name for item in result.delta.unchanged] == ["example.jar"]
    assert ServerState.load(server_dir).managed_files["100"].file_id == 200


def test_local_curseforge_export_installs_referenced_mods(tmp_path: Path) -> None:
    archive_path = make_curseforge_export(tmp_path)
    server_dir = tmp_path / "server"

    result = ServerUpdater(FakeCurseForgeClient()).update_from_local_curseforge_export(
        server_dir=server_dir,
        archive_path=archive_path,
        minecraft_version="1.21.1",
    )

    installed = server_dir / "mods" / "example.jar"
    assert result.added == ["example.jar"]
    assert installed.read_bytes() == b"jar"
    assert ServerState.load(server_dir).managed_files["100"].file_id == 200


def test_local_curseforge_export_uses_configured_fallback_source(tmp_path: Path) -> None:
    archive_path = make_curseforge_export(tmp_path)
    server_dir = tmp_path / "server"

    result = ServerUpdater(FailingCurseForgeClient()).update_from_local_curseforge_export(
        server_dir=server_dir,
        archive_path=archive_path,
        minecraft_version="1.21.1",
        fallback_sources=(
            {
                "curseforgeProjectId": 100,
                "curseforgeFileId": 200,
                "provider": "url",
                "url": "https://fallback.invalid/example.jar",
                "fileName": "example.jar",
            },
        ),
    )

    installed = server_dir / "mods" / "example.jar"
    assert result.added == ["example.jar"]
    assert result.skipped == []
    assert installed.read_bytes() == b"fallback-jar"
    assert ServerState.load(server_dir).managed_files["100"].file_id == 200


def test_local_curseforge_export_can_ignore_client_only_manifest_entries(tmp_path: Path) -> None:
    archive_path = make_curseforge_export(tmp_path)
    server_dir = tmp_path / "server"

    result = ServerUpdater(FailingCurseForgeClient()).update_from_local_curseforge_export(
        server_dir=server_dir,
        archive_path=archive_path,
        minecraft_version="1.21.1",
        fallback_sources=(
            {
                "curseforgeProjectId": 100,
                "provider": "ignore",
                "reason": "client-only",
            },
        ),
    )

    assert result.added == []
    assert result.delta.added == []
    assert result.skipped == ["100:200 ignored by fallback policy"]
    assert not (server_dir / "mods" / "example.jar").exists()


def test_minimal_yaml_config_loader(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CURSEFORGE_API_KEY", "secret")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'curseforgeApiKey: "${CURSEFORGE_API_KEY}"',
                "modpackId: 123",
                'minecraftVersion: "1.21.1"',
                'serverDir: "/server"',
                "updatePolicy:",
                "  removeMissing: true",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.curseforge_api_key == "secret"
    assert config.modpack_id == 123
    assert config.update_policy.remove_missing is True


def make_curseforge_export(tmp_path: Path) -> Path:
    archive_path = tmp_path / "client-export.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr(
            "manifest.json",
            """
            {
              "name": "Example Export",
              "minecraft": {
                "version": "1.21.1",
                "modLoaders": [{"id": "neoforge-21.1.233", "primary": true}]
              },
              "files": [
                {"projectID": 100, "fileID": 200, "required": true}
              ],
              "overrides": "overrides"
            }
            """,
        )
        zf.writestr("modlist.html", "<ul></ul>")
        zf.writestr("overrides/config/example.toml", "value = true")
    return archive_path


class FakeCurseForgeClient:
    def get_file(self, mod_id: int, file_id: int) -> ModpackFile:
        assert mod_id == 100
        assert file_id == 200
        return ModpackFile(
            id=file_id,
            display_name="Example",
            file_name="example.jar",
            download_url="https://example.invalid/example.jar",
            release_type=1,
            game_versions=["1.21.1"],
            server_pack_file_id=None,
            file_date=None,
        )

    def download(self, url: str, destination: str) -> None:
        assert url == "https://example.invalid/example.jar"
        Path(destination).write_bytes(b"jar")


class FailingCurseForgeClient:
    def get_file(self, mod_id: int, file_id: int) -> ModpackFile:
        raise CurseForgeError("CurseForge API error 403")

    def download(self, url: str, destination: str) -> None:
        assert url == "https://fallback.invalid/example.jar"
        Path(destination).write_bytes(b"fallback-jar")
