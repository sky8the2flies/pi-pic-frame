# Pi Picture Frame

Python digital picture frame for Raspberry Pi. Photos come from a self-hosted [Immich](https://immich.app/) instance running on the same Pi (or anywhere on your network).

Why Immich: Google Photos deprecated third-party library access on March 31, 2025 (all `photoslibrary.*` scopes return 403). Immich runs locally, gives full control, and has a mobile app for auto-backup.

## Features

- Fullscreen HDMI slideshow with `fit + blurred background`, `fit`, or `crop` modes
- Configurable crossfade between slides
- SD-card local cache with disk-usage cap
- Dashboard web UI with optional bearer-token auth
- WSGI (waitress) served, systemd-friendly, and Dockerized
- Graceful SIGINT/SIGTERM shutdown

## 1) Install Immich on the Pi

See [`deploy/immich/README.md`](deploy/immich/README.md).

Short version:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER" && newgrp docker
mkdir -p /opt/immich && cd /opt/immich
wget -O docker-compose.yml https://github.com/immich-app/immich/releases/latest/download/docker-compose.yml
wget -O .env https://github.com/immich-app/immich/releases/latest/download/example.env
# edit .env: UPLOAD_LOCATION, DB_DATA_LOCATION, DB_PASSWORD, TZ
docker compose up -d
```

Open `http://<pi-ip>:2283`, create the admin account, upload photos (or install the Immich mobile app).

Then in Immich → Account → API Keys → create a key for the picture frame with the following permissions:

- `asset.read`
- `asset.download`
- `album.read`
- `server.ping`

## 2) Install the picture frame

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

## 3) Configure

```bash
cp config.example.toml config.toml
mkdir -p data/cache
```

You can fill in Immich credentials via the web UI, or edit `config.toml` directly.

## 4) Run

All-in-one runtime (display + background sync + web dashboard):

```bash
picture-frame-app --config config.toml
```

Or run components separately:

```bash
picture-frame-sync --config config.toml
picture-frame-display --config config.toml
picture-frame-web --config config.toml            # web only
picture-frame-headless --config config.toml       # web + background sync, no display
```

Common flags:

- `--log-level {DEBUG,INFO,WARNING,ERROR}`
- `--host 0.0.0.0`, `--port 8080` — override web binding
- `PICTURE_FRAME_LOG_LEVEL` env var wins if set

Every process handles `SIGINT`/`SIGTERM` for a clean shutdown.

## 5) Use the dashboard

Open `http://<pi-ip>:8080/`. The dashboard has four tabs:

- **Dashboard** — pause/resume, next/previous, sync now, cached-photo stats
- **Immich** — base URL + API key
- **Albums** — multi-select the albums you want on the frame
- **Display** — slide duration, transition seconds, fit mode

If `[web].auth_token` is set, the UI prompts once for the token; it's stored in `localStorage` and sent as `Authorization: Bearer <token>` on every API call.

## Web API

Public:

- `GET /` — dashboard
- `GET /health` — liveness
- `GET /auth/config` — `{"auth_required": bool}`

Protected (require `Authorization: Bearer <token>` when `auth_token` is set):

- `GET /status`
- `POST /config/immich` — `{"base_url": "...", "api_key": "..."}`
- `GET /immich/albums`
- `POST /config/albums` — `{"albums": ["id1", ...], "sync_now": false}`
- `POST /config/display` — `{"slide_seconds": 20, "transition_seconds": 0.8, "mode": "fit_blur"}`
- `POST /sync`
- `POST /control/pause`, `/control/resume`, `/control/next`, `/control/previous`
- `POST /stop` (requires `X-Allow-Stop: true`)

## Cache behavior

- Photos live under `cache.directory`; metadata in `cache.metadata_file`.
- Downloads never exceed `cache.max_disk_usage_percent` (default 80%) nor drop below `cache.min_free_space_mb`.
- Oldest cached images are evicted only when new downloads need the space.
- Failed downloads are logged and counted in the sync stats.

## Test on Mac / any Docker host

`docker-compose.yml` at the repo root spins up Immich plus the picture-frame headless service (containers on Mac can't drive the host screen, so the display runs natively).

```bash
cp .env.example .env
docker compose up --build -d
```

Then:

- Immich UI: `http://localhost:2283` (create admin, upload photos)
- Picture frame dashboard: `http://localhost:8080/`
  - Base URL: `http://immich-server:2283` (matches `config.toml`)
  - Paste the API key you created in Immich
  - Pick albums, save, sync

Optional native display on the host (talks to the same cache):

```bash
picture-frame-display --config config.toml
```

Tear down:

```bash
docker compose down
rm -rf immich-data data
```

## Raspberry Pi startup with systemd

```bash
sudo cp deploy/picture-frame-renderer.service /etc/systemd/system/
sudo cp deploy/picture-frame-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now picture-frame-renderer.service picture-frame-web.service
```

Adjust `User`, `WorkingDirectory`, `ExecStart`, and config paths in the service files.
