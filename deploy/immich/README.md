# Immich on the Pi

Immich runs on the same Raspberry Pi as the picture frame using Docker.

Recommended hardware: Raspberry Pi 5 with 4 GB or 8 GB RAM. Pi 4 (4 GB or 8 GB) also works, though ML jobs are slower.

## 1) Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
newgrp docker
```

Log out/in so the group takes effect.

## 2) Fetch Immich compose files

Always use the latest official files:

```bash
mkdir -p /opt/immich && cd /opt/immich
wget -O docker-compose.yml https://github.com/immich-app/immich/releases/latest/download/docker-compose.yml
wget -O .env https://github.com/immich-app/immich/releases/latest/download/example.env
```

Edit `.env` and set:

- `UPLOAD_LOCATION` (e.g. `/opt/immich/library`)
- `DB_DATA_LOCATION` (e.g. `/opt/immich/postgres`)
- `DB_PASSWORD` to a random string
- `TZ` to your timezone

## 3) Start Immich

```bash
cd /opt/immich
docker compose up -d
```

Web UI: `http://<pi-ip>:2283`

Create the admin account on first visit. Upload some photos or use the mobile app for auto-backup.

## 4) Create API key for the picture frame

- Log into Immich web UI.
- Account settings → API Keys → New API Key.
- Name it `picture-frame`.
- Copy the key value.

Paste the key into the picture frame `/setup` page along with the Immich base URL (usually `http://localhost:2283` when both run on the same Pi).

## Ports

- Immich: `2283`
- Picture frame web control: `8080`

Both services can coexist on the same Pi.
