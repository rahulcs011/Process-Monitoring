# scheduler.py
# CPU scheduling algorithms (simulation) + performance statistics.
#
# Algorithms: FCFS (FIFO), Priority (non-preemptive), Priority (preemptive),
# Round Robin. Each one returns a ScheduleResult which has the timeline
# (for the Gantt chart) and the stats for every job.
#
# Rules we follow:
#   - smaller priority number = more important (1 is higher than 3)
#   - ties are broken by arrival time, then by the order jobs were entered
#   - in Round Robin, a job that arrives during a time slice is put in the
#     queue BEFORE the job that just used up its quantum (textbook rule)

import heapq
import random
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional

FCFS = "FCFS (FIFO)"
PRIORITY_NP = "Priority (non-preemptive)"
PRIORITY_P = "Priority (preemptive)"
ROUND_ROBIN = "Round Robin"
ALGORITHMS = [FCFS, PRIORITY_NP, PRIORITY_P, ROUND_ROBIN]


@dataclass
class Job:
    job_id: str
    arrival: int
    burst: int
    priority: int = 0

    def __post_init__(self):
        if self.arrival < 0:
            raise ValueError(self.job_id + ": arrival time cannot be negative")
        if self.burst <= 0:
            raise ValueError(self.job_id + ": burst time must be more than 0")


@dataclass
class Slice:
    # one bar of the gantt chart, job_id = None means CPU was idle
    job_id: Optional[str]
    start: float
    end: float

    @property
    def length(self):
        return self.end - self.start


@dataclass
class JobStats:
    job_id: str
    arrival: float
    burst: float
    priority: int
    start: float       # first time the job got the CPU
    finish: float      # completion time
    turnaround: float  # finish - arrival
    waiting: float     # turnaround - burst
    response: float    # start - arrival


@dataclass
class ScheduleResult:
    algorithm: str
    timeline: List[Slice]
    jobs: List[JobStats]
    quantum: Optional[float] = None
    averages: dict = field(default_factory=dict)

    @property
    def total_time(self):
        if not self.timeline:
            return 0.0
        return self.timeline[-1].end - self.timeline[0].start

    @property
    def busy_time(self):
        return sum(s.length for s in self.timeline if s.job_id is not None)

    @property
    def context_switches(self):
        # count how many times the CPU moved from one job to a different job
        ids = [s.job_id for s in self.timeline if s.job_id is not None]
        count = 0
        for i in range(1, len(ids)):
            if ids[i] != ids[i - 1]:
                count += 1
        return count


class _Work:
    # keeps track of a job while it is being scheduled
    def __init__(self, job, order):
        self.job = job
        self.order = order          # position in the input list (for ties)
        self.remaining = job.burst
        self.start = None
        self.finish = None


def _prepare(jobs):
    if not jobs:
        raise ValueError("No jobs to schedule")
    ids = [j.job_id for j in jobs]
    if len(set(ids)) != len(ids):
        raise ValueError("Job IDs must be unique")
    return [_Work(j, i) for i, j in enumerate(jobs)]


def _add_slice(timeline, job_id, start, end):
    if end <= start:
        return
    last = timeline[-1] if timeline else None
    if last is not None and last.job_id == job_id and last.end == start:
        last.end = end   # same job continues, just extend the bar
    else:
        timeline.append(Slice(job_id, start, end))


def _finish(algorithm, works, timeline, quantum=None):
    stats = []
    for w in sorted(works, key=lambda w: w.order):
        j = w.job
        tat = w.finish - j.arrival
        stats.append(JobStats(j.job_id, j.arrival, j.burst, j.priority,
                              w.start, w.finish, tat, tat - j.burst, w.start - j.arrival))

    res = ScheduleResult(algorithm, timeline, stats, quantum)
    n = len(stats)
    total = res.total_time
    res.averages = {
        "avg_waiting": sum(s.waiting for s in stats) / n,
        "avg_turnaround": sum(s.turnaround for s in stats) / n,
        "avg_response": sum(s.response for s in stats) / n,
        "throughput": n / total if total else 0.0,
        "cpu_utilization": 100.0 * res.busy_time / total if total else 0.0,
        "makespan": total,
        "context_switches": res.context_switches,
    }
    return res


# ---------------------------------------------------------------- algorithms

def fcfs(jobs):
    """First Come First Served - run jobs fully in order of arrival."""
    works = _prepare(jobs)
    timeline = []
    t = 0
    for w in sorted(works, key=lambda w: (w.job.arrival, w.order)):
        if t < w.job.arrival:
            # nobody is ready yet, CPU sits idle
            _add_slice(timeline, None, t, w.job.arrival)
            t = w.job.arrival
        w.start = t
        t += w.job.burst
        w.finish = t
        w.remaining = 0
        _add_slice(timeline, w.job.job_id, w.start, t)
    return _finish(FCFS, works, timeline)


# Profiling showed the first version of the two priority functions was O(n^2):
# every step built a "ready" list and called min() over it. Now jobs are sorted
# by arrival once and the ready jobs live in a heap (priority queue), so getting
# the most important one is O(log n).

def _heap_key(w):
    return (w.job.priority, w.job.arrival, w.order)


def priority_non_preemptive(jobs):
    """Pick the most important job that has arrived, let it finish."""
    works = _prepare(jobs)
    incoming = deque(sorted(works, key=lambda w: (w.job.arrival, w.order)))
    heap = []
    timeline = []
    t = 0
    while incoming or heap:
        while incoming and incoming[0].job.arrival <= t:
            w = incoming.popleft()
            heapq.heappush(heap, (_heap_key(w), w))
        if not heap:
            nxt = incoming[0].job.arrival
            _add_slice(timeline, None, t, nxt)
            t = nxt
            continue
        _, w = heapq.heappop(heap)
        w.start = t
        t += w.job.burst
        w.finish = t
        w.remaining = 0
        _add_slice(timeline, w.job.job_id, w.start, t)
    return _finish(PRIORITY_NP, works, timeline)


