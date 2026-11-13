# executor.py
# "Real" scheduler: every job is an actual child process (fork + exec via
# subprocess) that burns some CPU seconds. A separate thread decides which
# child may run and pauses / resumes them with SIGSTOP and SIGCONT.
# FCFS and Priority run a job till it exits, Round Robin stops it after the
# quantum. You can see these children under our app in the Process Tree tab.
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .scheduler import FCFS, PRIORITY_NP, ROUND_ROBIN, Job, ScheduleResult, Slice, _finish, _Work

REAL_ALGORITHMS = [FCFS, PRIORITY_NP, ROUND_ROBIN]

# Child program: spin until it has used `burst` seconds of *its own* CPU time.
# Because it measures CPU time (not wall time), pausing it with SIGSTOP
# really delays its completion - exactly like a real CPU-bound job.
_WORKER = (
    "import sys, time\n"
    "need = float(sys.argv[1]); s = time.process_time()\n"
    "while time.process_time() - s < need:\n"
    "    pass\n"
)

WAITING, RUNNING, STOPPED, DONE, KILLED = "waiting", "running", "stopped (SIGSTOP)", "done", "killed"


@dataclass
class RealJob:
    job: Job
    state: str = WAITING
    proc: Optional[subprocess.Popen] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    cpu_given: float = 0.0          # wall-clock seconds it held "the CPU"
    slices: List[Slice] = field(default_factory=list)

    @property
    def pid(self) -> Optional[int]:
        return self.proc.pid if self.proc else None


