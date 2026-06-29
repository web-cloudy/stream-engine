"""
Single entry point for the Broadcasting Engine servers (packaged as one .exe).

One program, selectable role -- so Server A and Server B can each run as a
standalone executable with NO Python install:

    StreamEngineServer --role origin
        Server A: receives client uploads, stores them, serves the origin API.

    StreamEngineServer --role edge --origin http://<server-a>:5000
        Server B: mirrors A's live streams (runs the manager AND the relay
        together) and broadcasts to viewers.

    StreamEngineServer --role worker ...        (internal)
        One per-stream engine. The edge re-invokes THIS program in the worker
        role to spawn workers, so the whole thing ships as a single binary.

Config precedence: CLI flags  >  environment / a `.env` next to the exe  >  defaults.
Common flags: --host --port --storage --ffmpeg ; edge: --origin --poll-interval.
"""
import os
import sys
import argparse
import threading


def _base_dir():
    """Folder of the running program (the exe when frozen, else this script)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def main():
    parser = argparse.ArgumentParser(description='Broadcasting Engine server (origin / edge).')
    parser.add_argument('--role', choices=['origin', 'edge', 'worker'], default=None,
                        help='origin = Server A, edge = Server B (default), worker = internal.')
    parser.add_argument('--host', help='Bind address (default 0.0.0.0).')
    parser.add_argument('--port', type=int, help='Listen port (default 5000).')
    parser.add_argument('--storage', help='Where recordings are stored (TRANSCODE_TEMP_DIR).')
    parser.add_argument('--ffmpeg', help='Path to ffmpeg (optional; enables MP4 downloads).')
    parser.add_argument('--origin', help='[edge] Base URL of Server A, e.g. http://10.0.0.5:5000')
    parser.add_argument('--poll-interval', help='[edge] Relay poll interval seconds (default 1.0).')
    # Internal (worker role); ignored for origin/edge.
    parser.add_argument('--stream-id')
    parser.add_argument('--output-dir')
    parser.add_argument('--manager-pid', type=int)
    args, _ = parser.parse_known_args()

    base = _base_dir()

    # Load a `.env` sitting next to the program (does NOT override real env vars).
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(base, '.env'))
    except Exception:
        pass

    # CLI overrides -> environment, BEFORE importing modules that read env at
    # import time (config.py, relay.py).
    if args.host:           os.environ['HOST'] = args.host
    if args.port:           os.environ['PORT'] = str(args.port)
    if args.storage:        os.environ['TRANSCODE_TEMP_DIR'] = args.storage
    if args.ffmpeg:         os.environ['FFMPEG_PATH'] = args.ffmpeg
    if args.origin:         os.environ['ORIGIN_URL'] = args.origin
    if args.poll_interval:  os.environ['POLL_INTERVAL'] = args.poll_interval

    # Keep recordings next to the program by default, so data is predictable.
    os.environ.setdefault('TRANSCODE_TEMP_DIR', os.path.join(base, 'transcode_temp'))

    role = args.role or os.getenv('ROLE') or 'edge'
    if role == 'origin':
        _run_origin()
    elif role == 'worker':
        _run_worker(args)
    else:
        _run_edge()


def _run_origin():
    """Server A: the all-in-one origin engine (ingest + store + serve)."""
    from config import Config
    import app as origin_app
    application = origin_app.create_app()
    print(f'[origin] Server A on http://{Config.HOST}:{Config.PORT}  (Ctrl+C to stop)')
    application.run(host=Config.HOST, port=Config.PORT, threaded=True, use_reloader=False)


def _run_worker(args):
    """Internal: one per-stream engine, spawned by the edge manager."""
    import single_engine
    if args.manager_pid:
        threading.Thread(target=single_engine._exit_when_parent_dies,
                         args=(args.manager_pid,), daemon=True).start()
    application = single_engine.create_app(args.stream_id, os.path.abspath(args.output_dir))
    application.run(host=args.host or '127.0.0.1', port=args.port,
                    threaded=True, debug=False, use_reloader=False)


def _run_edge():
    """Server B: the manager (serves viewers) + the relay (mirrors Server A)."""
    import atexit
    import signal
    from config import Config
    import manager
    import relay

    # Same lifecycle the manager sets up when run as a script.
    atexit.register(manager._shutdown_all_workers)

    def _term(signum, frame):
        manager._shutdown_all_workers()
        os._exit(0)
    try:
        signal.signal(signal.SIGTERM, _term)
    except Exception:
        pass

    threading.Thread(target=manager._reaper_loop, daemon=True).start()
    # The relay mirrors Server A into this engine (no-op if ORIGIN_URL is unset).
    threading.Thread(target=relay.discovery_loop, daemon=True).start()

    application = manager.create_app()
    print(f'[edge] Server B on http://{Config.HOST}:{Config.PORT}  '
          f'origin={os.getenv("ORIGIN_URL") or "(NONE set -- nothing to mirror!)"}  '
          f'(Ctrl+C to stop)')
    application.run(host=Config.HOST, port=Config.PORT, threaded=True, use_reloader=False)


if __name__ == '__main__':
    main()
