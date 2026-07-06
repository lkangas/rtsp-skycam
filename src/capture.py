#!/usr/bin/env python
"""skycam capturer — a single RTSP consumer with day/night modes.

Every ``interval`` seconds exactly one image is written:

* **day**   (sun above ``sun_limit``): the latest single frame
* **night** (sun below ``sun_limit``): a peak-hold stack over the interval

Images are grouped into per-session folders::

    <base_dir>/day/<session_date>/<label>_<time>_UTC_frame.jpg
    <base_dir>/night/<session_date>/<label>_<time>_UTC_<interval>s_max.jpg

where ``session_date`` is the UTC date on which the current day- or night-session
began, so a night crossing midnight stays in one folder (the evening's date).

One RTSP connection total (coexists with e.g. birdnet-go on the substream). The
night branch reuses the peak-hold kernel from pnuu/sky-cam-cv (see stacking.py).

Usage: ``python capture.py [config.yaml]`` (default: $SKYCAM_CONFIG or
/run/skycam/config.yaml).
"""

import datetime as dt
import os
import queue
import signal
import sys
import threading
import time

import cv2
import ephem
import numpy as np
import yaml
from PIL import Image

from stacking import update_max_stack

DEFAULT_CONFIG = os.environ.get("SKYCAM_CONFIG", "/run/skycam/config.yaml")


def read_config(path):
    with open(path) as fid:
        return yaml.safe_load(fid)


def build_url(stream):
    """Build the RTSP URL from the stream config section."""
    return (
        f'{stream.get("protocol", "rtsp")}://'
        f'{stream["username"]}:{stream["password"]}@'
        f'{stream["camera_ip"]}:{stream.get("port", 554)}/{stream["stream"]}'
    )


def sun_altitude_deg(location, when_utc):
    """Sun altitude in degrees at the given naive-UTC datetime."""
    obs = ephem.Observer()
    obs.lon = "%f" % location["longitude"]
    obs.lat = "%f" % location["latitude"]
    obs.elevation = location["elevation"]
    obs.date = when_utc
    sun = ephem.Sun()
    sun.compute(obs)
    return float(np.rad2deg(float(sun.alt)))


class StreamReader(threading.Thread):
    """Background RTSP reader: keeps frames flowing and reconnects on failure.

    Frames are pushed to a bounded queue (oldest dropped if the consumer ever
    falls behind, which keeps latency and memory bounded). ``last_frame_time``
    is the wall-clock time of the most recent successful read — the liveness
    signal behind the heartbeat / healthcheck.
    """

    def __init__(self, url, maxsize=60):
        super().__init__(daemon=True)
        self._url = url
        self._q = queue.Queue(maxsize=maxsize)
        self._running = False
        self.last_frame_time = 0.0

    def _open(self):
        cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return cap

    def run(self):
        self._running = True
        backoff = 1.0
        cap = None
        while self._running:
            if cap is None or not cap.isOpened():
                if cap is not None:
                    cap.release()
                cap = self._open()
                if not cap.isOpened():
                    print(f"[reader] open failed; retry in {backoff:.0f}s", flush=True)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                print("[reader] stream opened", flush=True)
                backoff = 1.0
            ok, frame = cap.read()
            if not ok:
                print("[reader] read failed; reconnecting", flush=True)
                cap.release()
                cap = None
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            self.last_frame_time = time.time()
            self._put((frame, self.last_frame_time))
        if cap is not None:
            cap.release()

    def _put(self, item):
        try:
            self._q.put_nowait(item)
        except queue.Full:
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(item)
            except queue.Full:
                pass

    def get(self, timeout):
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        self._running = False


def write_heartbeat(path, ts):
    with open(path, "w") as fid:
        fid.write(f"{ts:.0f}\n")


