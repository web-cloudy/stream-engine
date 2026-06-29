"""
Broadcasting Manager  ("the bot" / gateway)  -- Part 2 entry point.

ONE public server (host:port from config, e.g. http://0.0.0.0:5000) that:

  * spawns ONE single_engine.py worker PER stream / PER folder, on demand;
  * reverse-proxies every client + viewer request to the right worker by
    stream_id, so clients and viewers only ever use this single address;
  * keeps a worker alive after its broadcast ends so the recording can still be
    replayed, then reaps it after an idle timeout;
  * re-spawns a worker on demand when someone replays an old recording (or after
    a manager restart), rebuilding its state from disk.

Because it speaks the exact same HTTP API the old monolithic engine did, the
Screen Broadcast Client (Part 1) and Web Viewer (Part 3) need NO changes -- they
keep pointing at this one address.

Run:

    python manager.py            # serves on http://0.0.0.0:5000
"""
import os
import sys
import glob
import json
import time
import uuid
import atexit
import socket
import shutil
import threading
import subprocess

import requests
from flask import Flask, jsonify, request, Response
from flask_cors import CORS

from config import Config


HERE = os.path.dirname(os.path.abspath(__file__))
SINGLE_ENGINE = os.path.join(HERE, 'single_engine.py')
BASE_DIR = os.path.abspath(os.path.join(Config.TRANSCODE_TEMP_DIR, 'external_streams'))

# ---- Tunables (overridable via env) -------------------------------------
# Ended worker that no one has touched for this long -> shut it down (its files
# stay on disk; a later replay re-spawns it).
IDLE_REAP_SECONDS = int(os.getenv('ENGINE_IDLE_REAP', '600'))
# Streaming worker that hasn't received a segment for this long -> the client
# vanished without calling /end. Finalize its VOD and mark it ended.
LIVE_IDLE_SECONDS = int(os.getenv('LIVE_IDLE_SECONDS', '60'))
# How long to wait for a freshly spawned worker to answer its health check.
ENGINE_START_TIMEOUT = int(os.getenv('ENGINE_START_TIMEOUT', '15'))
# How often the background reaper wakes up to check for idle workers.
REAP_INTERVAL = int(os.getenv('REAP_INTERVAL', '15'))

# Headers we must not blindly copy when proxying (they describe THIS hop, not
# the payload). Content-Length/Encoding are dropped so Flask recomputes them.
HOP_BY_HOP = {
    'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
    'te', 'trailers', 'transfer-encoding', 'upgrade', 'host',
    'content-length', 'content-encoding',
}


# registry: stream_id -> {
#   'output_dir', 'port', 'proc', 'status', 'last_activity', 'name'
# }
registry = {}
reg_lock = threading.RLock()


# ---------------------------------------------------------------------------
# Worker process management
# ---------------------------------------------------------------------------
def _free_port():
    """Ask the OS for a free TCP port (small race window, fine on a LAN tool)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _engine_base(port):
    return f'http://127.0.0.1:{port}'


def _wait_healthy(port, timeout=ENGINE_START_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(_engine_base(port) + '/', timeout=1)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _spawn_worker(stream_id, output_dir):
    """Start a single_engine.py worker for one stream and wait until it's up."""
    port = _free_port()
    common = ['--port', str(port),
              '--stream-id', stream_id,
              '--output-dir', output_dir,
              # So the worker self-exits if we die without cleaning up (hard kill).
              '--manager-pid', str(os.getpid())]
    if getattr(sys, 'frozen', False):
        # Packaged as an .exe: re-invoke ourselves in the worker role (there is
        # no python + single_engine.py to call). sys.executable is the exe.
        cmd = [sys.executable, '--role', 'worker'] + common
        run_cwd = os.path.dirname(sys.executable)
    else:
        # Source mode: sys.executable = the (venv) Python running the manager.
        cmd = [sys.executable, SINGLE_ENGINE] + common
        run_cwd = HERE
    proc = subprocess.Popen(cmd, cwd=run_cwd)
    if not _wait_healthy(port):
        try:
            proc.terminate()
        except Exception:
            pass
        raise RuntimeError(f'engine for {stream_id} failed to start on port {port}')
    return port, proc


