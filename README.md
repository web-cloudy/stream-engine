
A live screen-broadcasting system split into **3 independent projects**. They
communicate only over HTTP, so each can be developed, deployed, and run on a
separate machine.

```
┌──────────────────────────┐   push (HLS)   ┌────────────────────────┐   pull (HLS)   ┌──────────────┐
│  screen-broadcast-client  │ ──────────────▶│  broadcasting-engine   │◀───────────────│  web-viewer  │
│  Part 1 — desktop capture │                │  Part 2 — API server   │                │  Part 3 — UI │
└──────────────────────────┘                └────────────────────────┘                └──────────────┘
```

| Folder | Part | What it is | Default port |
|--------|------|-----------|--------------|
| [`screen-broadcast-client/`](screen-broadcast-client) | 1 | Windows desktop app (Tkinter + FFmpeg) that captures a screen region and pushes it as live HLS. Builds to a standalone `.exe`. | — |
| [`broadcasting-engine/`](broadcasting-engine) | 2 | Headless Flask **API** that receives, stores, and serves the streams (+ VOD replay). | `5000` |
| [`web-viewer/`](web-viewer) | 3 | Flask **web app** with the dashboard + player pages. Talks to the engine over HTTP/CORS. | `8080` |

See [`ARCHITECTURE_3PARTS.md`](ARCHITECTURE_3PARTS.md) for the detailed design.

## Each project is self-contained

Every folder has its own:
- `requirements.txt` — its Python dependencies
- `README.md` — its own setup/build/run documentation
- `install.sh` — one-click environment setup
- `run.sh` (engine & viewer) — one-click start

## Quick start (single machine)

Run each in its own terminal. On Windows use **Git Bash** or **WSL** for the
`bash` scripts (or follow each project's "Manual" instructions for PowerShell).

```bash
# 1) Broadcasting Engine (Part 2)
cd broadcasting-engine
bash install.sh && bash run.sh          # http://localhost:5000

# 2) Web Viewer (Part 3)         — new terminal
cd web-viewer
bash install.sh && bash run.sh          # http://localhost:8080/live
#   (default ENGINE_URL is http://localhost:5000)

# 3) Screen Broadcast Client (Part 1)  — new terminal
cd screen-broadcast-client
bash install.sh
python screen_capture_client.py         # Server Address: http://localhost:5000
#   or build the .exe:  python build_client_exe.py
```

Then open **http://localhost:8080/live**, start a broadcast from the client, and
click **Watch**.

## Across machines (LAN)

- Run **broadcasting-engine** on the server PC (binds `0.0.0.0:5000`).
- In **screen-broadcast-client**, set *Server Address* to `http://<engine-ip>:5000`.
- In **web-viewer**, set `ENGINE_URL=http://<engine-ip>:5000` in its `.env`
  (this URL is used by viewers' browsers, so it must be the engine's reachable
  LAN IP, not `localhost`).
- Open the viewer at `http://<viewer-host>:8080/live`.
- Allow inbound TCP **5000** (engine) and **8080** (viewer) in the firewall.

## What changed from the original single-folder project

Parts 2 and 3 used to run inside one Flask process. They are now two separate
apps: the engine is a pure API (CORS enabled) and the viewer is a thin Flask app
that serves the pages and points its browser-side JS at the engine via
`ENGINE_URL`. Part 1 was already standalone.
