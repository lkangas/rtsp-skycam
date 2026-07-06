# syntax=docker/dockerfile:1
FROM python:3.13-slim

# System libs:
#   ffmpeg        - timelapse assembler CLI (Step 5) + codecs
#   gettext-base  - envsubst, to render the config from .env
#   tini          - minimal init (signal forwarding + zombie reaping) as PID 1
#   libgomp1      - OpenMP runtime for numba parallel=True
#   libglib2.0-0  - required by opencv-python-headless
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        gettext-base \
        tini \
        libgomp1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Python deps first, so the (slow) wheel install layer caches across code edits.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Application.
COPY src/ /app/src/
COPY config/ /app/config/
COPY docker/ /app/docker/
RUN chmod +x /app/docker/entrypoint.sh

# Non-root runtime user; pre-create the writable dirs it needs (heartbeat,
# numba cache, and the data mountpoint) since /run and / are root-owned.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin skycam \
    && mkdir -p /run/skycam /cache /data \
    && chown -R skycam:skycam /run/skycam /cache /data

ENV PYTHONUNBUFFERED=1 \
    NUMBA_CACHE_DIR=/cache \
    # Force RTSP over TCP and time out reads after 5 s (microseconds) so a
    # network stall surfaces as a read error the reader can recover from,
    # rather than blocking forever.
    OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp|timeout;5000000"

WORKDIR /app
USER skycam

# Liveness = freshness of the last captured frame (heartbeat holds its epoch).
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python", "/app/docker/healthcheck.py"]

ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker/entrypoint.sh"]
