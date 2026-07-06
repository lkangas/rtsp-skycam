#!/usr/bin/env python
"""Timelapse assembler + retention sweep.

Runs as its own always-on service (same image, different entrypoint). On each
pass it:

1. Assembles each *finished* day/night session folder into an MP4 with ffmpeg.
   A session is "finished" once no new frame has landed for QUIET_PERIOD (i.e.
   the mode has switched), which naturally makes this fire ~twice a day: the day
   video after dusk, the night video after dawn. Videos are (re)built only when
   frames are newer than the existing MP4, so passes are idempotent.
2. Prunes frames older than FRAME_RETENTION_DAYS and videos older than
   VIDEO_RETENTION_DAYS (0 = keep forever) to bound disk on the NUC.

Configuration is read straight from the environment (.env), so this service
needs no rendered config file.

    <base>/day/<date>/*.jpg    -> <base>/video/day/<date>.mp4
    <base>/night/<date>/*.jpg  -> <base>/video/night/<date>.mp4
"""

import glob
import os
import signal
import subprocess
import threading
import time

BASE_DIR = os.environ.get("SKYCAM_DATA_DIR", "/data")
FPS = os.environ.get("TIMELAPSE_FPS", "25")
FRAME_RETENTION_DAYS = int(os.environ.get("FRAME_RETENTION_DAYS", "14"))
VIDEO_RETENTION_DAYS = int(os.environ.get("VIDEO_RETENTION_DAYS", "0"))
ASSEMBLE_INTERVAL = int(os.environ.get("ASSEMBLE_INTERVAL", "3600"))
QUIET_PERIOD = int(os.environ.get("ASSEMBLE_QUIET_PERIOD", "1200"))
MODES = ("day", "night")

_stop = threading.Event()


def log(msg):
    print(f"[assemble] {msg}", flush=True)


def build_video(session_dir, out_path):
    """Assemble *.jpg in session_dir into out_path (atomic replace)."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp = out_path + ".tmp.mp4"
    # Glob input reads the JPGs in alphabetical = chronological order (the
    # filename timestamps sort correctly).
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", str(FPS),
        "-pattern_type", "glob", "-i", "*.jpg",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
        tmp,
    ]
    subprocess.run(cmd, cwd=session_dir, check=True)
    os.replace(tmp, out_path)


def assemble_pass():
    for mode in MODES:
        mode_dir = os.path.join(BASE_DIR, mode)
        if not os.path.isdir(mode_dir):
            continue
        for session_dir in sorted(glob.glob(os.path.join(mode_dir, "*"))):
            if not os.path.isdir(session_dir):
                continue
            frames = glob.glob(os.path.join(session_dir, "*.jpg"))
            if not frames:
                continue
            newest = max(os.path.getmtime(f) for f in frames)
            # Still being written -> leave it for a later pass.
            if time.time() - newest < QUIET_PERIOD:
                continue
            session = os.path.basename(session_dir)
            out_path = os.path.join(BASE_DIR, "video", mode, f"{session}.mp4")
            if os.path.exists(out_path) and os.path.getmtime(out_path) >= newest:
                continue  # already up to date
            try:
                log(f"building {mode}/{session}.mp4 from {len(frames)} frames")
                build_video(session_dir, out_path)
            except (subprocess.CalledProcessError, OSError) as exc:
                log(f"FAILED {mode}/{session}: {exc}")


def prune_pass():
    now = time.time()
    if FRAME_RETENTION_DAYS > 0:
        cutoff = now - FRAME_RETENTION_DAYS * 86400
        for mode in MODES:
            for frame in glob.glob(os.path.join(BASE_DIR, mode, "*", "*.jpg")):
                try:
                    if os.path.getmtime(frame) < cutoff:
                        os.remove(frame)
                except OSError:
                    pass
            # Drop now-empty session dirs.
            for session_dir in glob.glob(os.path.join(BASE_DIR, mode, "*")):
                if os.path.isdir(session_dir) and not os.listdir(session_dir):
                    try:
                        os.rmdir(session_dir)
                    except OSError:
                        pass
    if VIDEO_RETENTION_DAYS > 0:
        cutoff = now - VIDEO_RETENTION_DAYS * 86400
        for video in glob.glob(os.path.join(BASE_DIR, "video", "*", "*.mp4")):
            try:
                if os.path.getmtime(video) < cutoff:
                    os.remove(video)
            except OSError:
                pass


def main():
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    signal.signal(signal.SIGINT, lambda *_: _stop.set())
    log(
        f"started (base={BASE_DIR} fps={FPS} interval={ASSEMBLE_INTERVAL}s "
        f"quiet={QUIET_PERIOD}s frame_retention={FRAME_RETENTION_DAYS}d "
        f"video_retention={VIDEO_RETENTION_DAYS}d)"
    )
    while not _stop.is_set():
        try:
            assemble_pass()
            prune_pass()
        except Exception as exc:  # keep the service alive across surprises
            log(f"pass error: {exc}")
        _stop.wait(ASSEMBLE_INTERVAL)
    log("stopped")


if __name__ == "__main__":
    main()
