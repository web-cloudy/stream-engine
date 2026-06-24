# 📐 System Architecture — The 3 Parts

Your project is a live screen‑broadcasting system made of **3 independent parts**. They
talk to each other only over HTTP, so each part can run on a different machine.

```
┌──────────────────────────┐      HTTP push (HLS .ts + .m3u8)      ┌───────────────────────────┐
│  PART 1                   │  ───────────────────────────────▶    │  PART 2                    │
│  Screen Broadcast Client  │   POST /api/stream-receiver/...       │  Broadcasting Engine       │
│  (Windows .exe)           │                                       │  (Flask server)            │
│  Captures screen → FFmpeg │                                       │  Receives + stores + serves│
└──────────────────────────┘                                       └───────────┬───────────────┘
                                                                                │ HTTP pull
                                                                                │ (HLS playback)
                                                                                ▼
                                                                    ┌───────────────────────────┐
                                                                    │  PART 3                    │
                                                                    │  Web App (Viewer)          │
                                                                    │  Dashboard + player pages  │
                                                                    │  in any browser            │
                                                                    └───────────────────────────┘
```

> Note: **Part 2 (engine)** and **Part 3 (web app)** currently run inside the *same* Flask
> process (`app.py`). That is normal for a media server — the engine exposes the API and the
> web pages are served from the same app. They are still logically separate and could be
> split into two processes later. Part 1 is fully separate (a standalone .exe).

---

## 🧩 PART 1 — Screen Broadcast Client (the `.exe`)

**Job:** Let a user drag‑select a region of their screen, capture it with FFmpeg into HLS
segments, and **push** those segments to the engine over HTTP.

**Files**
| File | Purpose |
|------|---------|
| `screen_capture_client.py` | The Tkinter GUI app: area selector, Start/Stop, status log, FFmpeg capture loop, segment uploader. |
| `download_ffmpeg.py` | Downloads/locates the FFmpeg binary the client needs. |
| `build_client_exe.py` | PyInstaller build script → `dist_client/ScreenCaptureClient.exe` (bundles FFmpeg). |
| `ScreenCaptureClient.spec` | PyInstaller spec used by the build. |
| `dist_client/` | The built client + bundled `ffmpeg/`. This is what you ship to users. |

**How it works (data flow)**
1. User enters the **Server Address** (the engine URL, e.g. `http://SERVER-IP:5000`).
2. User selects a screen area → client sends `POST /api/stream-receiver/init`
   and receives a `stream_id` + upload endpoint.
3. FFmpeg captures the region → writes rolling HLS files (`segment_XXX.ts`, `stream.m3u8`).
4. A background loop uploads each new segment via
   `POST /api/stream-receiver/<stream_id>/segment` and the playlist via
   `.../playlist` (or as `is_playlist=true`).
5. On Stop → `POST /api/stream-receiver/<stream_id>/end`.

**Run / build**
```bat
:: run from source
python screen_capture_client.py

:: build the distributable exe
python build_client_exe.py
:: → dist_client\ScreenCaptureClient.exe
```

**Key requirement:** FFmpeg must be present. The exe bundles it in `dist_client/ffmpeg/`.
If you saw *"Missing dependencies: FFmpeg"*, the client couldn't find that binary.

---

## 🧩 PART 2 — Broadcasting Engine (the server)

**Job:** Receive pushed segments from clients, store them per‑stream, track stream state,
and **serve** the HLS playlist/segments back to viewers. Also finalizes a replayable
recording when a broadcast ends.

**File:** `app.py` (the integrated server). A standalone, streaming‑only variant also
exists as `app_streamserver.py`.

