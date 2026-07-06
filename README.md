# skycam-deploy

Dockerized **24 h sky timelapse** from a TP-Link Tapo RTSP camera, deployed on
host **fresnel**. Built on the peak-hold stacking core from
[pnuu/sky-cam-cv](https://github.com/pnuu/sky-cam-cv).

A single process holds one RTSP connection and saves an image every 15 s:

- **Day** (sun up) → the latest single frame.
- **Night** (sun below the limit) → a 15 s **peak-hold stack** (meteors + aurora).

Twice a day it assembles the frames into a **day timelapse** and a **night
timelapse** with ffmpeg. One camera connection total, so it coexists cleanly with
the **birdnet-go** instance already reading stream2 audio on fresnel.

Target host **fresnel** is an Intel NUC (i5, x86-64, Ubuntu). Image base:
`python:3.13-slim` + `opencv-python-headless` + `ffmpeg`.

## Status

✅ **Live on fresnel** — capturing `stream1` from the Tapo, healthy, frames landing
under `data/`. All core steps done (see [PLAN.md](PLAN.md) for the full design):

- ✅ Repo, plan & conventions
- ✅ Upstream vendored + deps
- ✅ Capture core (`src/`) — day/night single-consumer loop
- ✅ Container (`Dockerfile`, entrypoint, healthcheck)
- ✅ Orchestration (`docker-compose.yml`, self-heal on stall)
- ✅ Timelapse assembler + retention (`src/assemble.py`)

**Next: build & run on fresnel** — see [DEPLOY.md](DEPLOY.md) for the full
runbook and first-run verification. Config surface: [.env.example](.env.example).

## Deploy

Full runbook (camera prep, verification, ops notes): **[DEPLOY.md](DEPLOY.md)**.
The short version:

```bash
git clone git@github.com:lkangas/rtsp-skycam.git && cd rtsp-skycam
git submodule update --init          # pulls pinned pnuu/sky-cam-cv (peak-hold source)
cp .env.example .env && $EDITOR .env # fill camera creds, location, tuning
docker compose up -d --build
```
