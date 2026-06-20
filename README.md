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
