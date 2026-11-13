#!/bin/bash
# stress.sh - starts some CPU-heavy background processes so the monitor
# has something to show during the demo. They are stopped automatically.
#   ./scripts/stress.sh [workers] [seconds]
WORKERS=${1:-2}
SECONDS_TO_RUN=${2:-30}
pids=()

cleanup() {
    for p in "${pids[@]}"; do kill "$p" 2>/dev/null; done
    echo "stopped all workers"
}
trap cleanup EXIT INT TERM

for i in $(seq 1 "$WORKERS"); do
    ( while :; do :; done ) &
    pids+=($!)
    echo "worker $i started, PID $!  (parent PID $$)"
done
echo "Look for these PIDs in the Processes / Process Tree tabs. Running $SECONDS_TO_RUN s..."
sleep "$SECONDS_TO_RUN"
