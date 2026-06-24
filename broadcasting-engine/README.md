# Broadcasting Engine (Part 2)

The server in the middle. It **receives** pushed HLS segments from the
[Screen Broadcast Client](../screen-broadcast-client), stores them per stream,
and **serves** them back to the [Web Viewer](../web-viewer). When a broadcast
ends it finalizes a replayable VOD recording.

```
┌───────────────────────────┐   push    ┌────────────────────────┐   pull    ┌──────────────┐
│  Screen Broadcast Client   │ ─────────▶│  Broadcasting Engine   │◀───────── │  Web Viewer  │
│  (Part 1)                  │           │  (this project, API)   │           │  (Part 3)    │
└───────────────────────────┘           └────────────────────────┘           └──────────────┘
```

This project is a **pure API** (no UI). CORS is enabled so the Web Viewer can
run on a different host/port.

## Requirements

- **Python 3.8+**
- **FFmpeg** (optional) — only used by the "download recording as MP4" endpoint.
  If absent, downloads fall back to a concatenated `.ts` file.

## Quick start (one-click install + run)

```bash
bash install.sh        # create venv, install deps, create .env
bash run.sh            # start the engine on http://0.0.0.0:5000
```

> On Windows use **Git Bash** or **WSL** to run the scripts, or follow the
> "Manual" steps below in PowerShell.

## Manual

```bash
python -m venv venv
venv\Scripts\activate            # Windows  (source venv/bin/activate on *nix)
pip install -r requirements.txt
copy .env.example .env           # cp .env.example .env on *nix
python app.py
```

The server starts at `http://localhost:5000` and binds `0.0.0.0` so LAN clients
and viewers can reach it. Make sure inbound TCP **5000** is allowed by the
firewall.

## Production

```bash
# Linux/Mac
gunicorn -w 4 -b 0.0.0.0:5000 "app:create_app()"

# Windows
waitress-serve --listen=0.0.0.0:5000 --call app:create_app
```

## API

### Reception (client → engine)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/stream-receiver/init` | POST | Create a stream session + storage folder; returns `stream_id`. |
| `/api/stream-receiver/<id>/segment` | POST | Receive one `.ts` segment (or playlist). |
| `/api/stream-receiver/<id>/playlist` | POST | Receive/replace the live `.m3u8`. |
| `/api/stream-receiver/<id>/end` | POST | End the broadcast; build a VOD playlist for replay. |

### Serving (viewer → engine)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/screen-stream/list` | GET | List all streams. |
| `/api/screen-stream/<id>` | GET | Status of one stream. |
| `/api/screen-stream/<id>/stream.m3u8` | GET | Serve the HLS playlist (+ unique-viewer count). |
| `/api/screen-stream/<id>/<segment>` | GET | Serve a `.ts` segment. |
| `/api/screen-stream/<id>/download` | GET | Download the recording as MP4 (or `.ts`). |
| `/api/screen-stream/<id>/delete` | POST | Delete one recording. |
| `/api/cleanup` | POST | Delete all ended/stopped recordings. |
| `/` | GET | Health/info JSON. |

## Configuration (`.env`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `TRANSCODE_TEMP_DIR` | `./transcode_temp` | Where recordings are stored. |
| `FFMPEG_PATH` | `ffmpeg` | FFmpeg binary for MP4 download. |
| `HOST` | `0.0.0.0` | Bind address. |
| `PORT` | `5000` | Listen port. |
| `DEBUG` | `true` | Flask debug mode. |

## Load testing

`loadtest.py` simulates many concurrent HLS viewers to estimate capacity:

```bash
python loadtest.py --url http://localhost:5000 --viewers 100 --duration 30
python loadtest.py --url http://localhost:5000 --ramp          # find the max
python loadtest.py --url http://localhost:5000 --seed          # no client needed
```

## Files

| File | Purpose |
|------|---------|
| `app.py` | The Flask API server. |
| `config.py` | Configuration (reads `.env`). |
| `loadtest.py` | Viewer capacity load-tester. |
| `requirements.txt` | Python dependencies. |
| `install.sh` / `run.sh` | One-click setup and start. |
