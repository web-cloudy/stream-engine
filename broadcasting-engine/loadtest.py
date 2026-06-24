"""
Viewer load test for the Broadcasting Engine.

Simulates many concurrent HLS viewers. Each virtual viewer behaves like a real
player: it polls the .m3u8 playlist every couple seconds, parses the segment
list, and downloads the newest segments it hasn't seen yet. We measure request
success/failure, latency, and total bandwidth to estimate how many simultaneous
viewers the server can sustain.

USAGE
-----
1) Start a broadcast first (run app.py + the Screen Capture Client) so there is
   a live stream to watch.

2) Fixed load (e.g. 100 viewers for 30s):
     python loadtest.py --url http://localhost:5000 --viewers 100 --duration 30

3) Auto ramp-up to find the max (steps until errors/latency cross a threshold):
     python loadtest.py --url http://localhost:5000 --ramp

   The stream is auto-detected from /api/screen-stream/list (first "streaming"
   one). You can also pass --stream-id <id> explicitly.

NOTE: All virtual viewers come from this machine's IP, so the dashboard's
"viewers" number won't match (it counts unique IPs). This tool measures server
*capacity*, not the unique-viewer counter.
"""
import argparse
import statistics
import sys
import threading
import time

try:
    import requests
except ImportError:
    print("This tool needs the 'requests' package:  pip install requests")
    sys.exit(1)


def pick_stream(base_url):
    """Return the id of the first 'streaming' stream, else the first stream."""
    r = requests.get(f"{base_url}/api/screen-stream/list", timeout=10)
    r.raise_for_status()
    streams = r.json()
    if not streams:
        return None
    for s in streams:
        if s.get('status') == 'streaming':
            return s['id']
    return streams[0]['id']


def seed_stream(base_url, n_segments=6, seg_kb=600, name='LoadTest (synthetic)'):
    """Create a synthetic live stream by pushing dummy segments via the API.

    Lets you run the capacity test without the GUI client / real screen capture.
    The segments are random bytes (~seg_kb each, mimicking a ~2s @ 2.5Mbps chunk);
    the load test only downloads them, so they don't need to be real video.
    """
    import os
    r = requests.post(f"{base_url}/api/stream-receiver/init",
                      json={'name': name, 'width': 1280, 'height': 720, 'fps': 30},
                      timeout=10)
    r.raise_for_status()
    stream_id = r.json()['stream_id']

    blob = os.urandom(seg_kb * 1024)
    for i in range(n_segments):
        requests.post(f"{base_url}/api/stream-receiver/{stream_id}/segment",
                     files={'segment': (f'segment_{i:03d}.ts', blob)},
                     data={'segment_number': i}, timeout=30)

    lines = ['#EXTM3U', '#EXT-X-VERSION:3', '#EXT-X-TARGETDURATION:2',
             '#EXT-X-MEDIA-SEQUENCE:0']
    for i in range(n_segments):
        lines += ['#EXTINF:2.000,', f'segment_{i:03d}.ts']
    requests.post(f"{base_url}/api/stream-receiver/{stream_id}/playlist",
                 json={'playlist': '\n'.join(lines) + '\n'}, timeout=15)

    print(f"Seeded synthetic stream {stream_id} "
          f"({n_segments} x {seg_kb}KB segments).")
    return stream_id



class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.playlist_ok = 0
        self.playlist_fail = 0
        self.segment_ok = 0
        self.segment_fail = 0
        self.bytes = 0
        self.playlist_latency = []
        self.segment_latency = []

    def add_playlist(self, ok, latency):
        with self.lock:
            if ok:
                self.playlist_ok += 1
                self.playlist_latency.append(latency)
            else:
                self.playlist_fail += 1

    def add_segment(self, ok, latency, nbytes):
        with self.lock:
            if ok:
                self.segment_ok += 1
                self.segment_latency.append(latency)
                self.bytes += nbytes
            else:
                self.segment_fail += 1


def parse_segments(playlist_text):
    return [ln.strip() for ln in playlist_text.splitlines()
            if ln.strip() and not ln.startswith('#')]


def viewer_worker(base_url, stream_id, stop_at, metrics, stop_event):
    """One virtual viewer: poll playlist + download new segments until stop."""
    session = requests.Session()
    playlist_url = f"{base_url}/api/screen-stream/{stream_id}/stream.m3u8"
    seg_base = f"{base_url}/api/screen-stream/{stream_id}/"
    seen = set()

    while time.time() < stop_at and not stop_event.is_set():
        # 1) Fetch playlist
        t0 = time.time()
        try:
            r = session.get(playlist_url, timeout=15)
            ok = r.status_code == 200
            metrics.add_playlist(ok, time.time() - t0)
            segments = parse_segments(r.text) if ok else []
        except Exception:
            metrics.add_playlist(False, time.time() - t0)
            segments = []

        # 2) Download the newest few segments we haven't fetched yet
        for seg in segments[-3:]:
            if seg in seen:
                continue
            seen.add(seg)
            t1 = time.time()
            try:
                rs = session.get(seg_base + seg, timeout=20)
                metrics.add_segment(rs.status_code == 200,
                                    time.time() - t1, len(rs.content))
            except Exception:
                metrics.add_segment(False, time.time() - t1, 0)

        # Real players poll roughly once per segment duration (~2s)
        time.sleep(2.0)


