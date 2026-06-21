# cf2amp-serverupdater

Automation tool and implementation prototype for updating Minecraft servers from CurseForge modpacks on Ubuntu or in Docker.

The updater prefers CurseForge server packs, computes a deterministic mod delta, backs up the server before mutation, writes a JSON report, and can restore backups for rollback. The full architecture and operational runbook live in [docs/DESIGN.md](docs/DESIGN.md).

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install .
export CURSEFORGE_API_KEY="your-key"
cf2amp run --config config/example.config.yaml
```

## Direct CLI

```bash
cf2amp search "All the Mods 10"
cf2amp update --server-dir /opt/minecraft/server --modpack-id 925200 --minecraft-version 1.21.1
```

## Without CurseForge API Access

If you only have a CurseForge author token and it returns `403` against the
Core API, download the CurseForge server-pack ZIP manually and apply it locally:

```bash
cf2amp apply-server-pack \
  --server-dir /opt/minecraft/server \
  --archive /opt/cf2amp/packs/latest-server-pack.zip \
  --minecraft-version 1.21.1
```

Config-driven local ZIP mode:

```yaml
source:
  type: "localServerPack"
  path: "./packs/latest-server-pack.zip"
serverDir: "/server"
minecraftVersion: "1.21.1"
```

CurseForge Share/Export ZIPs are different from server packs. They contain
`manifest.json` and `overrides/`, but usually no `mods/*.jar` files. cf2amp can
apply them with a CurseForge Core API key by resolving the manifest's referenced
mods and downloading only the required delta.

## Fallback Sources

Some CurseForge files return `403` through the Core API. For those cases, add
fallback sources in the web UI as JSON. CurseForge remains the primary source;
fallbacks are only used for matching `projectID`/`fileID` entries that cannot be
resolved through CurseForge.

```json
[
  {
    "curseforgeProjectId": 448233,
    "provider": "modrinth",
    "project": "entityculling"
  },
  {
    "curseforgeProjectId": 676721,
    "provider": "github",
    "repo": "Create-Aeronautics/Create-Aeronautics",
    "assetPattern": "*1.21.1*.jar"
  },
  {
    "curseforgeProjectId": 123456,
    "curseforgeFileId": 789000,
    "provider": "url",
    "url": "https://example.invalid/mod.jar",
    "fileName": "mod.jar"
  },
  {
    "curseforgeProjectId": 433760,
    "provider": "ignore",
    "reason": "client-only"
  }
]
```

`provider: "modrinth"` chooses the latest version matching the manifest's
Minecraft version and loader. `provider: "github"` reads the latest GitHub
release and downloads the first JAR asset matching `assetPattern`. Use
`provider: "ignore"` for client-only or resource-pack entries that should not be
installed on the server. Use `curseforgeFileId` when one CurseForge project
needs different fallback sources for different files.

## Web UI

Run the local admin interface on port `8080`:

```bash
docker compose -f docker-compose.web.yml up -d
```

Local Python run:

```bash
pip install .
cf2amp-web
```

The web app supports AMP instance scanning, settings management, server-pack ZIP
uploads, update previews, live update logs, backup listing, and rollback jobs.

## Testing

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

## Docker

```bash
docker build -t cf2amp .
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e CURSEFORGE_API_KEY="$CURSEFORGE_API_KEY" \
  -v "$PWD/config/example.config.yaml:/config/config.yaml:ro" \
  -v "/opt/minecraft/server:/server" \
  cf2amp run --config /config/config.yaml
```

## GitHub Container Registry

The repository includes a GitHub Actions workflow based on `plan3t/classroomfe`.
Pushes to `main` or `develop` publish Docker images to:

```text
ghcr.io/plan3t/cf2amp-serverupdater
```

Manual workflow runs can create a GitHub release and versioned image tag:

```bash
docker pull ghcr.io/plan3t/cf2amp-serverupdater:latest
```

Deployment with the published image:

```bash
docker compose -f docker-compose.deploy.yml run --rm cf2amp
```

For a fuller Ubuntu server setup with Compose and optional systemd timer, see
[deploy/ubuntu/README.md](deploy/ubuntu/README.md).

## Rollback

```bash
cf2amp rollback --server-dir /server --backup-dir /server/backups/cf2amp/20260620-120000
```

## Prototype Status

This is a runnable prototype with production-oriented seams for validation, orchestration, and observability. Before using it on a live server, test against a copy of your server directory and decide whether `removeMissing` should remain disabled.
