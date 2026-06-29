"""
Single-stream Broadcasting Engine worker.

A minimal engine that serves EXACTLY ONE stream / one folder. The manager
(manager.py) spawns one of these per broadcast and reverse-proxies all client +
viewer traffic to it. You normally do NOT run this by hand -- run

    python manager.py

instead, which launches one worker per stream automatically.

Run directly (for debugging a single stream):

    python single_engine.py --port 5001 --stream-id <id> --output-dir <dir>

It binds 127.0.0.1 only: the manager is the public entry point and proxies to it.
"""
import os
import re
import sys
import glob
import json
import time
import shutil
import argparse
import threading
import subprocess
from datetime import datetime

from flask import Flask, jsonify, request, Response, send_file
from flask_cors import CORS

from config import Config


def _exit_when_parent_dies(manager_pid):
    """Hard-exit this worker as soon as the launching manager process dies.

    Guarantees a worker never outlives its manager no matter HOW the manager
    dies -- Ctrl+C, terminate(), or a Task Manager / SIGKILL hard kill. The
    manager's own cleanup is best-effort and does NOT run on a hard kill, so
    each worker independently watches its parent. Runs in a daemon thread.
    """
    if not manager_pid:
        return
    manager_pid = int(manager_pid)

    if sys.platform == 'win32':
        import ctypes
        SYNCHRONIZE = 0x00100000
        INFINITE = 0xFFFFFFFF
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, manager_pid)
        if not handle:
            os._exit(0)                       # manager already gone
        # Blocks with no CPU cost until the manager handle is signalled (exit).
        ctypes.windll.kernel32.WaitForSingleObject(handle, INFINITE)
        os._exit(0)
    else:
        # Linux: ask the kernel to signal us the instant the parent dies.
        try:
            import ctypes
            import signal as _signal
            ctypes.CDLL('libc.so.6', use_errno=True).prctl(1, _signal.SIGTERM)  # PR_SET_PDEATHSIG
        except Exception:
            pass
        # Portable backstop (macOS + the prctl already-dead race): poll.
        while True:
            try:
                os.kill(manager_pid, 0)
            except OSError:
                os._exit(0)
            time.sleep(2)


# A viewer is considered "active" if we've seen them within this many seconds.
# HLS players poll the playlist every segment duration (~2s), so this window
# comfortably covers normal polling while letting the count drop soon after a
# viewer leaves.
VIEWER_TTL = 30


def _find_ffmpeg():
    """Locate ffmpeg: bundled next to the exe / in _MEIPASS (frozen), alongside
    the source, the configured path, or PATH."""
    exe = 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'
    bases = []
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', '')
        if meipass:
            bases.append(meipass)
        bases.append(os.path.dirname(sys.executable))
    bases.append(os.path.dirname(os.path.abspath(__file__)))

    candidates = []
    for b in bases:
        candidates += [os.path.join(b, 'ffmpeg', exe),
                       os.path.join(b, 'ffmpeg', 'bin', exe),
                       os.path.join(b, exe)]
    candidates.append(getattr(Config, 'FFMPEG_PATH', None))
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return shutil.which(getattr(Config, 'FFMPEG_PATH', None) or 'ffmpeg') or shutil.which('ffmpeg')


