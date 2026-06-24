"""
Broadcasting Engine (Part 2) - pure API server.

Receives HLS segments pushed by the Screen Broadcast Client (Part 1), stores
them per stream, serves them to viewers, and finalizes a replayable VOD
recording when a broadcast ends.

The viewer web pages (Part 3) are a SEPARATE project (../web-viewer) that talks
to this server's API over HTTP. CORS is enabled here so the viewer app may run
on a different host/port/origin.
"""
import os
import re
import glob
import json
import time
import uuid
import shutil
import subprocess
from datetime import datetime

from flask import Flask, jsonify, request, Response, send_file
from flask_cors import CORS

from config import Config


# A viewer is considered "active" if we've seen them within this many seconds.
# HLS players poll the playlist every segment duration (~2s), so this window
# comfortably covers normal polling while letting the count drop soon after a
# viewer leaves.
VIEWER_TTL = 30


def _find_ffmpeg():
    """Locate an ffmpeg executable (bundled ./ffmpeg, alongside app, config, PATH)."""
    here = os.path.dirname(os.path.abspath(__file__))
    exe = 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'
    candidates = [
        os.path.join(here, 'ffmpeg', exe),
        os.path.join(here, 'ffmpeg', 'bin', exe),
        os.path.join(here, exe),
        getattr(Config, 'FFMPEG_PATH', None),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return shutil.which(getattr(Config, 'FFMPEG_PATH', None) or 'ffmpeg') or shutil.which('ffmpeg')


def create_app():

    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app)

    # Make sure the storage folder exists.
    os.makedirs(os.path.join(Config.TRANSCODE_TEMP_DIR, 'external_streams'), exist_ok=True)

    # In-memory registry of streams pushed by broadcast clients.
    external_streams = {}

    # ---- Persistence: survive server restarts ----------------------------
    # The registry is in memory, so without this a restart would "lose" every
    # recording even though its segments are still on disk. We save a small
    # metadata.json next to each stream's segments and reload them on startup.

    def _meta_path(output_dir):
        return os.path.join(output_dir, 'metadata.json')

    def _save_meta(info):
        """Persist a stream's metadata (everything except live-only fields)."""
        try:
            data = {k: v for k, v in info.items() if k != 'viewer_ips'}
            with open(_meta_path(info['output_dir']), 'w') as f:
                json.dump(data, f)
        except Exception:
            pass

    def _load_existing_streams():
        """Rebuild the registry from recordings already on disk."""
        base = os.path.join(Config.TRANSCODE_TEMP_DIR, 'external_streams')
        if not os.path.isdir(base):
            return
        for stream_id in os.listdir(base):
            output_dir = os.path.join(base, stream_id)
            if not os.path.isdir(output_dir):
                continue
            playlist = os.path.join(output_dir, 'stream.m3u8')
            segments = glob.glob(os.path.join(output_dir, 'segment_*.ts'))
            if not os.path.exists(playlist) or not segments:
                continue  # nothing replayable here

            meta = {}
            if os.path.exists(_meta_path(output_dir)):
                try:
                    with open(_meta_path(output_dir)) as f:
                        meta = json.load(f)
                except Exception:
                    meta = {}

            info = {
                'id': stream_id,
                'name': meta.get('name', f'Recording {stream_id[:8]}'),
                'width': meta.get('width', 0),
                'height': meta.get('height', 0),
                'fps': meta.get('fps', 30),
                'source_ip': meta.get('source_ip', ''),
                'output_dir': output_dir,
                # A prior session can't still be live after a restart -> ended.
                'status': 'ended',
                'started_at': meta.get('started_at'),
                'ended_at': meta.get('ended_at'),
                'viewers': 0,
                'viewer_ips': {},
                'segments_received': len(segments),
                'last_segment_time': meta.get('last_segment_time'),
                'type': meta.get('type', 'external'),
                'vod': True,
                'duration': meta.get('duration', len(segments) * 2),
            }
            external_streams[stream_id] = info

    _load_existing_streams()

    # ==================== Stream Reception (push from client) ====================

    @app.route('/api/stream-receiver/init', methods=['POST'])
    def init_external_stream():
        """Create a new stream session and storage folder."""
        data = request.get_json() or {}
        stream_id = str(uuid.uuid4())
        output_dir = os.path.join(Config.TRANSCODE_TEMP_DIR, 'external_streams', stream_id)
        os.makedirs(output_dir, exist_ok=True)

        external_streams[stream_id] = {
            'id': stream_id,
            'name': data.get('name', 'External Stream'),
            'width': data.get('width', 1920),
            'height': data.get('height', 1080),
            'fps': data.get('fps', 30),
            'source_ip': request.remote_addr,
            'output_dir': output_dir,
            'status': 'initialized',
            'started_at': datetime.utcnow().isoformat(),
            'viewers': 0,
            'viewer_ips': {},
            'segments_received': 0,
            'last_segment_time': None,
            'type': 'external',
        }
        _save_meta(external_streams[stream_id])

        return jsonify({
            'stream_id': stream_id,
            'status': 'initialized',
            'upload_endpoint': f'/api/stream-receiver/{stream_id}/segment',
            'stream_url': f'/api/screen-stream/{stream_id}/stream.m3u8',
        }), 201

    @app.route('/api/stream-receiver/<stream_id>/segment', methods=['POST'])
    def receive_stream_segment(stream_id):
        """Receive one .ts segment (or the playlist) from the client."""
        if stream_id not in external_streams:
            return jsonify({'error': 'Stream session not found'}), 404

        info = external_streams[stream_id]
        if 'segment' not in request.files:
            return jsonify({'error': 'No segment file provided'}), 400

        segment_file = request.files['segment']
        segment_number = request.form.get('segment_number', type=int)
        is_playlist = request.form.get('is_playlist', 'false') == 'true'

        if is_playlist:
            segment_file.save(os.path.join(info['output_dir'], 'stream.m3u8'))
        else:
            if segment_number is None:
                segment_number = info['segments_received']
            segment_file.save(os.path.join(info['output_dir'], f'segment_{segment_number:03d}.ts'))
            info['segments_received'] += 1
            info['last_segment_time'] = datetime.utcnow().isoformat()

        if info['status'] == 'initialized':
            info['status'] = 'streaming'

        return jsonify({
            'success': True,
            'segment_number': segment_number,
            'segments_received': info['segments_received'],
        })

    @app.route('/api/stream-receiver/<stream_id>/playlist', methods=['POST'])
    def update_stream_playlist(stream_id):
        """Receive/replace the live .m3u8 playlist."""
        if stream_id not in external_streams:
            return jsonify({'error': 'Stream session not found'}), 404

        data = request.get_json() or {}
        playlist_content = data.get('playlist')
        if not playlist_content:
            return jsonify({'error': 'No playlist content provided'}), 400

        with open(os.path.join(external_streams[stream_id]['output_dir'], 'stream.m3u8'), 'w') as f:
            f.write(playlist_content)

        return jsonify({'success': True})

    @app.route('/api/stream-receiver/<stream_id>/end', methods=['POST'])
    def end_external_stream(stream_id):
        """End a broadcast and finalize a VOD playlist for replay."""
        if stream_id not in external_streams:
            return jsonify({'error': 'Stream session not found'}), 404

        info = external_streams[stream_id]
        info['status'] = 'ended'
        info['ended_at'] = datetime.utcnow().isoformat()
        # The broadcast is over: clear live-viewer tracking so the ended card
        # doesn't keep displaying (and growing) a stale viewer count.
        info['viewer_ids'] = {}
        info['viewers'] = 0

        # Build a complete VOD playlist (with #EXT-X-ENDLIST) from all received
        # segments so the recording can be replayed from the beginning.
        try:
            out_dir = info['output_dir']

            def _seg_num(p):
                m = re.search(r'segment_(\d+)\.ts', os.path.basename(p))
                return int(m.group(1)) if m else 0

            segments = sorted(glob.glob(os.path.join(out_dir, 'segment_*.ts')), key=_seg_num)
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
                with open(os.path.join(out_dir, 'stream.m3u8'), 'w') as f:
                    f.write('\n'.join(lines) + '\n')
                info['vod'] = True
                info['duration'] = len(segments) * 2
        except Exception:
            pass

        _save_meta(info)
        return jsonify({'success': True, 'vod': info.get('vod', False)})

    # ==================== Stream Serving (pull by viewers) ====================

    def _decay_viewers(info):
        """Drop viewers we haven't seen within VIEWER_TTL and refresh the count.

        Called on read endpoints so the count falls back to 0 after the last
        viewer leaves, even though no one is polling the playlist anymore.

        Only LIVE ('streaming') streams have viewers. A finished recording must
        always report 0 live viewers -- otherwise replay/poller/load-test
        traffic to an ended stream keeps inflating the number on its card.
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
        """A copy of a stream's info without internal-only tracking fields."""
        return {k: v for k, v in info.items() if k not in ('viewer_ids', 'viewer_ips')}

    @app.route('/api/screen-stream/list')
    def list_screen_streams():
        """List all streams."""
        out = []
        for info in external_streams.values():
            _decay_viewers(info)
            out.append(_public_view(info))
        return jsonify(out)

    @app.route('/api/screen-stream/<stream_id>')
    def get_screen_stream_status(stream_id):
        """Status of one stream."""
        if stream_id not in external_streams:
            return jsonify({'error': 'Stream not found'}), 404
        info = external_streams[stream_id]
        _decay_viewers(info)
        return jsonify(_public_view(info))

    @app.route('/api/screen-stream/<stream_id>/stream.m3u8')
    def get_screen_stream_playlist(stream_id):
        """Serve the HLS playlist to a viewer (+ unique-viewer tracking)."""
        if stream_id not in external_streams:
            return jsonify({'error': 'Stream not found'}), 404

        playlist_path = os.path.join(external_streams[stream_id]['output_dir'], 'stream.m3u8')
        if not os.path.exists(playlist_path):
            return jsonify({'error': 'Stream playlist not found'}), 404

        with open(playlist_path, 'r') as f:
            playlist = f.read()

        # Count UNIQUE active viewers by a stable PER-BROWSER COOKIE, not by IP.
        # A single viewer can reach the server from several IPs (IPv4 vs IPv6
        # loopback, or a proxy/tunnel that rotates source addresses), which would
        # otherwise inflate the count. HLS players poll the playlist continuously,
        # so we refresh the viewer's timestamp on every poll and only count those
        # seen within VIEWER_TTL seconds.
        info = external_streams[stream_id]
        viewer_id = request.cookies.get('viewer_id')
        set_cookie = False
        if not viewer_id:
            viewer_id = uuid.uuid4().hex
            set_cookie = True

        now = time.time()
        # Only track/count viewers while the broadcast is LIVE. Once it has
        # ended the .m3u8 is a finished VOD; replaying it (or any leftover
        # poller / load-test client) must NOT keep growing the viewer count
        # shown on the ended card.
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
        if set_cookie:
            # 1-day cookie; SameSite=Lax is fine for same-origin player requests.
            resp.set_cookie('viewer_id', viewer_id, max_age=86400, samesite='Lax')
        return resp

    @app.route('/api/screen-stream/<stream_id>/<segment>')
    def get_screen_stream_segment(stream_id, segment):
        """Serve a single .ts segment to a viewer."""
        if stream_id not in external_streams:
            return jsonify({'error': 'Stream not found'}), 404

        segment_path = os.path.join(external_streams[stream_id]['output_dir'], segment)
        if not os.path.exists(segment_path):
            return jsonify({'error': 'Segment not found'}), 404

        return send_file(segment_path, mimetype='video/mp2t')

    @app.route('/api/screen-stream/<stream_id>/download')
    def download_recording(stream_id):
        """Download the recording as a single playable file.

        The recording lives on disk as many small .ts HLS segments, which a
        browser can't "Save As" on its own. Here we stitch them into ONE file:
        - If ffmpeg is available we remux (stream-copy, no re-encode) into an
          .mp4 -- the most universally playable/shareable container.
        - Otherwise we fall back to byte-concatenating the segments into a
          single .ts (valid MPEG-TS), which still plays in VLC/most players.
        """
        if stream_id not in external_streams:
            return jsonify({'error': 'Stream not found'}), 404

        info = external_streams[stream_id]
        out_dir = info['output_dir']

        def _seg_num(p):
            m = re.search(r'segment_(\d+)\.ts', os.path.basename(p))
            return int(m.group(1)) if m else 0

        segments = sorted(glob.glob(os.path.join(out_dir, 'segment_*.ts')), key=_seg_num)
        if not segments:
            return jsonify({'error': 'No recording available to download'}), 404

        # Build a filesystem-safe base name from the stream name.
        base_name = re.sub(r'[^A-Za-z0-9_-]+', '_',
                           info.get('name') or 'recording').strip('_') or 'recording'

        newest_seg_mtime = max(os.path.getmtime(s) for s in segments)

        # ---- Preferred path: remux to MP4 with ffmpeg -------------------
        ffmpeg = _find_ffmpeg()
        if ffmpeg:
            mp4_path = os.path.join(out_dir, 'recording.mp4')
            try:
                # Rebuild only if missing or older than the latest segment.
                if (not os.path.exists(mp4_path)
                        or os.path.getmtime(mp4_path) < newest_seg_mtime):
                    concat_list = os.path.join(out_dir, '_concat.txt')
                    with open(concat_list, 'w') as f:
                        for s in segments:
                            f.write(f"file '{os.path.basename(s)}'\n")
                    subprocess.run(
                        [ffmpeg, '-y', '-f', 'concat', '-safe', '0',
                         '-i', '_concat.txt',
                         '-c', 'copy', '-bsf:a', 'aac_adtstoasc',
                         '-movflags', '+faststart', 'recording.mp4'],
                        cwd=out_dir, capture_output=True, timeout=600,
                    )
                if os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 0:
                    return send_file(mp4_path, mimetype='video/mp4',
                                     as_attachment=True,
                                     download_name=f'{base_name}.mp4')
            except Exception:
                pass  # fall through to the .ts fallback

        # ---- Fallback: concatenate the raw .ts segments -----------------
        ts_path = os.path.join(out_dir, 'recording.ts')
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

    @app.route('/api/screen-stream/<stream_id>/delete', methods=['POST'])
    def delete_external_stream(stream_id):
        """Delete one recording (disk + memory)."""
        if stream_id not in external_streams:
            return jsonify({'error': 'Stream not found'}), 404
        output_dir = external_streams[stream_id].get('output_dir')
        if output_dir and os.path.exists(output_dir):
            try:
                shutil.rmtree(output_dir)
            except Exception:
                pass
        del external_streams[stream_id]
        return jsonify({'success': True})

    @app.route('/api/cleanup', methods=['POST'])
    def cleanup_old_streams():
        """Delete all ended/stopped recordings (disk + memory)."""
        cleaned = 0
        for stream_id in list(external_streams.keys()):
            info = external_streams[stream_id]
            if info.get('status') in ('ended', 'stopped'):
                output_dir = info.get('output_dir')
                if output_dir and os.path.exists(output_dir):
                    try:
                        shutil.rmtree(output_dir)
                    except Exception:
                        pass
                del external_streams[stream_id]
                cleaned += 1
        return jsonify({'cleaned': cleaned, 'message': f'Cleaned up {cleaned} stream(s)'})

    # ==================== Health / info ====================

    @app.route('/')
    def index():
        """Simple health/info endpoint (the engine has no UI of its own)."""
        return jsonify({
            'service': 'broadcasting-engine',
            'status': 'ok',
            'streams': len(external_streams),
            'hint': 'The viewer UI is a separate project (web-viewer).',
        })

    return app


if __name__ == '__main__':
    app = create_app()
    # threaded=True lets the server handle many viewers (playlist polls + segment
    # downloads) concurrently instead of one-at-a-time, which keeps playback smooth.
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG, threaded=True)