class Capturer:
    def __init__(self, config):
        self._location = config["location"]
        self._interval = float(config["capture"]["interval"])
        self._label = config["capture"]["label"]
        self._base_dir = config["output"]["base_dir"]
        self._heartbeat = config["runtime"]["heartbeat_file"]
        self._stall_timeout = float(config["runtime"].get("stall_timeout", 20))
        self._hard_stall = float(config["runtime"].get("hard_stall_timeout", 120))
        self._url = build_url(config["stream"])

        os.makedirs(os.path.dirname(self._heartbeat), exist_ok=True)

        self._reader = StreamReader(self._url)
        self._running = False

        # Session state: mode + the UTC date the session began.
        self._session_mode = None
        self._session_date = None

    def _resolve_session(self):
        """Return (mode, session_date), starting a new session on mode change."""
        now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        alt = sun_altitude_deg(self._location, now)
        mode = "night" if alt < self._location["sun_limit"] else "day"
        if mode != self._session_mode:
            self._session_mode = mode
            self._session_date = now.strftime("%Y-%m-%d")
            print(
                f"[mode] -> {mode} (sun {alt:.1f} deg, session {self._session_date})",
                flush=True,
            )
        return mode, self._session_date

    def _save(self, mode, session_date, window_start, latest, max_stack):
        if mode == "night" and max_stack is None:
            print("[save] night window had no frames; skipping", flush=True)
            return
        if mode == "day" and latest is None:
            print("[save] day window had no frames; skipping", flush=True)
            return

        ts = dt.datetime.fromtimestamp(window_start, dt.timezone.utc).strftime(
            "%Y-%m-%d_%H%M%S_UTC"
        )
        folder = os.path.join(self._base_dir, mode, session_date)
        os.makedirs(folder, exist_ok=True)

        if mode == "night":
            data, fname = max_stack, f"{self._label}_{ts}_{int(self._interval)}s_max.jpg"
        else:
            data, fname = latest, f"{self._label}_{ts}_frame.jpg"

        # OpenCV is BGR; PIL expects RGB.
        Image.fromarray(data[:, :, ::-1]).save(os.path.join(folder, fname), quality=90)
        print(f"[save] {mode}/{session_date}/{fname}", flush=True)

    def run(self):
        self._running = True
        self._reader.start()
        start = time.time()

        mode, session_date = self._resolve_session()
        window_start = time.time()
        next_save = window_start + self._interval
        max_stack = None
        stack_sum = None
        latest = None
        last_hb = 0.0
        stall_logged = False

        while self._running:
            item = self._reader.get(timeout=1.0)
            now = time.time()

            if item is not None:
                frame, _ = item
                latest = frame
                if mode == "night":
                    if max_stack is None:
                        max_stack = frame.copy()
                        stack_sum = np.zeros(frame.shape[:2], dtype=np.uint16)
                    else:
                        update_max_stack(max_stack, frame, stack_sum)

            # Heartbeat = time of last good frame, written at most once/second.
            if now - last_hb >= 1.0:
                write_heartbeat(self._heartbeat, self._reader.last_frame_time)
                last_hb = now

            # Stall logging (reader handles the actual reconnect).
            lft = self._reader.last_frame_time
            if lft and now - lft > self._stall_timeout:
                if not stall_logged:
                    print(f"[stall] no frame for {now - lft:.0f}s", flush=True)
                    stall_logged = True
            else:
                stall_logged = False

            # Hard stall: exit nonzero so `restart: unless-stopped` restarts us
            # with a clean process/connection. Also covers never connecting on
            # startup (reference the launch time until the first frame arrives).
            reference = lft if lft else start
            if now - reference > self._hard_stall:
                why = "no first frame" if not lft else "stream stalled"
                print(
                    f"[fatal] {why} for {now - reference:.0f}s; exiting for restart",
                    flush=True,
                )
                self._reader.stop()
                sys.exit(1)

            # Window boundary: save and begin the next window.
            if now >= next_save:
                self._save(mode, session_date, window_start, latest, max_stack)
                window_start = now
                next_save = window_start + self._interval
                mode, session_date = self._resolve_session()
                max_stack = None
                stack_sum = None

        self._reader.stop()

    def stop(self, *_):
        print("[main] shutting down", flush=True)
        self._running = False


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG
    config = read_config(config_path)
    capturer = Capturer(config)
    signal.signal(signal.SIGTERM, capturer.stop)
    signal.signal(signal.SIGINT, capturer.stop)
    capturer.run()


if __name__ == "__main__":
    main()