def create_app(stream_id, output_dir):
    """Build a Flask app that serves exactly one stream (`stream_id`).

    All the per-stream state that the original monolithic engine kept in a big
    `external_streams` dict lives here as a single `info` dict, so this worker is
    completely independent from every other stream's worker process.
    """

    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app)

    os.makedirs(output_dir, exist_ok=True)

    # The single stream this worker serves. `None` until /init (a fresh stream)
    # or until we rebuild it from disk below (a replay/recovery spawn).
    state = {'info': None}

    # ---- Persistence -----------------------------------------------------
    # We save a small metadata.json next to the segments so the manager can show
    # ended recordings in the list without spawning us, and so a replay spawn can
    # rebuild full state from disk.

    def _meta_path():
        return os.path.join(output_dir, 'metadata.json')

    def _save_meta():
        info = state['info']
        if not info:
            return
        try:
            data = {k: v for k, v in info.items() if k not in ('viewer_ids', 'viewer_ips')}
            with open(_meta_path(), 'w') as f:
                json.dump(data, f)
        except Exception:
            pass

    def _load_from_disk():
        """Rebuild `info` from metadata.json + segments already on disk.

        Used when the manager spawns us for an EXISTING recording (replay) or
        after a manager restart. A fresh stream has neither, so `info` stays
        None and the first /init call will create it.
        """
        meta = {}
        if os.path.exists(_meta_path()):
            try:
                with open(_meta_path()) as f:
                    meta = json.load(f)
            except Exception:
                meta = {}

        segments = glob.glob(os.path.join(output_dir, 'segment_*.ts'))
        playlist = os.path.join(output_dir, 'stream.m3u8')
        if not meta and not (segments and os.path.exists(playlist)):
            return  # nothing to recover -- this is a brand-new stream

        # A recording with segments on disk but no longer being pushed to is, by
        # definition, an ended (replayable) recording.
        status = meta.get('status', 'ended')
        if segments and status not in ('streaming', 'initialized'):
            status = 'ended'

        state['info'] = {
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
            'viewer_ids': {},
            'segments_received': meta.get('segments_received', len(segments)),
            'last_segment_time': meta.get('last_segment_time'),
            'type': meta.get('type', 'external'),
            'vod': meta.get('vod', bool(segments)),
            'duration': meta.get('duration', len(segments) * 2),
        }

    _load_from_disk()

    def _wrong_stream(sid):
        """Guard: this worker only knows about its one assigned stream."""
        return sid != stream_id

    # ==================== Stream Reception (push from client) ============

    @app.route('/api/stream-receiver/init', methods=['POST'])
    def init_stream():
        """Initialize this worker's stream (folder already created by manager)."""
        data = request.get_json() or {}
        state['info'] = {
            'id': stream_id,
            'name': data.get('name', 'External Stream'),
            'width': data.get('width', 1920),
            'height': data.get('height', 1080),
            'fps': data.get('fps', 30),
            'source_ip': request.headers.get('X-Forwarded-For', request.remote_addr),
            'output_dir': output_dir,
            'status': 'initialized',
            'started_at': datetime.utcnow().isoformat(),
            'viewers': 0,
            'viewer_ids': {},
            'segments_received': 0,
            'last_segment_time': None,
            'type': 'external',
        }
        _save_meta()

        return jsonify({
            'stream_id': stream_id,
            'status': 'initialized',
            'upload_endpoint': f'/api/stream-receiver/{stream_id}/segment',
            'stream_url': f'/api/screen-stream/{stream_id}/stream.m3u8',
        }), 201

    @app.route('/api/stream-receiver/<sid>/segment', methods=['POST'])
    def receive_segment(sid):
        """Receive one .ts segment (or the playlist) from the client."""
        if _wrong_stream(sid) or state['info'] is None:
            return jsonify({'error': 'Stream session not found'}), 404

        info = state['info']
        if 'segment' not in request.files:
            return jsonify({'error': 'No segment file provided'}), 400

        segment_file = request.files['segment']
        segment_number = request.form.get('segment_number', type=int)
        is_playlist = request.form.get('is_playlist', 'false') == 'true'

        if is_playlist:
            segment_file.save(os.path.join(output_dir, 'stream.m3u8'))
        else:
            if segment_number is None:
                segment_number = info['segments_received']
            segment_file.save(os.path.join(output_dir, f'segment_{segment_number:03d}.ts'))
            info['segments_received'] += 1
            info['last_segment_time'] = datetime.utcnow().isoformat()

        # Receiving data means the broadcast is live (covers a client that
        # resumes pushing to a worker we had marked ended).
        if info['status'] in ('initialized', 'ended'):
            info['status'] = 'streaming'

        return jsonify({
            'success': True,
            'segment_number': segment_number,
            'segments_received': info['segments_received'],
        })

    @app.route('/api/stream-receiver/<sid>/playlist', methods=['POST'])
    def update_playlist(sid):
        """Receive/replace the live .m3u8 playlist."""
        if _wrong_stream(sid) or state['info'] is None:
            return jsonify({'error': 'Stream session not found'}), 404

        data = request.get_json() or {}
        playlist_content = data.get('playlist')
        if not playlist_content:
            return jsonify({'error': 'No playlist content provided'}), 400

        with open(os.path.join(output_dir, 'stream.m3u8'), 'w') as f:
            f.write(playlist_content)

        return jsonify({'success': True})

    @app.route('/api/stream-receiver/<sid>/end', methods=['POST'])
    def end_stream(sid):
        """End the broadcast and finalize a VOD playlist for replay."""
        if _wrong_stream(sid) or state['info'] is None:
            return jsonify({'error': 'Stream session not found'}), 404

        info = state['info']
        info['status'] = 'ended'
        info['ended_at'] = datetime.utcnow().isoformat()
        info['viewer_ids'] = {}
        info['viewers'] = 0

        # Build a complete VOD playlist (with #EXT-X-ENDLIST) from all received
        # segments so the recording can be replayed from the beginning.
        try:
            def _seg_num(p):
                m = re.search(r'segment_(\d+)\.ts', os.path.basename(p))
                return int(m.group(1)) if m else 0

            segments = sorted(glob.glob(os.path.join(output_dir, 'segment_*.ts')), key=_seg_num)
            if segments:
                lines = [
                    '#EXTM3U',
                    '#EXT-X-VERSION:3',
                    '#EXT-X-TARGETDURATION:5',
                    '#EXT-X-MEDIA-SEQUENCE:0',
                    '#EXT-X-PLAYLIST-TYPE:VOD',
                ]
                for seg in segments:
                    lines.append('#EXTINF:2.000,')
                    lines.append(os.path.basename(seg))
                lines.append('#EXT-X-ENDLIST')
                with open(os.path.join(output_dir, 'stream.m3u8'), 'w') as f:
                    f.write('\n'.join(lines) + '\n')
                info['vod'] = True
                info['duration'] = len(segments) * 2
        except Exception:
            pass

        _save_meta()
        return jsonify({'success': True, 'vod': info.get('vod', False)})

    # ==================== Stream Serving (pull by viewers) ===============

    def _decay_viewers(info):
        """Drop viewers we haven't seen within VIEWER_TTL and refresh the count.

        Only LIVE ('streaming') streams have viewers; a finished recording must
        always report 0 so replay/poller/load-test traffic can't inflate it.
        """
        if info.get('status') != 'streaming':
            info['viewer_ids'] = {}
            info['viewers'] = 0
            return
        now = time.time()
        viewers = {vid: ts for vid, ts in info.get('viewer_ids', {}).items()
                   if now - ts <= VIEWER_TTL}
        info['viewer_ids'] = viewers
        info['viewers'] = len(viewers)

    def _public_view(info):
        """A copy of the stream's info without internal-only tracking fields."""
        return {k: v for k, v in info.items() if k not in ('viewer_ids', 'viewer_ips')}

    @app.route('/api/screen-stream/<sid>')
    def get_status(sid):
        """Status of this stream."""
        if _wrong_stream(sid) or state['info'] is None:
            return jsonify({'error': 'Stream not found'}), 404
        info = state['info']
        _decay_viewers(info)
        return jsonify(_public_view(info))

    @app.route('/api/screen-stream/<sid>/stream.m3u8')
    def get_playlist(sid):
        """Serve the HLS playlist to a viewer (+ unique-viewer tracking)."""
        if _wrong_stream(sid) or state['info'] is None:
            return jsonify({'error': 'Stream not found'}), 404

        playlist_path = os.path.join(output_dir, 'stream.m3u8')
        if not os.path.exists(playlist_path):
            return jsonify({'error': 'Stream playlist not found'}), 404

        with open(playlist_path, 'r') as f:
            playlist = f.read()

        # Count UNIQUE active viewers by a stable per-browser cookie (an IP can
        # be shared / rotate, which would inflate the count). Only track while
        # the broadcast is LIVE -- an ended VOD must not keep growing its count.
        info = state['info']
        import uuid as _uuid
        viewer_id = request.cookies.get('viewer_id')
        set_cookie = False
        if not viewer_id:
            viewer_id = _uuid.uuid4().hex
            set_cookie = True

        now = time.time()
        if info.get('status') == 'streaming':
            viewers = info.setdefault('viewer_ids', {})
            viewers[viewer_id] = now
            viewers = {vid: ts for vid, ts in viewers.items() if now - ts <= VIEWER_TTL}
            info['viewer_ids'] = viewers
            info['viewers'] = len(viewers)
        else:
            info['viewer_ids'] = {}
            info['viewers'] = 0

        resp = Response(playlist, mimetype='application/vnd.apple.mpegurl')
        # The playlist changes as the live window advances, so a cache/CDN in
        # front of the origin must always revalidate it (segments below are the
        # cacheable part).
        resp.headers['Cache-Control'] = 'no-cache'
        if set_cookie:
            resp.set_cookie('viewer_id', viewer_id, max_age=86400, samesite='Lax')
        return resp

    @app.route('/api/screen-stream/<sid>/download')
    def download_recording(sid):
        """Download the recording as one playable file (MP4 via ffmpeg, else .ts)."""
        if _wrong_stream(sid) or state['info'] is None:
            return jsonify({'error': 'Stream not found'}), 404

        info = state['info']

        def _seg_num(p):
            m = re.search(r'segment_(\d+)\.ts', os.path.basename(p))
            return int(m.group(1)) if m else 0

        segments = sorted(glob.glob(os.path.join(output_dir, 'segment_*.ts')), key=_seg_num)
        if not segments:
            return jsonify({'error': 'No recording available to download'}), 404

        base_name = re.sub(r'[^A-Za-z0-9_-]+', '_',
                           info.get('name') or 'recording').strip('_') or 'recording'
        newest_seg_mtime = max(os.path.getmtime(s) for s in segments)

        # ---- Preferred path: remux to MP4 with ffmpeg -------------------
        ffmpeg = _find_ffmpeg()
        if ffmpeg:
            mp4_path = os.path.join(output_dir, 'recording.mp4')
            try:
                if (not os.path.exists(mp4_path)
                        or os.path.getmtime(mp4_path) < newest_seg_mtime):
                    concat_list = os.path.join(output_dir, '_concat.txt')
                    with open(concat_list, 'w') as f:
                        for s in segments:
                            f.write(f"file '{os.path.basename(s)}'\n")
                    subprocess.run(
                        [ffmpeg, '-y', '-f', 'concat', '-safe', '0',
                         '-i', '_concat.txt',
                         '-c', 'copy', '-bsf:a', 'aac_adtstoasc',
                         '-movflags', '+faststart', 'recording.mp4'],
                        cwd=output_dir, capture_output=True, timeout=600,
                    )
                if os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 0:
                    return send_file(mp4_path, mimetype='video/mp4',
                                     as_attachment=True,
                                     download_name=f'{base_name}.mp4')
            except Exception:
                pass  # fall through to the .ts fallback

        # ---- Fallback: concatenate the raw .ts segments -----------------
        ts_path = os.path.join(output_dir, 'recording.ts')
        try:
            if (not os.path.exists(ts_path)
                    or os.path.getmtime(ts_path) < newest_seg_mtime):
                with open(ts_path, 'wb') as out:
                    for s in segments:
                        with open(s, 'rb') as part:
                            shutil.copyfileobj(part, out)
            return send_file(ts_path, mimetype='video/mp2t',
                             as_attachment=True,
                             download_name=f'{base_name}.ts')
        except Exception as e:
            return jsonify({'error': f'Failed to build download: {e}'}), 500

    @app.route('/api/screen-stream/<sid>/<segment>')
    def get_segment(sid, segment):
        """Serve a single .ts segment to a viewer."""
        if _wrong_stream(sid):
            return jsonify({'error': 'Stream not found'}), 404
        segment_path = os.path.join(output_dir, segment)
        if not os.path.exists(segment_path):
            return jsonify({'error': 'Segment not found'}), 404
        resp = send_file(segment_path, mimetype='video/mp2t')
        # HLS segments never change once written. Marking them immutable lets a
        # cache/CDN (or a relay tier) coalesce edge pulls, so the origin serves
        # each segment only ONCE per direct child instead of once per edge.
        if re.match(r'segment_\d+\.ts$', segment):
            resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return resp

    # ==================== Health / lifecycle =============================

    @app.route('/')
    def index():
        """Health/info for this worker (the manager polls this on startup)."""
        info = state['info']
        return jsonify({
            'service': 'single-engine',
            'status': 'ok',
            'stream_id': stream_id,
            'stream_status': info.get('status') if info else 'empty',
        })

    @app.route('/shutdown', methods=['POST'])
    def shutdown():
        """Let the manager stop this worker cleanly (used before delete)."""
        func = request.environ.get('werkzeug.server.shutdown')
        if func:
            func()
            return jsonify({'success': True})
        # No clean hook (newer Werkzeug): exit the process directly.
        os._exit(0)

    return app


def main():
    parser = argparse.ArgumentParser(description='Single-stream broadcasting engine worker.')
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--stream-id', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--host', default='127.0.0.1',
                        help='Bind address (default 127.0.0.1; the manager proxies to it).')
    parser.add_argument('--manager-pid', type=int, default=None,
                        help='PID of the launching manager; the worker self-exits if it dies.')
    args = parser.parse_args()

    # Never outlive the manager that spawned us.
    if args.manager_pid:
        threading.Thread(target=_exit_when_parent_dies,
                         args=(args.manager_pid,), daemon=True).start()

    app = create_app(args.stream_id, os.path.abspath(args.output_dir))
    # threaded=True so playlist polls + segment downloads are concurrent.
    # No reloader: this is a managed child process.
    app.run(host=args.host, port=args.port, threaded=True,
            debug=False, use_reloader=False)


if __name__ == '__main__':
    main()
