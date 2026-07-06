# skycam-deploy

Dockerized deployment of [pnuu/sky-cam-cv](https://github.com/pnuu/sky-cam-cv) —
peak-hold sky stacking from a TP-Link Tapo RTSP camera — tuned for deployment on
the host **fresnel**.

Upstream captures an RTSP stream, keeps the brightest pixel per position across a
stack (great for meteors, aurora and star trails), and writes stacked images. It
is gated by sun altitude so it only runs at night.

This repo wraps that app for containerized, hands-off operation (replacing the
upstream cron + bash-watchdog + conda model).

Target host **fresnel** is an Intel NUC (i5, x86-64, Ubuntu). Capture focus:
**meteors + aurora**. Image base: `python:3.13-slim` + `opencv-python-headless`.

## Status

🚧 **Planning.** See [PLAN.md](PLAN.md) for the full deployment design, tuning
choices, and phasing. Config surface is documented in [.env.example](.env.example).
Implementation is intentionally deferred (pending usage-window reset); it will
land phase-by-phase as separate commits.

## Quick deploy (once implemented)

```bash
git clone <this-repo> && cd skycam-deploy
git submodule update --init          # pulls pinned pnuu/sky-cam-cv
cp .env.example .env && $EDITOR .env # fill camera creds, location, tuning
docker compose up -d --build
```
