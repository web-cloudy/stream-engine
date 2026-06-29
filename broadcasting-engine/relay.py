"""
Live relay daemon for a Broadcasting Edge (Server B).

Polls the origin (Server A) for LIVE streams and mirrors each one into THIS
server's own broadcasting engine in real time. It does so by re-pushing the
origin's HLS segments + playlist through the standard /api/stream-receiver/*
ingest API -- i.e. it acts exactly like a broadcast client, but its "source" is
Server A instead of a local ffmpeg. The local engine (manager.py + the per-
stream single_engine workers) then serves viewers with NO changes.

    Server A (origin)                         this Server B (edge)
    /api/screen-stream/list   ──poll──▶  relay.py  ──re-push──▶  /api/stream-receiver/*
    /api/screen-stream/<id>/stream.m3u8                              │
    /api/screen-stream/<id>/<segment>                               ▼
                                                          single_engine ──▶ viewers

Run on each Server B, ALONGSIDE the engine:

    python manager.py        # the engine that serves viewers (port = PORT)
    python relay.py          # this daemon (mirrors origin -> local engine)

Config via environment / .env:
    ORIGIN_URL     base URL of Server A            (required, e.g. http://server-a:5000)
    EDGE_URL       base URL of THIS server's engine (default http://127.0.0.1:<PORT>)
    POLL_INTERVAL  discovery + tail interval, secs  (default 1.0)
"""
import os
import re
import io
import time
import threading

import requests

from config import Config


ORIGIN_URL = os.getenv('ORIGIN_URL', '').rstrip('/')
EDGE_URL = os.getenv('EDGE_URL', f'http://127.0.0.1:{Config.PORT}').rstrip('/')
POLL_INTERVAL = float(os.getenv('POLL_INTERVAL', '1.0'))

# One session, no system proxy (same hardening the broadcast client uses, so a
# VPN/proxy can't break server-to-server traffic).
S = requests.Session()
S.trust_env = False
S.proxies = {'http': None, 'https': None}

# stream_id -> {'stop': threading.Event, 'thread': threading.Thread}
_mirrors = {}
_mirrors_lock = threading.Lock()


def _origin(path):
    return f'{ORIGIN_URL}{path}'


def _edge(path):
    return f'{EDGE_URL}{path}'


def _seg_num(name):
    m = re.search(r'segment_(\d+)\.ts', name)
    return int(m.group(1)) if m else 0


def _parse_segments(playlist):
    """Segment filenames referenced by an .m3u8 (the non-tag lines)."""
    return [ln.strip() for ln in playlist.splitlines()
            if ln.strip() and not ln.startswith('#')]


def _mirror_stream(stream_id, meta, stop):
    """Mirror one origin stream into the local engine until it ends / stop set."""
    # 1) Create the stream locally under the SAME id, so viewer URLs match.
    try:
        S.post(_edge('/api/stream-receiver/init'), json={
            'stream_id': stream_id,
            'name': meta.get('name'),
            'width': meta.get('width'),
            'height': meta.get('height'),
            'fps': meta.get('fps'),
        }, timeout=10)
    except Exception as e:
        print(f'[relay] init failed for {stream_id}: {e}')
        return

    seen = set()              # segment names already pushed to the edge
    last_playlist = [None]    # last playlist forwarded (list = mutable closure cell)
    print(f'[relay] mirroring {stream_id}  ({meta.get("name")})')

    def sync_once():
        # Pull the origin's current playlist (live window or final VOD).
        try:
            r = S.get(_origin(f'/api/screen-stream/{stream_id}/stream.m3u8'), timeout=15)
            if r.status_code != 200:
                return
            playlist = r.text
        except Exception:
            return

        # Pull + re-push any segments we haven't mirrored yet (segments BEFORE
        # the playlist, so the edge never advertises a segment it lacks).
        for name in _parse_segments(playlist):
            if name in seen:
                continue
            try:
                seg = S.get(_origin(f'/api/screen-stream/{stream_id}/{name}'), timeout=30)
                if seg.status_code != 200:
                    continue
                S.post(
                    _edge(f'/api/stream-receiver/{stream_id}/segment'),
                    files={'segment': (name, io.BytesIO(seg.content), 'video/mp2t')},
                    data={'segment_number': _seg_num(name)},
                    timeout=30,
                )
                seen.add(name)
            except Exception as e:
                print(f'[relay] {stream_id} segment {name} error: {e}')

        # Forward the playlist (only when it changed) so the edge serves the
        # same live window the origin is serving.
        if playlist != last_playlist[0]:
            try:
                S.post(_edge(f'/api/stream-receiver/{stream_id}/playlist'),
                       json={'playlist': playlist}, timeout=10)
                last_playlist[0] = playlist
            except Exception:
                pass

    while not stop.is_set():
        sync_once()
        stop.wait(POLL_INTERVAL)

    # Stream ended on the origin: one final pass to catch trailing segments
    # (the origin has finalized its VOD playlist by now), then finalize locally.
    sync_once()
    try:
        S.post(_edge(f'/api/stream-receiver/{stream_id}/end'), timeout=10)
    except Exception:
        pass
    print(f'[relay] finished {stream_id}  ({len(seen)} segments mirrored)')


def _list_origin():
    try:
        r = S.get(_origin('/api/screen-stream/list'), timeout=10)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f'[relay] list error: {e}')
        return []


def discovery_loop():
    """Start a mirror for each new live stream; stop mirrors that have ended."""
    if not ORIGIN_URL:
        print('[relay] ORIGIN_URL is not set -- nothing to mirror. '
              'Set ORIGIN_URL=http://<server-a>:5000 and restart.')
        return

    print(f'[relay] origin={ORIGIN_URL}  edge={EDGE_URL}  interval={POLL_INTERVAL}s')
    while True:
        live = {s['id']: s for s in _list_origin() if s.get('status') == 'streaming'}

        with _mirrors_lock:
            # Start mirroring newly-seen live streams.
            for sid, meta in live.items():
                if sid not in _mirrors:
                    stop = threading.Event()
                    t = threading.Thread(target=_mirror_stream,
                                         args=(sid, meta, stop), daemon=True)
                    _mirrors[sid] = {'stop': stop, 'thread': t}
                    t.start()
            # Signal mirrors whose origin stream is no longer live to wrap up.
            for sid in list(_mirrors):
                if sid not in live:
                    _mirrors[sid]['stop'].set()
                    del _mirrors[sid]

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    discovery_loop()