**Engine API (in `app.py`)**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/stream-receiver/init` | POST | Create a stream session + storage folder; returns `stream_id`. |
| `/api/stream-receiver/<id>/segment` | POST | Receive one `.ts` segment (or playlist) from the client. |
| `/api/stream-receiver/<id>/playlist` | POST | Receive/replace the live `.m3u8`. |
| `/api/stream-receiver/<id>/end` | POST | End the broadcast; **build a VOD playlist** (`#EXT-X-ENDLIST`) for replay. |
| `/api/screen-stream/list` | GET | List all streams (local + external/pushed). |
| `/api/screen-stream/<id>` | GET | Status of one stream. |
| `/api/screen-stream/<id>/stream.m3u8` | GET | Serve the HLS playlist to viewers (+ counts unique viewers). |
| `/api/screen-stream/<id>/<segment>` | GET | Serve a `.ts` segment to viewers. |
| `/api/screen-stream/<id>/delete` | POST | Delete one recording (disk + memory). |
| `/api/cleanup` | POST | Delete all ended/stopped recordings. |

**Where data lives:** `transcode_temp/external_streams/<stream_id>/`
(contains `segment_000.ts …` and `stream.m3u8`).

**State:** kept in the in‑memory `external_streams` dict (id, name, resolution, fps, status,
viewers, source IP, output dir, etc.).

**Notable logic added**
- **Viewer counting** — counts *unique active viewers by IP within the last 20s* instead of
  `+1` per playlist request (HLS players poll constantly, which previously made the number
  climb forever).
- **Replay (VOD)** — on `/end`, the engine lists every received `segment_*.ts`, sorts them
  numerically, and writes a complete VOD `stream.m3u8` ending with `#EXT-X-ENDLIST`, so the
  recording can be watched from the beginning afterward.

**Run**
```bat
python app.py
:: serves on http://0.0.0.0:5000  (listens on all interfaces for LAN clients)
```

---

## 🧩 PART 3 — Web App (the viewer)

**Job:** Let end‑users discover and watch streams in a browser — both **LIVE** and
**Replay** of finished broadcasts.

**Files**
| File | Purpose |
|------|---------|
| `templates/streaming_dashboard.html` | The **dashboard** at `/live`. Lists every stream with LIVE badge, resolution/fps, viewer count; buttons: *Watch*, *Stop*, *Replay*, *Delete*. Auto‑refreshes every 3s. Uses `hls.js`. |
| `templates/stream_viewer.html` | The single‑stream **player page** at `/viewer/<id>`. |

**Page routes (in `app.py`)**
| URL | Purpose |
|-----|---------|
| `/live` | Streaming dashboard (all streams). |
| `/viewer/<stream_id>` | Full‑page player for one stream (live or replay). |

**How viewers watch**
- Open `http://SERVER-IP:5000/live` → click **Watch Stream** (live) or **▶ Replay** (ended).
- Player loads `…/stream.m3u8` via `hls.js` and plays the `.ts` segments served by Part 2.
- There is a few seconds of normal HLS latency (2s segments + small buffer).

---

## 🔄 End‑to‑end flow (all 3 parts together)

```
USER A (broadcaster)                 SERVER (engine + web)                 USER B (viewer)
─────────────────────                ─────────────────────                ───────────────
ScreenCaptureClient.exe
  init ────────────────────────────▶ create session, return stream_id
  ffmpeg → segment_000.ts
  upload segment ──────────────────▶ save to external_streams/<id>/
  upload playlist ─────────────────▶ save stream.m3u8
                                     list shows status=streaming ◀──────── open /live (poll list)
                                     serve stream.m3u8 + .ts ─────────────▶ /viewer/<id> plays LIVE
  Stop → end ──────────────────────▶ write VOD playlist (#EXT-X-ENDLIST)
                                     status=ended, Replay available ◀───── /live shows ▶ Replay
```

---

## 🚀 Quick start (single machine)

1. **Engine + Web (Parts 2 & 3):**
   ```bat
   python app.py
   ```
2. **Client (Part 1):** run `dist_client\ScreenCaptureClient.exe`
   - Server Address: `http://localhost:5000`
   - Select Area → ▶ Start Broadcasting
3. **Watch (Part 3):** open `http://localhost:5000/live` in a browser.

## 🌐 Across machines (LAN)
- Run the engine on the server PC (`python app.py` — it already binds `0.0.0.0`).
- In the client on PC A, set Server Address to `http://<server-LAN-IP>:5000`.
- Viewers on any PC open `http://<server-LAN-IP>:5000/live`.
- Make sure the server's firewall allows inbound TCP **5000**.