class RealScheduler(threading.Thread):
    """Runs on its own thread so the GUI stays responsive."""

    def __init__(self, jobs: List[Job], algorithm: str, quantum: float = 1.0,
                 on_event: Optional[Callable[[str], None]] = None) -> None:
        super().__init__(name="RealScheduler", daemon=True)
        if algorithm not in REAL_ALGORITHMS:
            raise ValueError(f"Real mode supports: {', '.join(REAL_ALGORITHMS)}")
        if quantum <= 0:
            raise ValueError("Quantum must be positive")
        self.algorithm = algorithm
        self.quantum = quantum
        self.jobs = [RealJob(j) for j in jobs]
        self.lock = threading.Lock()
        self._stop_event = threading.Event()
        self._on_event = on_event or (lambda msg: None)
        self.t0 = 0.0
        self.timeline: List[Slice] = []
        self.result: Optional[ScheduleResult] = None
        self.finished = False

    # ----------------------------------------------------------------- helpers
    def now(self) -> float:
        return time.monotonic() - self.t0

    def log(self, msg: str) -> None:
        self._on_event(f"[t={self.now():6.2f}s] {msg}")

    def _launch(self, rj: RealJob) -> None:
        rj.proc = subprocess.Popen([sys.executable, "-c", _WORKER, str(rj.job.burst)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        rj.started_at = self.now()
        self.log(f"fork/exec {rj.job.job_id} -> PID {rj.pid} (parent PID {os.getpid()})")

    def _signal(self, rj: RealJob, sig: int) -> None:
        try:
            os.kill(rj.pid, sig)
        except ProcessLookupError:
            pass

    def _pick(self, ready: deque) -> RealJob:
        if self.algorithm == PRIORITY_NP:
            best = min(ready, key=lambda r: (r.job.priority, r.job.arrival, self.jobs.index(r)))
            ready.remove(best)
            return best
        return ready.popleft()  # FIFO order for FCFS and Round Robin

    # ----------------------------------------------------------------- main loop
    def run(self) -> None:
        self.t0 = time.monotonic()
        incoming = deque(sorted(self.jobs, key=lambda r: (r.job.arrival, self.jobs.index(r))))
        ready: deque = deque()
        mode = f"{self.algorithm}" + (f", quantum={self.quantum}s" if self.algorithm == ROUND_ROBIN else "")
        self.log(f"scheduler started ({mode})")

        def admit() -> None:
            while incoming and incoming[0].job.arrival <= self.now():
                rj = incoming.popleft()
                ready.append(rj)
                self.log(f"{rj.job.job_id} arrived (burst={rj.job.burst}s, priority={rj.job.priority})")

        try:
            while not self._stop_event.is_set() and (incoming or ready):
                admit()
                if not ready:
                    self._stop_event.wait(0.02)
                    continue
                with self.lock:
                    rj = self._pick(ready)
                    if rj.proc is None:
                        self._launch(rj)
                    else:
                        self._signal(rj, signal.SIGCONT)
                        self.log(f"SIGCONT -> {rj.job.job_id} (PID {rj.pid}) resumed")
                    rj.state = RUNNING
                    start = self.now()
                    rj.slices.append(Slice(rj.job.job_id, start, start))
                    self.timeline.append(rj.slices[-1])
                    # pause every other launched job so only one "owns the CPU"
                    for other in self.jobs:
                        if other is not rj and other.proc and other.state not in (DONE, KILLED):
                            self._signal(other, signal.SIGSTOP)
                limit = self.quantum if self.algorithm == ROUND_ROBIN else float("inf")
                while not self._stop_event.is_set():
                    with self.lock:
                        rj.slices[-1].end = self.now()
                    if rj.proc.poll() is not None:
                        break
                    if self.now() - start >= limit:
                        break
                    admit()
                    self._stop_event.wait(0.02)
                with self.lock:
                    rj.slices[-1].end = self.now()
                    rj.cpu_given += rj.slices[-1].length
                    if rj.proc.poll() is not None:
                        rj.state = DONE
                        rj.finished_at = self.now()
                        self.log(f"{rj.job.job_id} (PID {rj.pid}) exited, code {rj.proc.returncode}")
                    elif self._stop_event.is_set():
                        break
                    else:
                        self._signal(rj, signal.SIGSTOP)
                        rj.state = STOPPED
                        self.log(f"quantum expired: SIGSTOP -> {rj.job.job_id} (PID {rj.pid})")
                        admit()
                        ready.append(rj)
        finally:
            self._cleanup()
            if all(r.state == DONE for r in self.jobs):
                self.result = self._build_result()
                self.log("all jobs finished")
            else:
                self.log("scheduler stopped by user")
            self.finished = True

    def _cleanup(self) -> None:
        for rj in self.jobs:
            if rj.proc and rj.proc.poll() is None:
                self._signal(rj, signal.SIGCONT)
                rj.proc.kill()
                rj.proc.wait()
                rj.state = KILLED
                self.log(f"killed {rj.job.job_id} (PID {rj.pid})")

    def _build_result(self) -> ScheduleResult:
        works = []
        timeline: List[Slice] = []
        for s in sorted(self.timeline, key=lambda s: s.start):
            if timeline and s.start > timeline[-1].end + 0.05:
                timeline.append(Slice(None, timeline[-1].end, s.start))
            timeline.append(Slice(s.job_id, s.start, s.end))
        if timeline and timeline[0].start > 0.05:
            timeline.insert(0, Slice(None, 0.0, timeline[0].start))
        for i, rj in enumerate(self.jobs):
            w = _Work(rj.job, i)
            w.start = rj.slices[0].start
            w.finish = rj.finished_at
            works.append(w)
        res = _finish(self.algorithm + " (real processes)", works, timeline,
                      self.quantum if self.algorithm == ROUND_ROBIN else None)
        # In real mode, "burst" is the CPU time requested; measured run time is in cpu_given.
        return res

    def stop(self) -> None:
        self._stop_event.set()

    def status_rows(self):
        with self.lock:
            return [(rj.job.job_id, rj.pid or "-", rj.state, rj.job.priority, rj.job.burst,
                     round(rj.cpu_given + (rj.slices[-1].length if rj.state == RUNNING and rj.slices else 0), 2))
                    for rj in self.jobs]

    def timeline_copy(self) -> List[Slice]:
        with self.lock:
            return [Slice(s.job_id, s.start, s.end) for s in self.timeline]