def _ensure_worker(stream_id, create=False):
    """Return a live registry entry for `stream_id`, spawning a worker if needed.

    create=True  -> brand-new stream (make the folder).
    create=False -> only succeed if the stream already exists on disk
                    (replay / recovery); returns None otherwise.

    NOTE: we hold the registry lock across the spawn (which blocks up to
    ENGINE_START_TIMEOUT on the worker's health check). Stream counts on a LAN
    tool are small, so the simplicity is worth more than the brief contention.
    """
    with reg_lock:
        entry = registry.get(stream_id)

        if entry is None:
            output_dir = os.path.join(BASE_DIR, stream_id)
            if not create and not os.path.isdir(output_dir):
                return None
            os.makedirs(output_dir, exist_ok=True)
            entry = {
                'output_dir': output_dir,
                'port': None,
                'proc': None,
                'status': 'initialized' if create else 'ended',
                'last_activity': time.time(),
                'name': None,
            }
            registry[stream_id] = entry

        proc = entry.get('proc')
        if proc is not None and proc.poll() is None:
            return entry  # worker already running

        # (Re)spawn the worker.
        port, proc = _spawn_worker(stream_id, entry['output_dir'])
        entry['port'] = port
        entry['proc'] = proc
        entry['last_activity'] = time.time()
        return entry


def _stop_worker(entry):
    """Terminate a worker process if it's running."""
    proc = entry.get('proc')
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
    except Exception:
        pass
    entry['proc'] = None
    entry['port'] = None


