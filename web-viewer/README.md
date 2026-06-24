# Web Viewer (Part 3)

The browser-facing web app. It serves the **live dashboard** and the
**single-stream player** pages. It stores no video itself — every API/HLS
request goes to the [Broadcasting Engine](../broadcasting-engine) (Part 2),
whose base URL is injected into the pages as `window.ENGINE_URL`.

```
┌────────────────────────┐   HTTP (CORS)   ┌──────────────┐   page request   ┌─────────┐
│  Broadcasting Engine    │◀───────────────│  Web Viewer  │◀────────────────│ Browser │
│  (Part 2, API)          │   API + HLS     │ (this app)   │   HTML/JS pages  │         │
└────────────────────────┘                 └──────────────┘                  └─────────┘
```

## Requirements

- **Python 3.8+**
- A running **Broadcasting Engine** reachable from the viewer's browser.

## Quick start (one-click install + run)

```bash
bash install.sh        # create venv, install deps, create .env
bash run.sh            # serve the viewer on http://0.0.0.0:8080
```

Then open `http://localhost:8080/live`.

> On Windows use **Git Bash** or **WSL** to run the scripts, or follow the
> "Manual" steps below in PowerShell.

## Configure the engine URL

Edit `.env` and set `ENGINE_URL` to where your engine runs:

```ini
ENGINE_URL=http://localhost:5000     # same machine
# ENGINE_URL=http://192.168.1.50:5000  # engine on another LAN machine
```

> ⚠️ `ENGINE_URL` is used by the **viewer's browser**, not by this server. When
> viewers are on other machines, it must be the engine's LAN IP / public host
> (not `localhost`). The engine already enables CORS for cross-origin requests.

## Manual

```bash
python -m venv venv
venv\Scripts\activate            # Windows  (source venv/bin/activate on *nix)
pip install -r requirements.txt
copy .env.example .env           # cp .env.example .env on *nix
python app.py
```

## Production

```bash
# Linux/Mac
gunicorn -w 2 -b 0.0.0.0:8080 "app:create_app()"

# Windows
waitress-serve --listen=0.0.0.0:8080 --call app:create_app
```

## Pages

| URL | Purpose |
|-----|---------|
| `/` | Redirects to `/live`. |
| `/live` | Dashboard of all streams (LIVE + ended), auto-refreshes every 3s. |
| `/viewer/<stream_id>` | Full-page player for one stream (live or replay). |

## Configuration (`.env`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENGINE_URL` | `http://localhost:5000` | Engine base URL used by the browser. |
| `HOST` | `0.0.0.0` | Bind address for this web app. |
| `PORT` | `8080` | Listen port for this web app. |
| `DEBUG` | `true` | Flask debug mode. |

## Files

| File | Purpose |
|------|---------|
| `app.py` | Flask app that serves the pages and injects `ENGINE_URL`. |
| `config.py` | Configuration (reads `.env`). |
| `templates/streaming_dashboard.html` | The dashboard. |
| `templates/stream_viewer.html` | The single-stream player. |
| `requirements.txt` | Python dependencies. |
| `install.sh` / `run.sh` | One-click setup and start. |
