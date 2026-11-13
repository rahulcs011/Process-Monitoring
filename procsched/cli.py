# cli.py - terminal version of the app (useful when there is no display)
import argparse
import os
import time

from . import monitor as mon
from .executor import REAL_ALGORITHMS, RealScheduler
from .scheduler import (ALGORITHMS, ROUND_ROBIN, ascii_gantt, compare_all, example_jobs,
                        parse_jobs, random_jobs, run_algorithm, stats_table)

ALIASES = {"fcfs": ALGORITHMS[0], "fifo": ALGORITHMS[0], "priority": ALGORITHMS[1],
           "priority-np": ALGORITHMS[1], "priority-p": ALGORITHMS[2], "rr": ROUND_ROBIN}


def cmd_monitor(args):
    mon.snapshot()            # first call primes per-process CPU counters
    time.sleep(1.0)
    procs = mon.snapshot()
    s = mon.system_stats(procs)
    print(f"CPU {s.cpu_total:.1f}%  |  Mem {s.mem_percent:.1f}% ({s.mem_used_gb:.1f}/{s.mem_total_gb:.1f} GB)  |  "
          f"Load {' '.join(f'{x:.2f}' for x in s.load_avg)}  |  {s.process_count} processes, {s.thread_count} threads")
    print("States:", ", ".join(f"{k}={v}" for k, v in sorted(s.status_counts.items())))
    print(f"\nTop {args.top} by CPU:")
    print(f"{'PID':>7} {'PPID':>7} {'CPU%':>6} {'MEM%':>6} {'STATUS':<10} NAME")
    for p in sorted(procs, key=lambda p: p.cpu, reverse=True)[:args.top]:
        print(f"{p.pid:>7} {p.ppid:>7} {p.cpu:>6.1f} {p.mem:>6.2f} {p.status:<10} {p.name}")
    print("\nAncestry of this program:")
    by_pid = {p.pid: p for p in procs}
    print("  <-  ".join(f"{by_pid[c].name}({c})" for c in mon.ancestors(os.getpid(), procs)))


def cmd_tree(args):
    procs = mon.snapshot()
    root = args.pid
    print(mon.tree_text(procs, root=root, max_depth=args.depth))


def _jobs(args):
    if args.jobs:
        return parse_jobs(args.jobs)
    if args.random:
        return random_jobs(args.random, seed=args.seed)
    return example_jobs()


def cmd_schedule(args):
    jobs = _jobs(args)
    results = compare_all(jobs, args.quantum) if args.algo == "all" else [run_algorithm(ALIASES[args.algo], jobs, args.quantum)]
    for r in results:
        title = r.algorithm + (f" (quantum={args.quantum})" if r.quantum else "")
        print("=" * 64 + f"\n{title}\n" + "=" * 64)
        print(ascii_gantt(r) + "\n")
        print(stats_table(r) + "\n")
    if len(results) > 1:
        print(f"{'Algorithm':<28}{'AvgWait':>9}{'AvgTAT':>9}{'AvgResp':>9}{'CtxSw':>7}")
        for r in results:
            a = r.averages
            print(f"{r.algorithm:<28}{a['avg_waiting']:>9.2f}{a['avg_turnaround']:>9.2f}"
                  f"{a['avg_response']:>9.2f}{a['context_switches']:>7}")


def cmd_real(args):
    jobs = _jobs(args)
    for j in jobs:  # interpret burst as CPU seconds, scaled down so the demo is quick
        j.burst = j.burst * args.scale
        j.arrival = j.arrival * args.scale
    s = RealScheduler(jobs, ALIASES[args.algo], args.quantum, on_event=print)
    s.start()
    try:
        s.join()
    except KeyboardInterrupt:
        s.stop()
        s.join()
    if s.result:
        print()
        print(ascii_gantt(s.result))
        print(stats_table(s.result))


def main(argv=None):
    p = argparse.ArgumentParser(prog="main.py --cli", description="CPU/Process monitor and job scheduler (CLI)")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("monitor", help="system stats and top processes")
    m.add_argument("--top", type=int, default=10)
    m.set_defaults(func=cmd_monitor)
    t = sub.add_parser("tree", help="pstree-like process tree")
    t.add_argument("--pid", type=int, help="root the tree at this PID (default: all roots)")
    t.add_argument("--depth", type=int, default=50)
    t.set_defaults(func=cmd_tree)
    for name, func, algos in (("schedule", cmd_schedule, list(ALIASES) + ["all"]),
                              ("real", cmd_real, ["fcfs", "fifo", "priority", "rr"])):
        s = sub.add_parser(name, help="simulate scheduling" if name == "schedule"
                           else "schedule REAL child processes with SIGSTOP/SIGCONT")
        s.add_argument("--algo", choices=algos, default="all" if name == "schedule" else "rr")
        s.add_argument("-q", "--quantum", type=float, default=2 if name == "schedule" else 0.5)
        s.add_argument("--jobs", help='e.g. "P1:0:5:3,P2:1:3:2,P3:2:1:1" (id:arrival:burst[:priority])')
        s.add_argument("--random", type=int, metavar="N", help="generate N random jobs")
        s.add_argument("--seed", type=int)
        if name == "real":
            s.add_argument("--scale", type=float, default=0.3, help="seconds per time unit (default 0.3)")
        s.set_defaults(func=func)
    args = p.parse_args(argv)
    try:
        args.func(args)
    except ValueError as e:
        print("Error:", e)
        raise SystemExit(2)
