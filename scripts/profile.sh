#!/bin/bash
# profile.sh - profiles the scheduler and the process monitor with cProfile
# and shows the before/after comparison of our optimisations.
#   ./scripts/profile.sh [number_of_jobs]
cd "$(dirname "$0")/.."
JOBS=${1:-3000}
PY=.venv/bin/python

echo "Running cProfile with $JOBS jobs..."
$PY profiling/profile_app.py --jobs "$JOBS" > /dev/null || exit 1

echo
echo "--------- BEFORE (first version) ---------"
cat profiling/results/timing_before.txt
echo
echo "--------- NOW ---------"
cat profiling/results/timing.txt

echo
echo "Top functions now (scheduler):"
sed -n '1,20p' profiling/results/scheduler_profile.txt

# memory + total time of a full CLI run, using the system 'time' command
echo
echo "Peak memory / time of one full CLI comparison run:"
if [ "$(uname)" = "Darwin" ]; then
    /usr/bin/time -l $PY main.py --cli schedule --algo all --random 2000 --seed 1 2>&1 >/dev/null \
        | grep -E "real|maximum resident"
else
    /usr/bin/time -v $PY main.py --cli schedule --algo all --random 2000 --seed 1 2>&1 >/dev/null \
        | grep -E "Elapsed|Maximum resident"
fi
echo
echo "Full reports: profiling/results/  (open .prof files with: pip install snakeviz; snakeviz file.prof)"
