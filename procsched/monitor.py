# monitor.py
# Process monitoring using psutil: snapshot of all processes, the unix
# process tree (built from PPID), system stats and a background thread
# that keeps refreshing the data.
import os
import pwd
import signal
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

import psutil

_ATTRS = ["pid", "ppid", "name", "uids", "status", "cpu_percent",
          "memory_percent", "memory_info", "num_threads", "create_time", "nice"]

# Profiling showed pwd.getpwuid() (uid -> user name) was ~25% of a snapshot,
# because psutil looks the name up again for every process every time.
# There are only a few different users, so we remember the answers.
_user_cache = {}


def _user_name(uids):
    if uids is None:
        return "?"
    uid = uids.real
    if uid not in _user_cache:
        try:
            _user_cache[uid] = pwd.getpwuid(uid).pw_name
        except KeyError:
            _user_cache[uid] = str(uid)
    return _user_cache[uid]


@dataclass
class ProcInfo:
    pid: int
    ppid: int
    name: str
    user: str
    status: str
    cpu: float          # % of one core (can exceed 100 for multi-threaded programs)
    mem: float          # % of total RAM
    rss_mb: float       # resident memory in MB
    threads: int
    nice: Optional[int]
    started: float      # epoch seconds


@dataclass
class SystemStats:
    timestamp: float
    cpu_total: float
    cpu_per_core: List[float]
    mem_percent: float
    mem_used_gb: float
    mem_total_gb: float
    swap_percent: float
    load_avg: Tuple[float, float, float]
    process_count: int
    thread_count: int
    status_counts: Dict[str, int]
    uptime_s: float


def snapshot() -> List[ProcInfo]:
    """Read every process the OS lets us see. Protected fields come back as None."""
    procs = []
    for p in psutil.process_iter(_ATTRS, ad_value=None):
        i = p.info
        mi = i.get("memory_info")
        procs.append(ProcInfo(
            pid=i["pid"],
            ppid=i.get("ppid") or 0,
            name=i.get("name") or "?",
            user=_user_name(i.get("uids")),
            status=i.get("status") or "?",
            cpu=i.get("cpu_percent") or 0.0,
            mem=i.get("memory_percent") or 0.0,
            rss_mb=(mi.rss / 1048576) if mi else 0.0,
            threads=i.get("num_threads") or 0,
            nice=i.get("nice"),
            started=i.get("create_time") or 0.0,
        ))
    return procs


def system_stats(procs: Optional[List[ProcInfo]] = None) -> SystemStats:
    vm = psutil.virtual_memory()
    try:
        load = os.getloadavg()
    except (AttributeError, OSError):
        load = (0.0, 0.0, 0.0)
    procs = procs if procs is not None else snapshot()
    counts: Dict[str, int] = {}
    for p in procs:
        counts[p.status] = counts.get(p.status, 0) + 1
    per_core = psutil.cpu_percent(percpu=True)
    return SystemStats(
        timestamp=time.time(),
        cpu_total=sum(per_core) / len(per_core) if per_core else 0.0,
        cpu_per_core=per_core,
        mem_percent=vm.percent,
        mem_used_gb=(vm.total - vm.available) / 1024 ** 3,
        mem_total_gb=vm.total / 1024 ** 3,
        swap_percent=psutil.swap_memory().percent,
        load_avg=tuple(load),
        process_count=len(procs),
        thread_count=sum(p.threads for p in procs),
        status_counts=counts,
        uptime_s=time.time() - psutil.boot_time(),
    )


# --------------------------------------------------------------------------- process tree
def build_tree(procs: List[ProcInfo]) -> Tuple[List[int], Dict[int, List[int]]]:
    """Return (roots, children) where children[pid] lists that process's child PIDs.

    A root is any process whose parent we cannot see (PID 0/1's parent, or a
    parent that already exited - i.e. an orphan that was re-parented)."""
    by_pid = {p.pid: p for p in procs}
    children: Dict[int, List[int]] = {}
    roots = []
    for p in sorted(procs, key=lambda p: p.pid):
        if p.ppid in by_pid and p.ppid != p.pid:
            children.setdefault(p.ppid, []).append(p.pid)
        else:
            roots.append(p.pid)
    return roots, children


def ancestors(pid: int, procs: List[ProcInfo]) -> List[int]:
    """Chain of PIDs from `pid` up to the root (pid first)."""
    by_pid = {p.pid: p for p in procs}
    chain, seen = [], set()
    while pid in by_pid and pid not in seen:
        chain.append(pid)
        seen.add(pid)
        pid = by_pid[pid].ppid
    return chain


def tree_text(procs: List[ProcInfo], root: Optional[int] = None, max_depth: int = 50) -> str:
    """pstree-like text rendering."""
    by_pid = {p.pid: p for p in procs}
    roots, children = build_tree(procs)
    lines: List[str] = []

    def walk(pid: int, prefix: str, last: bool, depth: int) -> None:
        p = by_pid[pid]
        branch = "" if depth == 0 else ("└── " if last else "├── ")
        lines.append(f"{prefix}{branch}{p.name} ({p.pid})")
        if depth >= max_depth:
            return
        kids = children.get(pid, [])
        ext = "" if depth == 0 else ("    " if last else "│   ")
        for k, c in enumerate(kids):
            walk(c, prefix + ext, k == len(kids) - 1, depth + 1)

    for r in ([root] if root is not None else roots):
        if r in by_pid:
            walk(r, "", True, 0)
    return "\n".join(lines)


# --------------------------------------------------------------------------- control
_SIGNALS = {
    "terminate": signal.SIGTERM,
    "kill": signal.SIGKILL,
    "suspend": signal.SIGSTOP,
    "resume": signal.SIGCONT,
}


def send_signal(pid: int, action: str) -> None:
    """Send SIGTERM / SIGKILL / SIGSTOP / SIGCONT to a process."""
    if pid in (0, 1, os.getpid()):
        raise PermissionError("Refusing to signal PID 0, PID 1 or this application itself")
    psutil.Process(pid).send_signal(_SIGNALS[action])


# --------------------------------------------------------------------------- background thread
class MonitorThread(threading.Thread):
    """Samples the system every `interval` seconds in the background.

    The GUI thread never touches psutil directly; it reads the latest sample
    through `latest()` which is protected by a lock (no race conditions)."""

    def __init__(self, interval: float = 1.5, history: int = 120) -> None:
        super().__init__(name="MonitorThread", daemon=True)
        self.interval = interval
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._procs: List[ProcInfo] = []
        self._stats: Optional[SystemStats] = None
        self.history: Deque[Tuple[float, float, float]] = deque(maxlen=history)
        self.samples = 0
        self.error: Optional[str] = None
        psutil.cpu_percent(percpu=True)  # prime the CPU counters

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                procs = snapshot()
                stats = system_stats(procs)
                with self._lock:
                    self._procs, self._stats = procs, stats
                    if self.samples > 0:  # first CPU reading is a warm-up value
                        self.history.append((stats.timestamp, stats.cpu_total, stats.mem_percent))
                    self.samples += 1
                    self.error = None
            except Exception as exc:  # keep the thread alive no matter what
                with self._lock:
                    self.error = str(exc)
            self._stop_event.wait(self.interval)

    def latest(self):
        with self._lock:
            return list(self._procs), self._stats, list(self.history)

    def stop(self) -> None:
        self._stop_event.set()
