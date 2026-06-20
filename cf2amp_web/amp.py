from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AmpInstance:
    name: str
    instance_dir: str
    server_dir: str
    detected: bool
    notes: list[str]


class AmpScanner:
    def __init__(self, roots: list[Path]) -> None:
        self.roots = roots

    def scan(self) -> list[AmpInstance]:
        instances: list[AmpInstance] = []
        seen: set[Path] = set()
        for root in self.roots:
            if not root.exists() or not root.is_dir():
                continue
            for child in sorted(item for item in root.iterdir() if item.is_dir()):
                if child in seen:
                    continue
                seen.add(child)
                instances.append(self._inspect_instance(child))
        return instances

    def _inspect_instance(self, instance_dir: Path) -> AmpInstance:
        candidates = [
            instance_dir / "Minecraft",
            instance_dir / "minecraft",
            instance_dir / "Server",
            instance_dir,
        ]
        notes: list[str] = []
        for candidate in candidates:
            if self._looks_like_minecraft_server(candidate):
                return AmpInstance(
                    name=instance_dir.name,
                    instance_dir=str(instance_dir),
                    server_dir=str(candidate),
                    detected=True,
                    notes=notes,
                )
        notes.append("No standard Minecraft server layout detected; verify server path manually.")
        return AmpInstance(
            name=instance_dir.name,
            instance_dir=str(instance_dir),
            server_dir=str(instance_dir),
            detected=False,
            notes=notes,
        )

    @staticmethod
    def _looks_like_minecraft_server(path: Path) -> bool:
        if not path.exists() or not path.is_dir():
            return False
        markers = [
            path / "server.properties",
            path / "mods",
            path / "world",
            path / "eula.txt",
        ]
        if any(marker.exists() for marker in markers):
            return True
        return any(path.glob("*server*.jar"))