def run_phase(base_url, stream_id, n_viewers, duration):
    """Run n_viewers concurrently for `duration` seconds; return a report dict."""
    metrics = Metrics()
    stop_event = threading.Event()
    stop_at = time.time() + duration
    threads = []

    for _ in range(n_viewers):
        t = threading.Thread(target=viewer_worker,
                             args=(base_url, stream_id, stop_at, metrics, stop_event),
                             daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.01)  # small stagger so we don't thundering-herd connect

    for t in threads:
        t.join(timeout=duration + 30)

    total_req = (metrics.playlist_ok + metrics.playlist_fail +
                 metrics.segment_ok + metrics.segment_fail)
    total_fail = metrics.playlist_fail + metrics.segment_fail
    err_rate = (total_fail / total_req * 100) if total_req else 0.0

    def p95(xs):
        if not xs:
            return 0.0
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(len(xs) * 0.95))]

    return {
        'viewers': n_viewers,
        'duration': duration,
        'requests': total_req,
        'failures': total_fail,
        'err_rate': err_rate,
        'playlist_p95_ms': p95(metrics.playlist_latency) * 1000,
        'segment_p95_ms': p95(metrics.segment_latency) * 1000,
        'segment_avg_ms': (statistics.mean(metrics.segment_latency) * 1000
                           if metrics.segment_latency else 0),
        'mbytes': metrics.bytes / 1_000_000,
        'mbps': (metrics.bytes * 8 / 1_000_000 / duration) if duration else 0,
    }


def print_report(rep):
    print(f"  viewers={rep['viewers']:<5} requests={rep['requests']:<6} "
          f"failures={rep['failures']:<4} err={rep['err_rate']:.1f}%  "
          f"seg_p95={rep['segment_p95_ms']:.0f}ms  "
          f"throughput={rep['mbps']:.1f} Mbps")


def main():
    ap = argparse.ArgumentParser(description="HLS viewer load test")
    ap.add_argument('--url', default='http://localhost:5000', help='Server base URL')
    ap.add_argument('--stream-id', default=None, help='Stream id (auto-detect if omitted)')
    ap.add_argument('--viewers', type=int, default=50, help='Concurrent viewers (fixed mode)')
    ap.add_argument('--duration', type=int, default=30, help='Seconds per phase')
    ap.add_argument('--ramp', action='store_true', help='Ramp up to find the max')
    ap.add_argument('--steps', default='10,25,50,100,200,400,800',
                    help='Comma-separated viewer counts for --ramp')
    ap.add_argument('--max-err', type=float, default=2.0, help='Stop ramp above this %% error')
    ap.add_argument('--max-p95', type=float, default=3000.0,
                    help='Stop ramp above this segment p95 latency (ms)')
    ap.add_argument('--seed', action='store_true',
                    help='Create a synthetic stream first (no GUI client needed)')
    ap.add_argument('--seg-kb', type=int, default=600,
                    help='Synthetic segment size in KB (default 600 ~ 2s @ 2.5Mbps)')
    args = ap.parse_args()

    base_url = args.url.rstrip('/')

    if args.seed:
        stream_id = seed_stream(base_url, seg_kb=args.seg_kb)
    else:
        stream_id = args.stream_id or pick_stream(base_url)
        if not stream_id:
            print("No active stream found -> seeding a synthetic one for the test.")
            print("(Use a real broadcast for true video, or pass --seed explicitly.)")
            stream_id = seed_stream(base_url, seg_kb=args.seg_kb)
    print(f"Target server : {base_url}")
    print(f"Target stream : {stream_id}\n")


    if not args.ramp:
        print(f"Running {args.viewers} viewers for {args.duration}s...")
        rep = run_phase(base_url, stream_id, args.viewers, args.duration)
        print_report(rep)
        print(f"\nTotal downloaded: {rep['mbytes']:.1f} MB  "
              f"(avg segment latency {rep['segment_avg_ms']:.0f} ms)")
        return

    # Ramp mode: step up until error rate or latency crosses the threshold.
    steps = [int(x) for x in args.steps.split(',') if x.strip()]
    print(f"Ramp-up test (stop when err>{args.max_err}% or seg_p95>{args.max_p95:.0f}ms)\n")
    last_good = 0
    for n in steps:
        rep = run_phase(base_url, stream_id, n, args.duration)
        print_report(rep)
        if rep['err_rate'] > args.max_err or rep['segment_p95_ms'] > args.max_p95:
            print(f"\n==> Limit reached around {n} viewers.")
            print(f"==> Last healthy level: ~{last_good} simultaneous viewers.")
            break
        last_good = n
        time.sleep(2)
    else:
        print(f"\n==> Server handled the full ramp ({last_good} viewers) without "
              f"crossing thresholds. Increase --steps to push further.")


if __name__ == '__main__':
    main()
