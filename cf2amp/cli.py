from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .backup import BackupManager
from .config import load_config
from .curseforge import CurseForgeClient, CurseForgeError
from .models import BackupRecord
from .orchestrator import Orchestrator
from .updater import ServerUpdater, UpdateOptions


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "rollback":
            return rollback(args)
        if args.command == "run":
            return run_config(args)

        api_key = args.api_key or os.environ.get("CURSEFORGE_API_KEY")
        if not api_key:
            parser.error("Set --api-key or CURSEFORGE_API_KEY")

        client = CurseForgeClient(api_key)
        if args.command == "search":
            return search(client, args.query)
        if args.command == "update":
            return update(client, args)
    except (CurseForgeError, RuntimeError, FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cf2amp",
        description="Update a Minecraft server from CurseForge modpacks.",
    )
    parser.add_argument("--api-key", help="CurseForge API key. Defaults to CURSEFORGE_API_KEY.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search", help="Search CurseForge modpacks.")
    search_parser.add_argument("query")

    update_parser = subparsers.add_parser("update", help="Update a server directory.")
    update_parser.add_argument("--server-dir", required=True, type=Path)
    update_parser.add_argument("--modpack-id", required=True, type=int)
    update_parser.add_argument("--modpack-file-id", type=int)
    update_parser.add_argument("--minecraft-version")
    update_parser.add_argument(
        "--client-pack",
        action="store_true",
        help="Do not prefer CurseForge server packs; install from manifest instead.",
    )
    update_parser.add_argument("--dry-run", action="store_true")

    run_parser = subparsers.add_parser("run", help="Run an update from a YAML or JSON config file.")
    run_parser.add_argument("--config", required=True, type=Path)
    run_parser.add_argument("--dry-run", action="store_true")

    rollback_parser = subparsers.add_parser("rollback", help="Restore a backup directory created by cf2amp.")
    rollback_parser.add_argument("--server-dir", required=True, type=Path)
    rollback_parser.add_argument("--backup-dir", required=True, type=Path)
    return parser


def search(client: CurseForgeClient, query: str) -> int:
    matches = client.search_modpacks(query)
    if not matches:
        print("No modpacks found.")
        return 0
    for item in matches:
        print(f"{item['id']}\t{item.get('name', '<unnamed>')}\t{item.get('slug', '')}")
    return 0


def update(client: CurseForgeClient, args: argparse.Namespace) -> int:
    result = ServerUpdater(client).update(
        UpdateOptions(
            server_dir=args.server_dir,
            modpack_project_id=args.modpack_id,
            modpack_file_id=args.modpack_file_id,
            minecraft_version=args.minecraft_version,
            use_server_pack=not args.client_pack,
            dry_run=args.dry_run,
        )
    )
    print(f"Modpack file: {result.modpack_file.display_name} ({result.modpack_file.id})")
    print(f"Mode: {result.mode}")
    print(f"Added: {len(result.added)}")
    for name in result.added:
        print(f"  + {name}")
    print(f"Updated: {len(result.updated)}")
    for name in result.updated:
        print(f"  ~ {name}")
    print(f"Removed: {len(result.removed)}")
    for name in result.removed:
        print(f"  - {name}")
    if result.skipped:
        print(f"Skipped: {len(result.skipped)}")
        for name in result.skipped:
            print(f"  ! {name}")
    print("Delta summary:")
    print(f"  added={len(result.delta.added)} updated={len(result.delta.updated)} removed={len(result.delta.removed)} unchanged={len(result.delta.unchanged)}")
    return 0


def run_config(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if not config.curseforge_api_key:
        raise CurseForgeError("Set curseforgeApiKey in the config or CURSEFORGE_API_KEY")
    client = CurseForgeClient(config.curseforge_api_key)
    report = Orchestrator(client).run(config, dry_run=args.dry_run)
    print(json.dumps(report.to_dict(), indent=2))
    return 0


def rollback(args: argparse.Namespace) -> int:
    backup = BackupRecord(
        backup_id=args.backup_dir.name,
        path=args.backup_dir,
        manifest_file_id=None,
        created_at=args.backup_dir.name,
    )
    BackupManager().restore(args.server_dir, backup)
    print(f"Restored {args.backup_dir} into {args.server_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
