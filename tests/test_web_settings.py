from __future__ import annotations

import json
from pathlib import Path

from cf2amp_web.settings import SettingsStore, WebSettings


def test_saved_server_dir_wins_over_environment_default(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "cf2amp-web.json"
    settings = WebSettings(
        server_dir="/home/amp/.ampdata/instances/ModpackUpdateTestjustcreate201/Minecraft",
        amp_instances_dir="/home/amp/.ampdata/instances",
    )
    config_path.write_text(json.dumps(settings.__dict__), encoding="utf-8")
    monkeypatch.setenv("SERVER_DIR", "/home/amp/.ampdata/instances")
    monkeypatch.setenv("AMP_INSTANCES_DIR", "/home/amp/.ampdata/instances")

    loaded = SettingsStore(config_path).load()

    assert loaded.server_dir == "/home/amp/.ampdata/instances/ModpackUpdateTestjustcreate201/Minecraft"
    assert loaded.amp_instances_dir == "/home/amp/.ampdata/instances"


def test_environment_server_dir_seeds_first_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SERVER_DIR", "/home/amp/.ampdata/instances")

    loaded = SettingsStore(tmp_path / "missing.json").load()

    assert loaded.server_dir == "/home/amp/.ampdata/instances"
