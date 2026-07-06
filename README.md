# skycam-deploy

Dockerized deployment of [pnuu/sky-cam-cv](https://github.com/pnuu/sky-cam-cv) —
peak-hold sky stacking from a TP-Link Tapo RTSP camera — tuned for deployment on
the host **fresnel**.

Upstream captures an RTSP stream, keeps the brightest pixel per position across a
stack (great for meteors, aurora and star trails), and writes stacked images. It
is gated by sun altitude so it only runs at night.

This repo wraps that app for containerized, hands-off operation (replacing the
upstream cron + bash-watchdog + conda model).

## Status

🚧 **Planning.** See [PLAN.md](PLAN.md) for the deployment design and decisions.
Implementation is intentionally deferred (pending usage-window reset).
