#!/usr/bin/env bash
# Projecute one-command start for macOS and Linux: run `bash run.sh`.
# Creates a virtual environment, installs dependencies once, then starts the app
# and opens it in your browser.
set -e
cd "$(dirname "$0")"

# 1. Find Python.
PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then
  echo "Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/"
  exit 1
fi

# 2. Create the virtual environment the first time.
if [ ! -x .venv/bin/python ]; then
  echo "Creating a virtual environment..."
  "$PY" -m venv .venv
fi

# 3. Install dependencies once (a marker file remembers that it is done).
if [ ! -f .venv/.installed ]; then
  echo "Installing dependencies. This happens once and takes a few minutes..."
  .venv/bin/python -m pip install --upgrade pip
  # On Linux the default PyTorch build includes a 2 GB GPU runtime; the CPU build is enough.
  if [ "$(uname -s)" = "Linux" ]; then
    .venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
  fi
  .venv/bin/python -m pip install -r requirements.txt
  touch .venv/.installed
fi

# 4. Create .env from the example if it is missing.
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env. Add a free Groq key there for live AI; without it the app runs in demo mode."
fi

# 5. Start the app; it opens the browser once the server is ready.
OPEN_BROWSER=1 exec .venv/bin/python main.py
