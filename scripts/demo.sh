#!/bin/bash
# demo.sh - terminal demo used during the presentation (press Enter between steps).
cd "$(dirname "$0")/.."
PY=.venv/bin/python
step() { echo; echo "=================== $1 ==================="; read -r -p "(press Enter)"; }

step "1. System and top processes"
$PY main.py --cli monitor --top 8

step "2. Process hierarchy starting from PID 1"
$PY main.py --cli tree --pid 1 --depth 1 | head -25

step "3. Compare FCFS, Priority and Round Robin"
$PY main.py --cli schedule --algo all

step "4. Real processes with Round Robin (SIGSTOP / SIGCONT)"
$PY main.py --cli real --algo rr -q 0.4

step "5. Profiling"
./scripts/profile.sh 3000

step "6. Open the GUI"
$PY main.py
