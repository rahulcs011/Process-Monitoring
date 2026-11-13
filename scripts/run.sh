#!/bin/bash
# run.sh - starts the app.
#   ./scripts/run.sh                  -> GUI
#   ./scripts/run.sh schedule         -> CLI commands (schedule, monitor, tree, real)
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
    ./scripts/setup.sh || exit 1
fi
if [ $# -eq 0 ]; then
    exec .venv/bin/python main.py
else
    exec .venv/bin/python main.py --cli "$@"
fi