# ---------------------------------------------------------------------------
# Reverse proxy
# ---------------------------------------------------------------------------
def _proxy(entry, stream_id):
    """Forward the current request to a stream's worker and relay its response."""
    url = _engine_base(entry['port']) + request.full_path  # full_path keeps ?query
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    # Preserve the real client IP for the worker's source_ip / logging.
    headers['X-Forwarded-For'] = request.remote_addr or ''
    try:
        upstream = requests.request(
            request.method, url,
            headers=headers,
            data=request.get_data(),          # raw body: works for multipart AND json
            cookies=request.cookies,
            params=None,                       # query already in full_path
            allow_redirects=False,
            stream=True,
            timeout=120,
        )
    except Exception as e:
        return jsonify({'error': f'engine unreachable: {e}'}), 502

    entry['last_activity'] = time.time()
    resp_headers = [(k, v) for k, v in upstream.raw.headers.items()
                    if k.lower() not in HOP_BY_HOP]
    return Response(upstream.iter_content(chunk_size=64 * 1024),
                    status=upstream.status_code, headers=resp_headers)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app)

    os.makedirs(BASE_DIR, exist_ok=True)

    # ============ Reception (client -> manager -> worker) ============

    @app.route('/api/stream-receiver/init', methods=['POST'])
    def init_stream():
        """Allocate a stream, spawn its worker, and forward the init to it.

        A caller MAY supply `stream_id` in the body. The live relay (Server B
        mirroring Server A) uses this so an edge mirrors the origin's stream
        under the SAME id, keeping viewer URLs identical on every server. Normal
        broadcast clients omit it and get a fresh uuid.
        """
        body = request.get_json(silent=True) or {}
        stream_id = body.get('stream_id') or str(uuid.uuid4())
        try:
            entry = _ensure_worker(stream_id, create=True)
        except Exception as e:
            return jsonify({'error': f'failed to start engine: {e}'}), 500

        entry['name'] = body.get('name')
        entry['status'] = 'initialized'
        return _proxy(entry, stream_id)

    @app.route('/api/stream-receiver/<stream_id>/segment', methods=['POST'])
    def receive_segment(stream_id):
        entry = _ensure_worker(stream_id)
        if entry is None:
            return jsonify({'error': 'Stream session not found'}), 404
        entry['status'] = 'streaming'
        return _proxy(entry, stream_id)

    @app.route('/api/stream-receiver/<stream_id>/playlist', methods=['POST'])
    def update_playlist(stream_id):
        entry = _ensure_worker(stream_id)
        if entry is None:
            return jsonify({'error': 'Stream session not found'}), 404
        entry['status'] = 'streaming'
        return _proxy(entry, stream_id)

    @app.route('/api/stream-receiver/<stream_id>/end', methods=['POST'])
    def end_stream(stream_id):
        entry = _ensure_worker(stream_id)
        if entry is None:
            return jsonify({'error': 'Stream session not found'}), 404
        entry['status'] = 'ended'
        return _proxy(entry, stream_id)

    # ============ Serving (viewer -> manager -> worker) ==============

    @app.route('/api/screen-stream/list')
    def list_streams():
        """Aggregate every stream WITHOUT spawning idle workers.

        Live streams have a running worker -> ask it for fresh counts. Ended
        recordings are read straight from their metadata.json on disk, so the
        dashboard's frequent polling never spins up an engine per recording.
        """
        out = []
        seen = set()

        with reg_lock:
            entries = list(registry.items())

        for stream_id, entry in entries:
            seen.add(stream_id)
            proc = entry.get('proc')
            if proc is not None and proc.poll() is None:
                try:
                    r = requests.get(
                        _engine_base(entry['port']) + f'/api/screen-stream/{stream_id}',
                        timeout=3)
                    if r.status_code == 200:
                        out.append(r.json())
                        continue
                except Exception:
                    pass
            info = _public_from_disk(stream_id, entry['output_dir'])
            if info:
                out.append(info)

        # Pick up recordings on disk we don't have a registry entry for yet
        # (e.g. right after a manager restart).
        if os.path.isdir(BASE_DIR):
            for stream_id in os.listdir(BASE_DIR):
                if stream_id in seen:
                    continue
                output_dir = os.path.join(BASE_DIR, stream_id)
                if not os.path.isdir(output_dir):
                    continue
                info = _public_from_disk(stream_id, output_dir)
                if info:
                    out.append(info)

        return jsonify(out)

    @app.route('/api/screen-stream/<stream_id>')
    def get_status(stream_id):
        """Status of one stream (uses the live worker if up, else disk)."""
        with reg_lock:
            entry = registry.get(stream_id)
        if entry and entry.get('proc') and entry['proc'].poll() is None:
            return _proxy(entry, stream_id)
        output_dir = os.path.join(BASE_DIR, stream_id)
        info = _public_from_disk(stream_id, output_dir)
        if info is None:
            return jsonify({'error': 'Stream not found'}), 404
        return jsonify(info)

    @app.route('/api/screen-stream/<stream_id>/stream.m3u8')
    def get_playlist(stream_id):
        # Fetching the playlist is what triggers a REPLAY: spawn the worker if
        # the recording exists on disk but its worker was reaped / never started.
        entry = _ensure_worker(stream_id)
        if entry is None:
            return jsonify({'error': 'Stream not found'}), 404
        return _proxy(entry, stream_id)

    @app.route('/api/screen-stream/<stream_id>/download')
    def download_recording(stream_id):
        entry = _ensure_worker(stream_id)
        if entry is None:
            return jsonify({'error': 'Stream not found'}), 404
        return _proxy(entry, stream_id)

    @app.route('/api/screen-stream/<stream_id>/<segment>')
    def get_segment(stream_id, segment):
        entry = _ensure_worker(stream_id)
        if entry is None:
            return jsonify({'error': 'Stream not found'}), 404
        return _proxy(entry, stream_id)

    @app.route('/api/screen-stream/<stream_id>/delete', methods=['POST'])
    def delete_stream(stream_id):
        """Stop the worker (so it releases the folder) then delete on disk."""
        with reg_lock:
            entry = registry.pop(stream_id, None)
        output_dir = (entry or {}).get('output_dir') or os.path.join(BASE_DIR, stream_id)
        if entry:
            _stop_worker(entry)
            time.sleep(0.3)  # let the OS release file handles (Windows)
        if os.path.isdir(output_dir):
            try:
                shutil.rmtree(output_dir)
            except Exception:
                pass
        return jsonify({'success': True})

    @app.route('/api/cleanup', methods=['POST'])
    def cleanup_streams():
        """Delete every ended/stopped recording (stop worker + remove on disk)."""
        cleaned = 0
        with reg_lock:
            items = list(registry.items())
        ended_ids = set()

        for stream_id, entry in items:
            if entry.get('status') in ('ended', 'stopped'):
                ended_ids.add(stream_id)
                _stop_worker(entry)
                with reg_lock:
                    registry.pop(stream_id, None)

        time.sleep(0.3)

        # Also sweep ended recordings that only exist on disk.
        if os.path.isdir(BASE_DIR):
            for stream_id in os.listdir(BASE_DIR):
                output_dir = os.path.join(BASE_DIR, stream_id)
                if not os.path.isdir(output_dir):
                    continue
                info = _public_from_disk(stream_id, output_dir)
                if info and info.get('status') in ('ended', 'stopped'):
                    ended_ids.add(stream_id)

        for stream_id in ended_ids:
            output_dir = os.path.join(BASE_DIR, stream_id)
            if os.path.isdir(output_dir):
                try:
                    shutil.rmtree(output_dir)
                    cleaned += 1
                except Exception:
                    pass

        return jsonify({'cleaned': cleaned, 'message': f'Cleaned up {cleaned} stream(s)'})

    @app.route('/')
    def index():
        with reg_lock:
            running = sum(1 for e in registry.values()
                          if e.get('proc') and e['proc'].poll() is None)
            total = len(registry)
        return jsonify({
            'service': 'broadcasting-manager',
            'status': 'ok',
            'streams_known': total,
            'workers_running': running,
            'hint': 'One engine worker is spawned per stream. Viewer UI is the '
                    'separate web-viewer project.',
        })

    return app