def priority_preemptive(jobs):
    """Always run the most important job. Check again whenever a new job arrives."""
    works = _prepare(jobs)
    incoming = deque(sorted(works, key=lambda w: (w.job.arrival, w.order)))
    heap = []
    timeline = []
    t = 0
    while incoming or heap:
        while incoming and incoming[0].job.arrival <= t:
            w = incoming.popleft()
            heapq.heappush(heap, (_heap_key(w), w))
        if not heap:
            nxt = incoming[0].job.arrival
            _add_slice(timeline, None, t, nxt)
            t = nxt
            continue
        key, w = heap[0]
        if w.start is None:
            w.start = t
        # run until this job finishes or until the next arrival (it may preempt us)
        run = w.remaining
        if incoming:
            run = min(run, incoming[0].job.arrival - t)
        _add_slice(timeline, w.job.job_id, t, t + run)
        t += run
        w.remaining -= run
        if w.remaining <= 0:
            w.finish = t
            heapq.heappop(heap)
    return _finish(PRIORITY_P, works, timeline)


def round_robin(jobs, quantum=2):
    """Every ready job runs for at most `quantum` and then goes to the back of the queue."""
    if quantum <= 0:
        raise ValueError("Time quantum must be positive")
    works = _prepare(jobs)
    incoming = deque(sorted(works, key=lambda w: (w.job.arrival, w.order)))
    ready = deque()
    timeline = []
    t = 0

    def admit(now):
        while incoming and incoming[0].job.arrival <= now:
            ready.append(incoming.popleft())

    admit(t)
    while ready or incoming:
        if not ready:
            nxt = incoming[0].job.arrival
            _add_slice(timeline, None, t, nxt)
            t = nxt
            admit(t)
            continue
        w = ready.popleft()
        if w.start is None:
            w.start = t
        run = min(quantum, w.remaining)
        # add every quantum as its own bar so each turn is visible on the chart
        timeline.append(Slice(w.job.job_id, t, t + run))
        t += run
        w.remaining -= run
        admit(t)              # new arrivals go in first
        if w.remaining > 0:
            ready.append(w)   # then the preempted job
        else:
            w.finish = t
    return _finish(ROUND_ROBIN, works, timeline, quantum)


def run_algorithm(name, jobs, quantum=2):
    if name == FCFS:
        return fcfs(jobs)
    if name == PRIORITY_NP:
        return priority_non_preemptive(jobs)
    if name == PRIORITY_P:
        return priority_preemptive(jobs)
    if name == ROUND_ROBIN:
        return round_robin(jobs, quantum)
    raise ValueError("Unknown algorithm: " + str(name))


def compare_all(jobs, quantum=2):
    return [run_algorithm(a, jobs, quantum) for a in ALGORITHMS]


# ---------------------------------------------------------------- helpers

def example_jobs():
    # the example we solved by hand in class / in the README
    return [Job("P1", 0, 5, 3), Job("P2", 1, 3, 2), Job("P3", 2, 1, 1)]


def random_jobs(n=5, max_arrival=10, max_burst=8, max_priority=5, seed=None):
    rng = random.Random(seed)
    jobs = []
    for i in range(n):
        jobs.append(Job("P" + str(i + 1), rng.randint(0, max_arrival),
                        rng.randint(1, max_burst), rng.randint(1, max_priority)))
    return jobs


def parse_jobs(text):
    """Read jobs from a string like "P1:0:5:3,P2:1:3:2" (id:arrival:burst[:priority])."""
    jobs = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        f = part.split(":")
        if len(f) not in (3, 4):
            raise ValueError("Bad job '%s' (use id:arrival:burst[:priority])" % part)
        prio = int(f[3]) if len(f) == 4 else 0
        jobs.append(Job(f[0], int(f[1]), int(f[2]), prio))
    return jobs


def fmt_num(x):
    x = float(x)
    if x.is_integer():
        return str(int(x))
    return "%.2f" % x


def ascii_gantt(result):
    top = "|"
    bottom = ""
    for s in result.timeline:
        label = s.job_id or "idle"
        width = max(len(label) + 2, 4)
        top += label.center(width) + "|"
        bottom += fmt_num(s.start).ljust(width + 1)
    bottom += fmt_num(result.timeline[-1].end)
    return top + "\n" + bottom


def stats_table(result):
    header = "%-6s%5s%7s%6s%7s%8s%7s%7s%7s" % (
        "Job", "Arr", "Burst", "Prio", "Start", "Finish", "TAT", "Wait", "Resp")
    lines = [header, "-" * len(header)]
    for s in result.jobs:
        lines.append("%-6s%5s%7s%6s%7s%8s%7s%7s%7s" % (
            s.job_id, fmt_num(s.arrival), fmt_num(s.burst), s.priority, fmt_num(s.start),
            fmt_num(s.finish), fmt_num(s.turnaround), fmt_num(s.waiting), fmt_num(s.response)))
    a = result.averages
    lines.append("-" * len(header))
    lines.append("Avg waiting %.2f | Avg turnaround %.2f | Avg response %.2f"
                 % (a["avg_waiting"], a["avg_turnaround"], a["avg_response"]))
    lines.append("Throughput %.3f jobs/unit | CPU utilization %.1f%% | Context switches %d"
                 % (a["throughput"], a["cpu_utilization"], a["context_switches"]))
    return "\n".join(lines)
