# rtsp-skycam

Dockerized **24 h sky timelapse** from a TP-Link Tapo (or any) RTSP camera. Built
on the peak-hold stacking core from
[pnuu/sky-cam-cv](https://github.com/pnuu/sky-cam-cv).

A single process holds one RTSP connection and saves an image every 15 s:

- **Day** (sun up) → the latest single frame.
- **Night** (sun below the limit) → a 15 s **peak-hold stack** (meteors + aurora).

Twice a day it assembles the frames into a **day timelapse** and a **night
timelapse** with ffmpeg. One camera connection total, so it coexists cleanly with
another consumer (e.g. birdnet-go) already reading the camera's stream2.

Runs on any x86-64 Linux host with Docker. Image base:
`python:3.13-slim` + `opencv-python-headless` + `ffmpeg`.

## Status

✅ **Deployed and capturing** `stream1` from the camera, healthy, frames landing
under `data/`. All core steps done (see [PLAN.md](PLAN.md) for the full design):

- ✅ Repo, plan & conventions
- ✅ Upstream vendored + deps
- ✅ Capture core (`src/`) — day/night single-consumer loop
- ✅ Container (`Dockerfile`, entrypoint, healthcheck)
- ✅ Orchestration (`docker-compose.yml`, self-heal on stall)
- ✅ Timelapse assembler + retention (`src/assemble.py`)

**To deploy** — see [DEPLOY.md](DEPLOY.md) for the full runbook and first-run
verification. Config surface: [.env.example](.env.example).

## Deploy

Full runbook (camera prep, verification, ops notes): **[DEPLOY.md](DEPLOY.md)**.
The short version:

```bash
git clone git@github.com:lkangas/rtsp-skycam.git && cd rtsp-skycam
git submodule update --init          # pulls pinned pnuu/sky-cam-cv (peak-hold source)
cp .env.example .env && $EDITOR .env # fill camera creds, location, tuning
docker compose up -d --build
```

## Optional: serve the latest frame

An opt-in `web` service (its own container) serves the most recent frame plus a
minimal live viewer, so you can put it behind your own reverse proxy or tunnel —
there's no machine-specific config in the repo. On `127.0.0.1:8092` it exposes:

- `GET /latest.jpg` — the current frame (`Cache-Control: no-cache` + ETag)
- `GET /ws` — a WebSocket that emits `{"type":"imageUpdate"}` on every new frame
- `GET /` — a viewer: the frame scaled to the viewport, refreshed live over the
  WebSocket

Enable it with `COMPOSE_PROFILES=hosting` in `.env` (or
`docker compose --profile hosting up -d`), then point your proxy/tunnel at
`:8092`. The `{"type":"imageUpdate"}` signal is also exactly what the
[Komakallio panel](https://github.com/komakallio/panel)'s `push_ws` consumes.

## Performance

The night peak-hold is the one heavy path, and it's tuned to stay light:

- **Fused peak-hold kernel** ([src/stacking.py](src/stacking.py)) folds the
  per-channel brightness sum into the pixel loop, dropping a separate
  `np.sum(axis=-1)` pass + a 4 MP allocation per frame — ~3× faster and
  bit-for-bit identical to the two-pass form.
- **`NUMBA_NUM_THREADS=1`** (default) — the stack is memory-bandwidth bound, so
  one thread runs faster *and* cooler than all cores (it sustains far above the
  stream rate here). Tunable in `.env`.

Measured on the reference host (Intel i7-10710U, 4 MP H.264 @ ~22 fps):

| capturer CPU | before | after |
|---|---|---|
| **night** (peak-hold) | ~526% (≈5.3 cores) | **~90%** (≈0.9 core) |
| **day** (single frame) | ~66% | ~66% |

No frames are dropped — the fused kernel sustains ~160 fps versus the ~15 fps
needed. Profiling notes: **decode is cheap** (~22% of a core in software), and
hardware VAAPI/Quick Sync decode measured *worse* for this low-bitrate stream, so
it isn't used; the remaining cost is the per-frame decode + colour-convert path.