# ---------------------------------------------------------------------------
# Disk helpers + background reaper
# ---------------------------------------------------------------------------
def _public_from_disk(stream_id, output_dir):
    """Build a viewer-facing info dict for a stream from files on disk.

    Returns None for empty/incomplete folders. Mirrors the shape the workers
    (and the old engine) return so the dashboard renders identically.
    """
    if not os.path.isdir(output_dir):
        return None

    meta_path = os.path.join(output_dir, 'metadata.json')
    meta = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except Exception:
            meta = {}

    segments = glob.glob(os.path.join(output_dir, 'segment_*.ts'))
    if not meta and not segments:
        return None

    status = meta.get('status', 'ended')
    # If it's not actively being served by a live worker, it isn't live.
    if status == 'streaming':
        status = 'ended'

    info = {
        'id': stream_id,
        'name': meta.get('name', f'Recording {stream_id[:8]}'),
        'width': meta.get('width', 0),
        'height': meta.get('height', 0),
        'fps': meta.get('fps', 30),
        'source_ip': meta.get('source_ip', ''),
        'output_dir': output_dir,
        'status': status,
        'started_at': meta.get('started_at'),
        'ended_at': meta.get('ended_at'),
        'viewers': 0,
        'segments_received': meta.get('segments_received', len(segments)),
        'last_segment_time': meta.get('last_segment_time'),
        'type': meta.get('type', 'external'),
        'vod': meta.get('vod', bool(segments)),
        'duration': meta.get('duration', len(segments) * 2),
    }
    return info


def _reaper_loop():
    """Background thread: finalize dead live streams and reap idle workers."""
    while True:
        time.sleep(REAP_INTERVAL)
        now = time.time()
        with reg_lock:
            entries = list(registry.items())

        for stream_id, entry in entries:
            proc = entry.get('proc')
            if proc is None or proc.poll() is not None:
                continue  # no live worker to manage
            idle = now - entry.get('last_activity', now)

            if entry['status'] == 'streaming' and idle > LIVE_IDLE_SECONDS:
                # Client vanished without /end -> ask the worker to finalize VOD.
                try:
                    requests.post(
                        _engine_base(entry['port']) + f'/api/stream-receiver/{stream_id}/end',
                        timeout=5)
                except Exception:
                    pass
                entry['status'] = 'ended'
                entry['last_activity'] = now
            elif entry['status'] in ('ended', 'stopped') and idle > IDLE_REAP_SECONDS:
                # Nobody's replaying it -> free the process (files stay on disk).
                _stop_worker(entry)


def _shutdown_all_workers():
    with reg_lock:
        entries = list(registry.values())
    for entry in entries:
        _stop_worker(entry)


if __name__ == '__main__':
    atexit.register(_shutdown_all_workers)

    # On POSIX, `kill <pid>` (SIGTERM) bypasses atexit -- clean up explicitly so
    # we don't leave workers behind. (On Windows a hard kill can't be trapped;
    # the workers' own parent-death watchdog covers that case.)
    import signal

    def _handle_term(signum, frame):
        _shutdown_all_workers()
        os._exit(0)

    try:
        signal.signal(signal.SIGTERM, _handle_term)
    except Exception:
        pass

    reaper = threading.Thread(target=_reaper_loop, daemon=True)
    reaper.start()

    app = create_app()
    print(f'Broadcasting Manager on http://{Config.HOST}:{Config.PORT} '
          f'(one engine worker per stream; Ctrl+C to stop)')
    # use_reloader=False: the reloader would fork a second manager (and a second
    # reaper + duplicate workers). threaded=True so many viewers proxy at once.
    app.run(host=Config.HOST, port=Config.PORT,
            debug=Config.DEBUG, threaded=True, use_reloader=False)
