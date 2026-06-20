from __future__ import annotations

from .models import DeltaPlan, ModMetadata, ModpackManifest
from .state import ServerState


class DeltaEngine:
    def calculate(self, current: ServerState, desired: ModpackManifest, remove_missing: bool) -> DeltaPlan:
        installed = {
            str(item.project_id): ModMetadata(
                mod_id=item.project_id,
                file_id=item.file_id,
                file_name=item.path,
                sha256=item.sha256,
            )
            for item in current.managed_files.values()
        }
        desired_by_id = {str(item.mod_id): item for item in desired.mods}
        added: list[ModMetadata] = []
        updated: list[tuple[ModMetadata, ModMetadata]] = []
        unchanged: list[ModMetadata] = []

        for key, desired_mod in desired_by_id.items():
            current_mod = installed.get(key)
            if current_mod is None:
                added.append(desired_mod)
            elif current_mod.file_id != desired_mod.file_id:
                updated.append((current_mod, desired_mod))
            else:
                unchanged.append(desired_mod)

        removed = []
        if remove_missing:
            removed = [
                installed[key]
                for key in sorted(set(installed) - set(desired_by_id))
            ]

        return DeltaPlan(
            added=sorted(added, key=lambda item: item.file_name),
            updated=sorted(updated, key=lambda item: item[1].file_name),
            removed=sorted(removed, key=lambda item: item.file_name),
            unchanged=sorted(unchanged, key=lambda item: item.file_name),
        )
