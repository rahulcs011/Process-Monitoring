#!/bin/bash
# setup.sh - creates the virtual environment and installs the libraries.
# Usage: ./scripts/setup.sh
set -e
cd "$(dirname "$0")/.."

# pick a python that has a working Tk (apple's /usr/bin/python3 has Tk 8.5 which freezes)
PY=""
for p in "$PYTHON" python3.12 python3.13 python3.11 python3; do
    if [ -n "$p" ] && command -v "$p" >/dev/null 2>&1; then
        if "$p" -c "import tkinter, sys; sys.exit(0 if tkinter.TkVersion >= 8.6 else 1)" 2>/dev/null; then
            PY=$(command -v "$p")
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "No python with Tk 8.6+ found."
    echo "On macOS run:  brew install python-tk@3.12"
    echo "On Ubuntu run: sudo apt install python3-tk python3-venv"
    exit 1
fi
echo "Using $PY ($("$PY" --version))"

if [ ! -d .venv ]; then
    "$PY" -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -c "import psutil, matplotlib, tkinter; print('psutil', psutil.__version__, '| matplotlib', matplotlib.__version__, '| Tk', tkinter.TkVersion)"
echo "Setup done. Start the app with ./scripts/run.sh"
