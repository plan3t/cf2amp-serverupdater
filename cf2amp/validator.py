from __future__ import annotations

import subprocess
from pathlib import Path

from .models import ModpackManifest


class ValidationError(RuntimeError):
    pass


class Validator:
    def validate_layout(self, server_dir: Path) -> list[str]:
        warnings: list[str] = []
        if not server_dir.exists():
            warnings.append("server directory does not exist yet; it will be created")
        elif not (server_dir / "mods").exists():
            warnings.append("mods directory does not exist yet; it will be created")
        return warnings

    def validate_manifest(self, manifest: ModpackManifest, target_minecraft_version: str | None) -> list[str]:
        warnings: list[str] = []
        if target_minecraft_version and manifest.minecraft_version != target_minecraft_version:
            raise ValidationError(
                f"manifest targets Minecraft {manifest.minecraft_version}, expected {target_minecraft_version}"
            )
        if manifest.loader not in {None, "forge", "fabric", "neoforge", "quilt"}:
            warnings.append(f"unknown loader '{manifest.loader}'")
        return warnings

    def smoke_test(self, server_dir: Path, java_path: str, java_opts: str, seconds: int) -> list[str]:
        jar_candidates = sorted(server_dir.glob("*.jar"))
        if not jar_candidates:
            return ["startup smoke test skipped because no server jar was found"]
        command = [java_path, *java_opts.split(), "-jar", str(jar_candidates[0]), "nogui"]
        try:
            process = subprocess.Popen(
                command,
                cwd=server_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                process.communicate(timeout=seconds)
            except subprocess.TimeoutExpired:
                process.terminate()
                return []
            if process.returncode not in {0, 130, 143}:
                raise ValidationError(f"startup smoke test failed with exit code {process.returncode}")
        except FileNotFoundError:
            return [f"startup smoke test skipped because '{java_path}' was not found"]
        return []
