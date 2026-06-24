#!/usr/bin/env bash
# One-click installer for the Screen Broadcast Client (Part 1).
# Creates a virtual environment, installs Python deps, and downloads FFmpeg.
set -euo pipefail

cd "$(dirname "$0")"

echo "============================================================"
echo " Screen Broadcast Client - setup"
echo "============================================================"

# --- pick a python ---------------------------------------------------------
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  if command -v python >/dev/null 2>&1; then PY=python
  elif command -v python3 >/dev/null 2>&1; then PY=python3
  elif command -v py >/dev/null 2>&1; then PY="py -3"
  else
    echo "ERROR: Python 3.8+ not found. Install it from https://www.python.org/downloads/"
    exit 1
  fi
fi
echo "Using Python: $($PY --version 2>&1)"

# --- virtual environment ---------------------------------------------------
if [ ! -d venv ]; then
  echo "Creating virtual environment (venv)..."
  $PY -m venv venv
fi

# venv layout differs between Windows (Scripts) and *nix (bin)
if [ -f venv/Scripts/python.exe ]; then
  VENV_PY=venv/Scripts/python.exe
else
  VENV_PY=venv/bin/python
fi

echo "Upgrading pip..."
"$VENV_PY" -m pip install --upgrade pip

echo "Installing dependencies..."
"$VENV_PY" -m pip install -r requirements.txt

# --- ffmpeg ----------------------------------------------------------------
if [ -f ffmpeg/ffmpeg.exe ] || [ -f ffmpeg/ffmpeg ]; then
  echo "FFmpeg already present in ./ffmpeg - skipping download."
else
  echo "Downloading FFmpeg into ./ffmpeg ..."
  "$VENV_PY" download_ffmpeg.py || echo "WARNING: FFmpeg download failed. Run 'python download_ffmpeg.py' manually."
fi

echo
echo "============================================================"
echo " Done!"
echo "------------------------------------------------------------"
echo " Run from source : $VENV_PY screen_capture_client.py"
echo " Build the .exe  : $VENV_PY build_client_exe.py"
echo "============================================================"
