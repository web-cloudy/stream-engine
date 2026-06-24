# Screen Broadcast Client (Part 1)

The desktop application that captures a region of your screen and **pushes** it
as live HLS video to the [Broadcasting Engine](../broadcasting-engine).

```
┌──────────────────────────┐   HTTP push (HLS .ts + .m3u8)   ┌────────────────────────┐
│  Screen Broadcast Client  │ ───────────────────────────────▶│  Broadcasting Engine   │
│  (this project)           │   POST /api/stream-receiver/... │  (separate project)    │
└──────────────────────────┘                                  └────────────────────────┘
```

## What it does

1. You enter the engine's **Server Address** (e.g. `http://localhost:5000`).
2. You drag-select a screen region.
3. FFmpeg captures that region into rolling HLS segments.
4. A background loop uploads each segment + the playlist to the engine.
5. On **Stop**, it tells the engine to finalize a replayable recording.

## Requirements

- **Python 3.8+** (only to run from source / build the `.exe`)
- **FFmpeg** — downloaded automatically by `download_ffmpeg.py` into `./ffmpeg/`
- **Windows** — screen capture uses `gdigrab` (Windows only). Running from
  source on macOS/Linux would require changing the FFmpeg input device.

## Quick start (one-click install)

```bash
bash install.sh
```

This creates a virtual environment, installs dependencies, and downloads FFmpeg
into `./ffmpeg/`.

> On Windows you can run the script from **Git Bash** or **WSL**. If you only
> have PowerShell, see "Manual install" below.

## Run from source

One-click (launches the GUI with **no console window** via `pythonw`):

```bash
bash run.sh
```

Or manually:

```bash
# activate the venv created by install.sh
source venv/Scripts/activate    # Git Bash on Windows
# or: venv\Scripts\activate     # PowerShell/cmd

# Windows: use pythonw.exe so NO black cmd/console window appears
pythonw screen_capture_client.py
# (plain `python screen_capture_client.py` also works but opens a console)
```

> The app is a GUI, so it needs no console. The bundled `.exe` is already built
> windowed (`console=False`), and the FFmpeg capture process is spawned with
> `CREATE_NO_WINDOW`, so end users never see a command window.


## Build the standalone .exe

```bash
python build_client_exe.py
# → dist_client/ScreenCaptureClient.exe   (FFmpeg bundled inside)
```

Ship the single `ScreenCaptureClient.exe` to end users — no Python or FFmpeg
install required on their machine.

## Manual install

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
# source venv/bin/activate

pip install -r requirements.txt
python download_ffmpeg.py
```

## Files

| File | Purpose |
|------|---------|
| `screen_capture_client.py` | The Tkinter GUI: area selector, Start/Stop, status log, FFmpeg capture + uploader. |
| `download_ffmpeg.py` | Downloads `ffmpeg.exe`/`ffprobe.exe` into `./ffmpeg/`. |
| `build_client_exe.py` | PyInstaller build → `dist_client/ScreenCaptureClient.exe`. |
| `ScreenCaptureClient.spec` | PyInstaller spec used by the build. |
| `requirements.txt` | Python dependencies. |
| `install.sh` | One-click environment setup. |

## Troubleshooting

- **"Missing dependencies: FFmpeg"** — run `python download_ffmpeg.py` (or, for
  the built exe, place `ffmpeg.exe` in an `ffmpeg/` folder next to the exe).
- **Can't connect to server** — make sure the Broadcasting Engine is running and
  reachable at the Server Address you typed, and that port 5000 is open in the
  firewall.
