from __future__ import annotations

import zipfile
from pathlib import Path

from cf2amp.config import load_config
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
