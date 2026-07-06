#!/usr/bin/env python
"""skycam-web: serve the latest frame + a WebSocket "new frame" doorbell.

Published on :8092 for a reverse proxy / tunnel to serve it publicly:

  GET /latest.jpg  current frame; no-cache + ETag/Last-Modified so conditional
                   GETs return 304 (aiohttp FileResponse handles this)
  GET /ws          WebSocket emitting {"type":"imageUpdate"} on each rewrite
  GET /            live viewer: latest.jpg scaled to the viewport, refreshed on
                   each imageUpdate

The /ws message is a plain {"type":"imageUpdate"} "new frame" signal any client
can subscribe to — the bundled viewer at /, or a dashboard's push_ws (e.g. the
Komakallio panel consumes /latest.jpg as an http_image + /ws as its push_ws).
"""

import asyncio
import os

from aiohttp import WSMsgType, web

DATA_DIR = os.environ.get("SKYCAM_DATA_DIR", "/data")
LATEST = os.path.join(DATA_DIR, "latest.jpg")
PORT = int(os.environ.get("SKYCAM_WEB_PORT", "8092"))
POLL = 1.0
INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")


async def handle_index(request):
    if os.path.exists(INDEX):
        return web.FileResponse(INDEX)
    return web.Response(text="skycam: see /latest.jpg", content_type="text/plain")


async def handle_latest(request):
    if not os.path.exists(LATEST):
        return web.Response(status=404, text="no frame yet")
    return web.FileResponse(
        LATEST,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


async def handle_ws(request):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    request.app["clients"].add(ws)
    try:
        async for msg in ws:  # no inbound messages expected; just keep it open
            if msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSING):
                break
    finally:
        request.app["clients"].discard(ws)
    return ws


async def watcher(app):
    """Broadcast {"type":"imageUpdate"} whenever latest.jpg's mtime changes."""
    last = 0.0
    while True:
        try:
            mtime = os.path.getmtime(LATEST)
        except OSError:
            mtime = 0.0
        if mtime and mtime != last:
            last = mtime
            for ws in list(app["clients"]):
                try:
                    await ws.send_json({"type": "imageUpdate"})
                except Exception:
                    app["clients"].discard(ws)
        await asyncio.sleep(POLL)


async def on_startup(app):
    app["watcher_task"] = asyncio.create_task(watcher(app))


async def on_cleanup(app):
    app["watcher_task"].cancel()
    for ws in list(app["clients"]):
        await ws.close()


def main():
    app = web.Application()
    app["clients"] = set()
    app.add_routes([
        web.get("/", handle_index),
        web.get("/latest.jpg", handle_latest),
        web.get("/ws", handle_ws),
    ])
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    print(f"[web] serving on :{PORT} (data={DATA_DIR})", flush=True)
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
