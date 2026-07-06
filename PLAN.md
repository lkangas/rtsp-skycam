# Deployment Plan — skycam-deploy

Dockerized deployment of [pnuu/sky-cam-cv](https://github.com/pnuu/sky-cam-cv) on
host **fresnel**, tuned for **meteor + aurora** capture from a Tapo camera.

> Status: **plan only**. Implementation is deferred until the usage window
> resets. This document is the agreed design; code lands in later phases.

---

## 1. What the upstream app does (and why it shapes the design)

`sky-cam-cv` (Python 3.13) pulls an **RTSP stream** from a Tapo camera and runs
**Numba-accelerated peak-hold stacking** — for each pixel it keeps the brightest
value seen across a stack, which is what makes meteors, fireballs and aurora pop
out of the night sky. Output is one stacked JPG per stack interval.

Key runtime facts that drive our containerization choices:

| Upstream behaviour | Implication for Docker |
|---|---|
| Gated by **sun altitude** (PyEphem): exits immediately if the sun is above `sun_limit`, otherwise runs until sunrise then exits. | Not a long-lived process by itself. We need a **supervisor loop** to re-launch it, replacing cron. |
| Driven by **cron** (`bin/sky-cam-cv.py <config>`) with a **PID file** to prevent overlap. | Cron + PID file become unnecessary — one process per container. The supervisor owns lifecycle. |
| A **bash watchdog** (`bin/sky-cam-cv_wathcdog.sh`) kills the process when a flaky network stalls `VideoCapture.read()`. | Replaced by **RTSP read timeouts + an output-freshness watchdog + Docker healthcheck + `restart: unless-stopped`**. |
| Dependencies via **conda** (`ephem numba pillow py-opencv pyyaml`). | We use **pip + `opencv-python-headless`** on `python:3.13-slim` (your choice) — smaller, no GUI libs. |
| Config is a single **YAML** file; RTSP URL built from `username/password/camera_ip/port/stream`. | Secrets injected at runtime via **`.env` + envsubst** into a rendered config — nothing sensitive baked into the image or committed. |
| Filenames/timestamps in **UTC**; sun calc uses **lat/lon/elevation**. | Container `TZ=UTC`; location comes from `.env`. |

Confirmed target: **Intel NUC, i5, Ubuntu (x86-64)** — full wheel support for
`opencv-python-headless`, `numba`/`llvmlite` on Python 3.13. No ARM caveats.

---

## 2. Target repository layout

```
skycam-deploy/
├── README.md
├── PLAN.md                     ← this file
├── .gitignore
├── .env.example                ← documents every config/secret knob
├── requirements.txt            ← pinned pip deps
├── Dockerfile                  ← python:3.13-slim + opencv-headless
├── docker-compose.yml          ← service, volume, restart, healthcheck
├── config/
│   └── tapo.yaml.template       ← YAML with ${ENV} placeholders
├── docker/
│   ├── entrypoint.sh            ← render config from template, exec supervisor
│   └── supervisor.py            ← re-launch loop + watchdog + retention + heartbeat
├── upstream/                    ← git submodule → pnuu/sky-cam-cv @ pinned SHA
└── data/                        ← (gitignored) captured images, bind-mounted
```

**Upstream is vendored as a pinned git submodule** — we run the author's code
unmodified and update deliberately, rather than forking. No patches to upstream
are required (secrets and RTSP timeouts are handled from the outside).

---

## 3. How it runs in a container

Replacing cron + watchdog with one small supervisor:

```
entrypoint.sh:
  envsubst < config/tapo.yaml.template > /run/tapo.yaml   # inject secrets/location
  exec python docker/supervisor.py

supervisor.py loop:
  while running:
      touch /run/heartbeat                 # for Docker HEALTHCHECK
      run: python upstream/bin/sky-cam-cv.py /run/tapo.yaml
           ├─ daytime  → exits fast        → sleep POLL_INTERVAL, retry
           ├─ sunrise  → exits after night → sleep POLL_INTERVAL, retry
           └─ crash    → exits nonzero      → short backoff, retry
      (watchdog thread) while a capture is active, if no new file appears
           in /data for 3 × STACK_LENGTH seconds → kill child (stream hung),
           loop restarts it
      (once/day) prune /data of files older than RETENTION_DAYS
```

Everything the NUC needs is `docker compose up -d --build`; the container
self-schedules around night/day and self-heals on network hiccups.

---

## 4. Tailoring for **meteors + aurora** (proposed defaults, all env-tunable)

| Knob | Upstream default | Proposed | Reason |
|---|---|---|---|
| `stream` | `stream2` (substream) | **`stream1`** (main, full-res) | Detail matters for faint meteors/aurora; an i5 NUC handles Tapo's ~15fps at full res. Substream is lower-res/heavily compressed. Falls back easily if CPU-bound. |
| RTSP transport | (default UDP) | **TCP + read timeout** via `OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp\|timeout;5000000` | Tapo RTSP is far more reliable over TCP; the timeout turns a network stall into a clean error the supervisor can recover from — the root-cause fix the upstream bash watchdog only mops up after. |
| `stack_length` | 60 s | **60 s** (kept) | Short stacks keep a fireball from washing out and preserve timing; good for both targets. Longer "all-night" summary stacks are a Phase 5 idea. |
| `sun_limit` | −5.0° | **−6° to −9°** (env, start −8) | Darker sky for faint aurora/meteors. ⚠️ At lat ~68.5° the sun never dips low in summer (polar day) → the app will exit every cycle and capture nothing until the dark season. Expected, not a bug. |
| `location` | lat 68.5 / lon 27.5 / elev 170 | **from `.env`** | Your actual site; drives the sun gate. |
| Filename prefix | `c325_north_` | **env `CAM_LABEL`** | So captures are self-describing per camera. |

---

## 5. Add-ons

**Included now (per your selection):**

- **Auto-restart on hang** — layered: RTSP read timeout (prevents most stalls) +
  supervisor output-freshness watchdog + Docker `HEALTHCHECK` reading the
  heartbeat file + `restart: unless-stopped`. Fully replaces the upstream bash
  watchdog and cron re-launch.
- **Retention / cleanup** — nightly prune of `/data` older than `RETENTION_DAYS`
  (default 14; `0` = keep forever) to bound disk on the NUC.

**Deferred to future phases (your call):**

- **Off-box upload/sync** — push each night's captures to a NAS/S3/remote. Left
  as a documented seam (a post-night hook in the supervisor) so it slots in later.
- **Nightly timelapse / all-night summary stack** — per-night video or combined
  peak-hold image.

---

## 6. Phasing

- **Phase 0 — Repo + plan** ✅ (this commit series).
- **Phase 1 — Core dockerization** *(after window reset)*: submodule upstream,
  `requirements.txt`, `Dockerfile`, `config/tapo.yaml.template`, `entrypoint.sh`,
  `supervisor.py` (sun-gated re-launch loop), `docker-compose.yml`, `.env`.
  Goal: container captures stacks at night to `./data`.
- **Phase 2 — Robustness**: RTSP timeouts, freshness watchdog, healthcheck,
  restart policy. Goal: survives network drops unattended.
- **Phase 3 — Retention**: nightly cleanup sweep.
- **Phase 4 — Upload/sync** *(deferred)*.
- **Phase 5 — Timelapse/summary** *(deferred)*.

Each phase is its own commit (or small series) so progress is reviewable.

---

## 7. Inputs needed at implementation time (non-blocking for this plan)

Collected into `.env` on fresnel — none block writing the plan:

1. **Camera**: IP, and the **Tapo "camera account"** username/password (Tapo
   requires creating a dedicated RTSP account in the Tapo app; the main cloud
   login does *not* work for RTSP). Has RTSP been enabled on the camera?
2. **Location**: latitude / longitude / elevation of the site, and `CAM_LABEL`.
3. **Tuning**: confirm `sun_limit` start value, `stack_length`, and `stream1`
   vs `stream2`.
4. **Retention**: `RETENTION_DAYS` (proposed 14).
5. **Deploy path**: how this repo reaches fresnel — add a **git remote** to
   push/pull, or copy over? (We can set a remote whenever you're ready.)

---

## 8. Risks / notes

- **Polar day**: near midsummer at high latitude, `sun_limit` is never reached —
  zero captures by design. Worth remembering before assuming a misconfiguration.
- **CPU**: full-res peak-hold stacking is light but not free; if the i5 runs hot,
  drop to `stream2` or lower framerate. Easy env flip.
- **numba first-run JIT**: adds a few seconds at container start; optionally cache
  via a `NUMBA_CACHE_DIR` volume to speed restarts.
- **Disk**: one JPG per `stack_length` all night; retention + monitoring the
  `./data` mount matter on a small NUC SSD.
