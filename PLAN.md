# Deployment Plan — skycam-deploy

Dockerized deployment based on [pnuu/sky-cam-cv](https://github.com/pnuu/sky-cam-cv)
on host **fresnel**, capturing a **24 h sky timelapse** where night frames are
peak-hold stacks (meteors + aurora) from a Tapo camera.

> Status: **plan only**. Implementation is deferred until the usage window
> resets. This document is the agreed design; code lands in later phases.

---

## 1. Core idea — one consumer, day/night modes

A **single** process holds **one** RTSP connection to the camera and, every
`INTERVAL` seconds (15 s), saves exactly one image:

| Period | Trigger | What's saved |
|---|---|---|
| **Day** | sun **above** `SUN_LIMIT` | the latest single frame (plain grab) |
| **Night** | sun **below** `SUN_LIMIT` | a **peak-hold stack** over the last `INTERVAL` seconds |

Then, **twice a day** (around the sunrise/sunset transitions), a separate step
assembles the accumulated frames with **ffmpeg** into a **day timelapse** and a
**night timelapse** video.

Consequences of this design:

- **Only one camera connection** (plus the existing **birdnet-go** on stream2) →
  **2 sessions total, always**, well under any Tapo limit. No restreamer, no
  concurrency juggling.
- The **night timelapse frames *are* the meteor/aurora captures** — each 15 s
  peak-hold stack serves both purposes.
- We **adapt upstream's capture loop** (fork/patch) rather than running it
  untouched: upstream *exits* in daylight, whereas we switch to plain-frame mode
  and keep running across the day/night boundary. Upstream's **Numba peak-hold
  core is reused verbatim** as the night branch (with attribution).

Confirmed: **Intel NUC i5 / Ubuntu / x86-64**; camera **RTSP already working**;
**full-res stream1** for capture; birdnet-go already reads stream2 audio.

---

## 2. Architecture

Two units, sharing one image and one `./data` volume:

```
capturer   (always-on, 1 RTSP connection)
   every 15 s:
      read frame(s)
      if sun below SUN_LIMIT:  peak-hold stack → save to data/night/<date>/
      else:                    save latest frame → save to data/day/<date>/
   writes a heartbeat for the healthcheck; restarts on stream stall

assembler  (runs ~twice/day, at day↔night transitions)
   ffmpeg data/day/<date>/*.jpg   → data/video/day/<date>.mp4
   ffmpeg data/night/<date>/*.jpg → data/video/night/<date>.mp4
   prune frames/videos past retention
```

The assembler can be a second short-lived container, a cron-like tick inside the
capturer, or triggered by the capturer when it detects a sun transition —
decided at implementation. Either way it's driven off the same sun calc so the
"day" and "night" segments line up with the mode switches.

---

## 3. Target repository layout

```
skycam-deploy/
├── README.md
├── PLAN.md                     ← this file
├── .gitignore
├── .env.example                ← every config/secret knob
├── requirements.txt            ← pinned pip deps
├── Dockerfile                  ← python:3.13-slim + opencv-headless + ffmpeg
├── docker-compose.yml
├── src/
│   ├── capture.py               ← the single consumer (day/night modes)
│   ├── stacking.py              ← peak-hold core reused from upstream (attributed)
│   └── assemble.py              ← ffmpeg timelapse builder + retention sweep
├── config/
│   └── config.yaml.template     ← ${ENV} placeholders
├── upstream/                    ← git submodule → pnuu/sky-cam-cv @ pinned SHA (reference/source)
└── data/                        ← (gitignored) frames + videos, bind-mounted
```

Upstream is kept as a **pinned submodule for reference and attribution**; the
peak-hold logic is lifted into `src/stacking.py` so our loop can call it directly
in the night branch.

---

## 4. Data layout on disk

```
data/
├── day/<YYYY-MM-DD>/<label>_<time>_UTC.jpg          plain frames, one per 15 s
├── night/<YYYY-MM-DD>/<label>_<time>_UTC.jpg        15 s peak-hold stacks
└── video/
    ├── day/<YYYY-MM-DD>.mp4
    └── night/<YYYY-MM-DD>.mp4
```

Night spans midnight; a night is labelled by the **date it began** (evening).
Timestamps in **UTC** (matches upstream); container `TZ=UTC`.

---

## 5. Tuning (proposed defaults, all env-configurable)

| Knob | Proposed | Reason |
|---|---|---|
| `CAMERA_STREAM` | `stream1` (full res) | Detail for meteors/aurora; i5 NUC handles one full-res decode. One connection only, so no bandwidth conflict. |
| RTSP transport | TCP + read timeout (`OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp\|timeout;5000000`) | Reliable Tapo RTSP; a stall becomes a recoverable error, not a hang. |
| `INTERVAL` | 15 s | One saved image per 15 s, day and night — uniform timelapse cadence. |
| Night stack | peak-hold over each 15 s window | Reuses upstream Numba core; catches meteors/aurora within the window. |
| `SUN_LIMIT` | −8° (env) | Darker sky for faint targets. ⚠️ At lat ~68.5° never reached near midsummer (polar day) → night mode simply never triggers; day timelapse continues. Not a bug. |
| `TIMELAPSE_FPS` | 25 | Assembly framerate. 15 s cadence → ~1 min of video per ~6 h of frames. |
| `CAM_LABEL` | env | Filename prefix so captures are self-describing. |
| `location` | from `.env` | Site lat/lon/elev drives the sun calc. |

---

## 6. Robustness (replaces upstream cron + bash watchdog)

- **RTSP read timeout** (above) — root-cause fix for network stalls.
- **Capturer heartbeat file** + Docker `HEALTHCHECK` + `restart: unless-stopped`
  → a wedged capturer is detected and restarted automatically.
- **Self-relaunch on stream error** with short backoff inside `capture.py`.

No PID file needed (one process per container).

---

## 7. Retention

Nightly sweep (in the assembler):

- `FRAME_RETENTION_DAYS` (default 14; `0` = keep) — prune individual JPGs.
- `VIDEO_RETENTION_DAYS` (default 0 = keep forever) — the finished timelapses are
  small; keep them long.

Bounds disk on the NUC SSD while preserving the assembled videos.

---

## 8. Phasing

- **Phase 0 — Repo + plan** ✅ (this commit series).
- **Phase 1 — Capturer** *(after reset)*: `capture.py` single-consumer loop with
  day (frame) / night (peak-hold) modes, `stacking.py` from upstream, config
  template, Dockerfile, compose, `.env`. Goal: images landing in `data/day` and
  `data/night`.
- **Phase 2 — Assembler**: `assemble.py` ffmpeg day/night timelapse builds,
  triggered twice daily.
- **Phase 3 — Robustness + retention**: RTSP timeouts, healthcheck, restart,
  retention sweep.
- **Phase 4 — Off-box upload/sync** *(deferred)*: push videos/frames to NAS/S3.

Each phase is its own commit (or small series).

---

## 9. Inputs needed at implementation time (non-blocking)

Collected into `.env` on fresnel:

1. **Camera**: IP + the Tapo **camera-account** username/password (RTSP already
   works, so these exist).
2. **Location**: latitude / longitude / elevation + `CAM_LABEL`.
3. **Tuning confirmation**: `SUN_LIMIT` start value, `INTERVAL` (15 s),
   `TIMELAPSE_FPS`, retention days.
4. **Deploy path**: how this repo reaches fresnel — add a **git remote** to
   push/pull, or copy over?

---

## 10. Risks / notes

- **Polar day**: near midsummer at high latitude the sun never dips below
  `SUN_LIMIT` → night mode never triggers; only the day timelapse runs. Expected.
- **Night frames are exposures the camera gives us** — a Tapo may switch to IR /
  night mode automatically; the peak-hold stack reflects whatever it outputs.
- **Disk**: 15 s cadence = 4 images/min continuously; retention + watching the
  `./data` mount matter on a small SSD.
- **Numba first-run JIT** adds a few seconds at start; optional `NUMBA_CACHE_DIR`
  volume speeds restarts.
- **birdnet-go coexistence**: unaffected — it keeps its own stream2 session; we
  add exactly one more.
