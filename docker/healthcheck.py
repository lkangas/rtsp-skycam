#!/usr/bin/env python
"""Container healthcheck: fail if the last captured frame is too old.

The capturer writes the epoch of its most recent good frame to the heartbeat
file every second. A stale (or missing) value means the stream is dead or the
process is wedged -> report unhealthy. Combined with `restart: unless-stopped`
and the capturer's own hard-stall exit, the container self-heals.
"""
import os
import sys
import time

HEARTBEAT = os.environ.get("SKYCAM_HEARTBEAT", "/run/skycam/heartbeat")
MAX_AGE = float(os.environ.get("SKYCAM_HEALTH_MAX_AGE", "90"))

try:
    last = float(open(HEARTBEAT).read().strip() or 0)
except (OSError, ValueError):
    sys.exit(1)

sys.exit(0 if (time.time() - last) < MAX_AGE else 1)
