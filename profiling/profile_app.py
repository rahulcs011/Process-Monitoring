# profile_app.py
# Finds the slow parts of the project using cProfile (python's built in profiler).
#
#   python profiling/profile_app.py            -> timing table + cProfile reports
#   python profiling/profile_app.py --jobs 2000
#
# Reports are written to profiling/results/.

import argparse
import cProfile
import io
import os
import pstats
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from procsched import monitor
from procsched.scheduler import ALGORITHMS, random_jobs, run_algorithm

OUT = os.path.join(os.path.dirname(__file__), "results")


def time_it(func, repeat=3):
    best = None
    for _ in range(repeat):
        t = time.perf_counter()
        func()
        took = time.perf_counter() - t
        if best is None or took < best:
            best = took
    return best


def save_profile(name, func):
    prof = cProfile.Profile()
    prof.enable()
    func()
    prof.disable()
    prof.dump_stats(os.path.join(OUT, name + ".prof"))   # can be opened with snakeviz
    buf = io.StringIO()
    st = pstats.Stats(prof, stream=buf).strip_dirs().sort_stats("cumulative")
    st.print_stats(15)
    with open(os.path.join(OUT, name + ".txt"), "w") as f:
        f.write(buf.getvalue())
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=3000)
    ap.add_argument("--quantum", type=int, default=4)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    jobs = random_jobs(args.jobs, max_arrival=args.jobs * 2, max_burst=20, seed=42)
    lines = ["Scheduler timing with %d jobs (best of 3)" % args.jobs, ""]
    times = {}
    for algo in ALGORITHMS:
        times[algo] = time_it(lambda: run_algorithm(algo, jobs, args.quantum))
        lines.append("%-28s %8.4f s" % (algo, times[algo]))

    slowest = max(times, key=times.get)
    lines.append("")
    lines.append("Slowest: " + slowest)

    # monitor: how long does one snapshot of all processes take?
    monitor.snapshot()
    snap = time_it(monitor.snapshot)
    lines.append("")
    lines.append("monitor.snapshot() of %d processes: %.4f s" % (len(monitor.snapshot()), snap))

    summary = "\n".join(lines)
    print(summary)
    with open(os.path.join(OUT, "timing.txt"), "w") as f:
        f.write(summary + "\n")

    print("\n===== cProfile: %s =====" % slowest)
    print(save_profile("scheduler_profile", lambda: run_algorithm(slowest, jobs, args.quantum)))
    print("===== cProfile: monitor.snapshot =====")
    print(save_profile("monitor_profile", monitor.snapshot))


if __name__ == "__main__":
    main()
