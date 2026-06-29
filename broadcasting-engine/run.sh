#!/usr/bin/env bash
# Start the Broadcasting Engine. Runs install.sh automatically on first use.
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

echo "Starting Broadcasting Manager on http://0.0.0.0:5000  (Ctrl+C to stop)"
echo "  (spawns one engine worker per stream; clients/viewers use this one address)"
# manager.py is the gateway/bot: it launches one single_engine.py worker per
# stream and proxies traffic to it. To run the old all-in-one engine instead,
# use: "$VENV_PY" app.py
"$VENV_PY" manager.py
