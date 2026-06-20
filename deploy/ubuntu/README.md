# Ubuntu Docker Deployment

This deployment runs `cf2amp` as a one-shot Docker Compose job. It updates the
server mounted at `SERVER_DIR`, writes backups inside that server directory, and
stores reports under `logs/cf2amp`.

## 1. Install Docker

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

## 2. Create Deployment Directory

```bash
sudo mkdir -p /opt/cf2amp-serverupdater
sudo git clone https://github.com/plan3t/cf2amp-serverupdater.git /tmp/cf2amp-serverupdater
sudo cp -r /tmp/cf2amp-serverupdater/deploy/ubuntu/. /opt/cf2amp-serverupdater/
cd /opt/cf2amp-serverupdater
sudo cp .env.example .env
sudo nano .env
sudo nano config.yaml
```

Set:

- `CURSEFORGE_API_KEY`
- `SERVER_DIR`
- `PUID` and `PGID` to the UID/GID that should own files in the server dir
- `modpackId`
- `minecraftVersion`

Find UID/GID:

```bash
id minecraft
```

## 3. Run Once

```bash
cd /opt/cf2amp-serverupdater
sudo docker compose pull
sudo docker compose run --rm cf2amp
```

## Web Interface

The web UI exposes settings, AMP instance selection, server-pack ZIP uploads,
update preview, live logs, and rollback actions.

```bash
cd /opt/cf2amp-serverupdater
sudo mkdir -p config packs
sudo docker compose -f docker-compose.web.yml pull
sudo docker compose -f docker-compose.web.yml up -d
```

Open:

```text
http://SERVER-IP:8080
```

## Local Server Pack Mode

If you do not have a CurseForge Core API key, download the modpack server ZIP
manually and copy it to the deployment directory:

```bash
sudo mkdir -p /opt/cf2amp-serverupdater/packs
sudo cp ~/Downloads/latest-server-pack.zip /opt/cf2amp-serverupdater/packs/
```

Then edit `/opt/cf2amp-serverupdater/config.yaml`:

```yaml
source:
  type: "localServerPack"
  path: "./packs/latest-server-pack.zip"
serverDir: "/server"
minecraftVersion: "1.21.1"
```

The updater will still create backups, apply only changed server-pack mods, and
write reports, but it will not auto-discover the newest CurseForge version.

If GHCR denies the pull, either make the package public in GitHub Packages or log in:

```bash
echo "YOUR_GITHUB_TOKEN" | sudo docker login ghcr.io -u plan3t --password-stdin
```

## 4. Optional Nightly Timer

```bash
sudo cp cf2amp-update.service /etc/systemd/system/
sudo cp cf2amp-update.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cf2amp-update.timer
systemctl list-timers cf2amp-update.timer
```

Manual timer run:

```bash
sudo systemctl start cf2amp-update.service
journalctl -u cf2amp-update.service -n 100 --no-pager
```

## 5. Rollback

Backups are created under:

```text
$SERVER_DIR/backups/cf2amp/<timestamp>
```

Rollback:

```bash
sudo docker compose run --rm cf2amp rollback \
  --server-dir /server \
  --backup-dir /server/backups/cf2amp/<timestamp>
```
