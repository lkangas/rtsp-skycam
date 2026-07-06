# Deploying on fresnel

Runbook for the Intel NUC (`fresnel`, Ubuntu x86-64). Assumes Docker Engine +
the Compose plugin are installed.

## 1. Prerequisites on the camera

- RTSP enabled, with a **Tapo "camera account"** (created in the Tapo app under
  *Advanced Settings → Camera Account*). The TP-Link cloud login does **not**
  work for RTSP.
- Note the camera's LAN IP and that account's username/password.
- `birdnet-go` already uses `stream2` (audio). This deployment uses **one** more
  RTSP session (`stream1` by default). If the Tapo refuses the extra connection,
  either point this at `stream2` too (`CAMERA_STREAM=stream2`) or check the
  camera's max-client setting.

## 2. Get the code

```bash
git clone git@github.com:lkangas/rtsp-skycam.git
cd rtsp-skycam
git submodule update --init          # pinned pnuu/sky-cam-cv (peak-hold source)
```

## 3. Configure

```bash
cp .env.example .env
$EDITOR .env                         # camera creds, real LAT/LON/ELEVATION, tuning
```

The real coordinates go **only** in `.env` (gitignored) — this repo is public.

## 4. Data directory permissions

The containers run as uid 1000. The repo ships a tracked `data/` dir, so after a
clone it's owned by *you* (uid 1000 on a standard single-user Ubuntu) and writes
just work — no action needed.

If you ever see the capturer crash-loop on `PermissionError: '/data/day'` (e.g.
Docker pre-created `./data` as root before the dir existed), fix ownership with a
one-shot root container (no sudo needed) and restart:

```bash
docker run --rm -v "$PWD/data:/data" python:3.13-slim chown -R 1000:1000 /data
docker compose restart capturer
```

## 5. Launch

```bash
docker compose up -d --build
```

Two services start: `skycam-capturer` (captures frames) and `skycam-assembler`
(builds timelapses + prunes).

## 6. First-run verification

```bash
docker compose ps                    # both Up; capturer becomes healthy in ~90s
docker compose logs -f capturer      # expect: "stream opened", "[mode] -> day/night", "[save] ..."
ls -R data/                          # frames appear under data/day/<date>/ or data/night/<date>/
docker inspect --format '{{.State.Health.Status}}' skycam-capturer
```

An image should land every `INTERVAL` seconds (15 s). Day → single frames;
night → peak-hold stacks. Timelapses appear under `data/video/{day,night}/`
after a session goes quiet (≈ after dusk / dawn).

## 7. Operating notes

- **Logs**: `docker compose logs -f capturer` / `... assembler` (rotated, 3×10 MB).
- **Restart / update**:
  ```bash
  git pull && git submodule update --init
  docker compose up -d --build
  ```
- **Self-heal**: a dead stream makes the capturer exit after
  `hard_stall_timeout` (120 s); `restart: unless-stopped` reconnects it. The
  healthcheck reflects last-frame freshness.
- **Polar day**: near midsummer at high latitude the sun never drops below
  `SUN_LIMIT`, so night mode never triggers — only day frames/timelapses. This
  is expected, not a fault.
- **Disk**: frames are pruned after `FRAME_RETENTION_DAYS` (default 14); videos
  kept per `VIDEO_RETENTION_DAYS` (default 0 = forever). Watch the `./data`
  mount on the NUC SSD.
- **CPU**: full-res `stream1` peak-hold is light on an i5, but if it runs hot,
  set `CAMERA_STREAM=stream2` and rebuild.

## 8. Teardown

```bash
docker compose down                  # keep ./data
docker compose down -v               # also drop the numba-cache volume
```
