#!/usr/bin/env bash
# Start the Web Viewer. Runs install.sh automatically on first use.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d venv ]; then
  echo "No venv found - running install.sh first..."
  bash install.sh
fi

if [ -f venv/Scripts/python.exe ]; then
  VENV_PY=venv/Scripts/python.exe
else
  VENV_PY=venv/bin/python
fi

echo "Starting Web Viewer on http://0.0.0.0:8080  (Ctrl+C to stop)"
echo "Open http://localhost:8080/live"
"$VENV_PY" app.py
