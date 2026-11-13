#!/bin/bash
# run_tests.sh - runs the unit tests and a few CLI checks, saves a log.
cd "$(dirname "$0")/.."
PY=.venv/bin/python
LOG=tests/test_log.txt
fail=0

echo "== unit tests ==" | tee "$LOG"
$PY -m unittest discover -s tests -v 2>&1 | tee -a "$LOG"
[ "${PIPESTATUS[0]}" -eq 0 ] || fail=1

echo "== CLI checks ==" | tee -a "$LOG"
check() {
    # check "name" "text we expect" command...
    name=$1; expect=$2; shift 2
    if "$@" 2>&1 | grep -q -- "$expect"; then
        echo "PASS  $name" | tee -a "$LOG"
    else
        echo "FAIL  $name" | tee -a "$LOG"
        fail=1
    fi
}
check "compare all algorithms" "Round Robin" $PY main.py --cli schedule --algo all
check "round robin avg waiting" "Avg waiting 3.33" $PY main.py --cli schedule --algo rr -q 2
check "custom jobs" "Avg waiting 0.00" $PY main.py --cli schedule --algo fcfs --jobs "A:0:2,B:2:3"
check "bad job is rejected" "burst time must be more than 0" $PY main.py --cli schedule --jobs "A:0:0"
check "process monitor" "Top 5 by CPU" $PY main.py --cli monitor --top 5
check "process tree" "launchd\|systemd\|init" $PY main.py --cli tree --pid 1 --depth 1

if [ $fail -eq 0 ]; then
    echo "ALL TESTS PASSED" | tee -a "$LOG"
else
    echo "SOME TESTS FAILED (see $LOG)" | tee -a "$LOG"
fi
exit $fail
