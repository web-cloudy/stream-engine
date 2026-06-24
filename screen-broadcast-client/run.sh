#!/usr/bin/env bash
# Start the Screen Broadcast Client GUI.
# On Windows we launch with pythonw.exe so NO console/cmd window appears
# (the app is a Tkinter GUI). Runs install.sh automatically on first use.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d venv ]; then
  echo "No venv found - running install.sh first..."
  bash install.sh
fi

# Prefer the windowed interpreter (pythonw) on Windows to avoid a console.
if [ -f venv/Scripts/pythonw.exe ]; then
  echo "Launching GUI (no console window)..."
  # Detach so the terminal returns immediately.
  start "" venv/Scripts/pythonw.exe screen_capture_client.py 2>/dev/null \
    || venv/Scripts/pythonw.exe screen_capture_client.py &
elif [ -f venv/Scripts/python.exe ]; then
  venv/Scripts/python.exe screen_capture_client.py
else
  venv/bin/python screen_capture_client.py
fi
