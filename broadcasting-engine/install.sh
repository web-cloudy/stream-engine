#!/usr/bin/env bash
# One-click installer for the Broadcasting Engine (Part 2).
# Creates a virtual environment, installs deps, and prepares .env.
set -euo pipefail

cd "$(dirname "$0")"

echo "============================================================"
echo " Broadcasting Engine - setup"
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

if [ -f venv/Scripts/python.exe ]; then
  VENV_PY=venv/Scripts/python.exe
else
  VENV_PY=venv/bin/python
fi

echo "Upgrading pip..."
"$VENV_PY" -m pip install --upgrade pip

echo "Installing dependencies..."
"$VENV_PY" -m pip install -r requirements.txt

# --- .env ------------------------------------------------------------------
if [ ! -f .env ]; then
  echo "Creating .env from template..."
  cp .env.example .env
fi

echo
echo "============================================================"
echo " Done! Start the engine with:  bash run.sh"
echo " (or: $VENV_PY app.py)"
echo " It listens on http://0.0.0.0:5000"
echo "============================================================"
