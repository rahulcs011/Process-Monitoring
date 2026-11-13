# gui.py
# Tkinter GUI with 5 tabs: processes, process tree, system graphs,
# scheduling simulator and the real process scheduler.
#
# Threads: Tk is not thread safe, so only the main thread touches widgets.
# MonitorThread and RealScheduler run in the background and give data to
# the GUI through a lock / queue.Queue. The GUI checks them with after().
import csv
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from . import monitor as mon  # noqa: E402
from .executor import REAL_ALGORITHMS, RealScheduler  # noqa: E402
from .scheduler import (ALGORITHMS, ROUND_ROBIN, Job, ScheduleResult, Slice,  # noqa: E402
                        compare_all, example_jobs, fmt_num, random_jobs, run_algorithm)

PALETTE = ["#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#B279A2",
           "#FF9DA6", "#9D755D", "#EECA3B", "#BAB0AC"]
IDLE_COLOR = "#D9D9D9"


def job_colors(ids: List[str]) -> Dict[str, str]:
    return {j: PALETTE[i % len(PALETTE)] for i, j in enumerate(ids)}


def draw_gantt(ax, timeline: List[Slice], job_ids: List[str], title: str,
               end: Optional[float] = None) -> None:
    """One row per job plus an 'idle' row; each bar is one CPU slice."""
    ax.clear()
    colors = job_colors(job_ids)
    rows = list(job_ids) + ["idle"]
    ypos = {j: len(rows) - 1 - i for i, j in enumerate(rows)}
    for s in timeline:
        key = s.job_id if s.job_id is not None else "idle"
        if key not in ypos:
            continue
        color = colors.get(s.job_id, IDLE_COLOR)
        ax.barh(ypos[key], s.length, left=s.start, height=0.6, color=color,
                edgecolor="white", linewidth=1)
        if s.length > 0 and s.job_id is not None:
            ax.text(s.start + s.length / 2, ypos[key], s.job_id, ha="center", va="center",
                    fontsize=8, color="white", fontweight="bold", clip_on=True)
    ax.set_yticks([ypos[r] for r in rows])
    ax.set_yticklabels(rows)
    ax.set_xlabel("time")
    ax.set_title(title, fontsize=10)
    xmax = end if end is not None else (timeline[-1].end if timeline else 1)
    ax.set_xlim(0, max(xmax, 1e-6) * 1.02)
    ax.grid(axis="x", alpha=0.3)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def make_tree(parent, columns, widths, height=15, show="headings", anchor_left=()):
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=columns, show=show, height=height)
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)
    for c, w in zip(columns, widths):
        tree.heading(c, text=c)
        tree.column(c, width=w, anchor="w" if c in anchor_left else "e", stretch=c in anchor_left)
    tree.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")
    return frame, tree


# =========================================================================== Processes tab
class ProcessesTab(ttk.Frame):
    COLS = ("PID", "PPID", "Name", "User", "Status", "CPU %", "Mem %", "RSS MB", "Threads", "Nice")
    KEYS = {"PID": "pid", "PPID": "ppid", "Name": "name", "User": "user", "Status": "status",
            "CPU %": "cpu", "Mem %": "mem", "RSS MB": "rss_mb", "Threads": "threads", "Nice": "nice"}

    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.sort_col, self.sort_rev = "CPU %", True
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="Search:").pack(side="left")
        self.search = tk.StringVar()
        ent = ttk.Entry(bar, textvariable=self.search, width=22)
        ent.pack(side="left", padx=4)
        ent.bind("<KeyRelease>", lambda e: self.refresh(force=True))
        self.mine = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Only my processes", variable=self.mine,
                        command=lambda: self.refresh(force=True)).pack(side="left", padx=6)
        self.paused = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Pause updates", variable=self.paused).pack(side="left", padx=6)
        for label, action in (("Terminate", "terminate"), ("Kill", "kill"),
                              ("Suspend", "suspend"), ("Resume", "resume")):
            ttk.Button(bar, text=label, command=lambda a=action: self.signal(a)).pack(side="right", padx=2)
        ttk.Button(bar, text="Show in tree", command=self.show_in_tree).pack(side="right", padx=8)

        frame, self.tree = make_tree(self, self.COLS, (70, 70, 220, 110, 80, 70, 70, 80, 70, 50),
                                     height=25, anchor_left=("Name", "User", "Status"))
        frame.pack(fill="both", expand=True)
        for c in self.COLS:
            self.tree.heading(c, text=c, command=lambda c=c: self.sort_by(c))
        self.summary = ttk.Label(self, text="Waiting for first sample...")
        self.summary.pack(fill="x", pady=(6, 0))
        self._procs: List[mon.ProcInfo] = []

    def sort_by(self, col):
        self.sort_rev = (not self.sort_rev) if self.sort_col == col else col in ("CPU %", "Mem %", "RSS MB", "Threads")
        self.sort_col = col
        self.refresh(force=True)

    def update_data(self, procs):
        if not self.paused.get():
            self._procs = procs
            self.refresh()

    def refresh(self, force=False):
        procs = self._procs
        q = self.search.get().strip().lower()
        if q:
            procs = [p for p in procs if q in p.name.lower() or q == str(p.pid)]
        if self.mine.get():
            me = self.app.username
            procs = [p for p in procs if p.user == me]
        key = self.KEYS[self.sort_col]
        procs = sorted(procs, key=lambda p: (getattr(p, key) is None, getattr(p, key) or 0)
                       if key not in ("name", "user", "status") else str(getattr(p, key)).lower(),
                       reverse=self.sort_rev)
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for p in procs:
            self.tree.insert("", "end", iid=str(p.pid), values=(
                p.pid, p.ppid, p.name, p.user, p.status, f"{p.cpu:.1f}", f"{p.mem:.2f}",
                f"{p.rss_mb:.1f}", p.threads, "" if p.nice is None else p.nice))
        keep = [s for s in sel if self.tree.exists(s)]
        if keep:
            self.tree.selection_set(keep)
        arrow = "(desc)" if self.sort_rev else "(asc)"
        for c in self.COLS:
            self.tree.heading(c, text=c + (f" {arrow}" if c == self.sort_col else ""))
        top = max(self._procs, key=lambda p: p.cpu, default=None)
        self.summary.config(text=f"Showing {len(procs)} of {len(self._procs)} processes"
                                 + (f"   |   Top CPU: {top.name} (PID {top.pid}) {top.cpu:.1f}%" if top else "")
                                 + "   |   Click a column heading to sort")

    def selected_pid(self) -> Optional[int]:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No process selected", "Select a process in the table first.")
            return None
        return int(sel[0])

    def signal(self, action):
        pid = self.selected_pid()
        if pid is None:
            return
        name = self.tree.set(str(pid), "Name")
        if not messagebox.askyesno("Confirm", f"Send {action.upper()} to {name} (PID {pid})?"):
            return
        try:
            mon.send_signal(pid, action)
            self.app.set_status(f"Sent {action} to PID {pid}")
        except Exception as exc:
            messagebox.showerror("Could not signal process", f"{type(exc).__name__}: {exc}")

    def show_in_tree(self):
        pid = self.selected_pid()
        if pid is not None:
            self.app.tree_tab.focus_pid(pid)


# =========================================================================== Process tree tab
class TreeTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Refresh", command=self.rebuild).pack(side="left")
        ttk.Button(bar, text="Expand all", command=lambda: self.set_open(True)).pack(side="left", padx=4)
        ttk.Button(bar, text="Collapse all", command=lambda: self.set_open(False)).pack(side="left")
        ttk.Button(bar, text="Find this app", command=lambda: self.focus_pid(os.getpid())).pack(side="left", padx=12)
        ttk.Label(bar, text="Find PID/name:").pack(side="left")
        self.find_var = tk.StringVar()
        ent = ttk.Entry(bar, textvariable=self.find_var, width=18)
        ent.pack(side="left", padx=4)
        ent.bind("<Return>", lambda e: self.find())
        ttk.Button(bar, text="Find", command=self.find).pack(side="left")

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        cols = ("PID", "PPID", "User", "Status", "CPU %", "Mem %", "Children")
        self.tree = ttk.Treeview(frame, columns=cols, show="tree headings")
        self.tree.heading("#0", text="Process (parent -> children)")
        self.tree.column("#0", width=380, stretch=True)
        for c, w in zip(cols, (70, 70, 110, 80, 70, 70, 70)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="e" if c not in ("User", "Status") else "w", stretch=False)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("me", background="#FFF3C4")
        self.info = ttk.Label(self, text="")
        self.info.pack(fill="x", pady=(6, 0))
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self._procs: List[mon.ProcInfo] = []
        self.built = False

    def rebuild(self):
        procs, _, _ = self.app.monitor.latest()
        if not procs:
            procs = mon.snapshot()
        self._procs = procs
        by_pid = {p.pid: p for p in procs}
        roots, children = mon.build_tree(procs)
        mine = set(mon.ancestors(os.getpid(), procs))
        self.tree.delete(*self.tree.get_children())
        stack = [("", r, 0) for r in reversed(roots)]
        while stack:  # iterative depth-first walk (no recursion limit issues)
            parent, pid, depth = stack.pop()
            p = by_pid[pid]
            kids = children.get(pid, [])
            self.tree.insert(parent, "end", iid=str(pid), text=f"{p.name}",
                             open=depth < 1, tags=("me",) if pid in mine else (),
                             values=(p.pid, p.ppid, p.user, p.status, f"{p.cpu:.1f}", f"{p.mem:.2f}", len(kids)))
            for c in reversed(kids):
                stack.append((str(pid), c, depth + 1))
        self.built = True
        self.info.config(text=f"{len(procs)} processes, {len(roots)} root(s). Highlighted rows = the "
                              f"chain from this app (PID {os.getpid()}) up to the root process.")

    def set_open(self, state, item=""):
        for child in self.tree.get_children(item):
            self.tree.item(child, open=state)
            self.set_open(state, child)

    def focus_pid(self, pid: int):
        self.app.notebook.select(self)
        if not self.built or not self.tree.exists(str(pid)):
            self.rebuild()
        if not self.tree.exists(str(pid)):
            messagebox.showinfo("Not found", f"PID {pid} is not running any more.")
            return
        node = self.tree.parent(str(pid))
        while node:
            self.tree.item(node, open=True)
            node = self.tree.parent(node)
        self.tree.selection_set(str(pid))
        self.tree.see(str(pid))

    def find(self):
        q = self.find_var.get().strip().lower()
        if not q:
            return
        if not self.built:
            self.rebuild()
        for p in self._procs:
            if q == str(p.pid) or q in p.name.lower():
                self.focus_pid(p.pid)
                return
        messagebox.showinfo("Not found", f"No process matching '{q}'.")

    def on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        chain = mon.ancestors(int(sel[0]), self._procs)
        by_pid = {p.pid: p for p in self._procs}
        self.info.config(text="Ancestry: " + "  <-  ".join(f"{by_pid[c].name}({c})" for c in chain))


# =========================================================================== System tab
class SystemTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        cards = ttk.Frame(self)
        cards.pack(fill="x")
        self.labels = {}
        for i, name in enumerate(("CPU", "Memory", "Swap", "Load avg (1/5/15m)",
                                  "Processes", "Threads", "Cores", "Uptime")):
            box = ttk.LabelFrame(cards, text=name, padding=6)
            box.grid(row=0, column=i, sticky="nsew", padx=3)
            cards.columnconfigure(i, weight=1)
            lbl = ttk.Label(box, text="-", font=("Helvetica", 14, "bold"))
            lbl.pack()
            self.labels[name] = lbl
        self.states = ttk.Label(self, text="")
        self.states.pack(fill="x", pady=4)
        self.fig = Figure(figsize=(10, 6), dpi=90)
        self.ax_cpu = self.fig.add_subplot(2, 2, 1)
        self.ax_mem = self.fig.add_subplot(2, 2, 2)
        self.ax_core = self.fig.add_subplot(2, 1, 2)
        self.fig.tight_layout(pad=2.5)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def update_data(self, stats: Optional[mon.SystemStats], history):
        if stats is None:
            return
        L = self.labels
        L["CPU"].config(text=f"{stats.cpu_total:.1f}%")
        L["Memory"].config(text=f"{stats.mem_percent:.1f}%  ({stats.mem_used_gb:.1f}/{stats.mem_total_gb:.1f} GB)")
        L["Swap"].config(text=f"{stats.swap_percent:.1f}%")
        L["Load avg (1/5/15m)"].config(text=" / ".join(f"{x:.2f}" for x in stats.load_avg))
        L["Processes"].config(text=str(stats.process_count))
        L["Threads"].config(text=str(stats.thread_count))
        L["Cores"].config(text=str(len(stats.cpu_per_core)))
        h, rem = divmod(int(stats.uptime_s), 3600)
        L["Uptime"].config(text=f"{h // 24}d {h % 24}h {rem // 60}m")
        self.states.config(text="Process states: " + ",  ".join(
            f"{k}: {v}" for k, v in sorted(stats.status_counts.items(), key=lambda kv: -kv[1])))

        t0 = history[-1][0] if history else time.time()
        xs = [t - t0 for t, _, _ in history]
        for ax, ys, title, color in ((self.ax_cpu, [c for _, c, _ in history], "Total CPU usage (%)", PALETTE[0]),
                                     (self.ax_mem, [m for _, _, m in history], "Memory usage (%)", PALETTE[1])):
            ax.clear()
            ax.plot(xs, ys, color=color, linewidth=2)
            ax.fill_between(xs, ys, alpha=0.15, color=color)
            ax.set_ylim(0, 100)
            ax.set_xlim(min(xs + [-60]), 0)
            ax.set_title(title, fontsize=10)
            ax.set_xlabel("seconds ago")
            ax.grid(alpha=0.3)
        ax = self.ax_core
        ax.clear()
        cores = stats.cpu_per_core
        ax.bar(range(len(cores)), cores, color=[PALETTE[3] if c > 80 else PALETTE[2] for c in cores])
        ax.set_ylim(0, 100)
        ax.set_xticks(range(len(cores)))
        ax.set_xticklabels([f"core {i}" for i in range(len(cores))], fontsize=8)
        ax.set_title("Per-core CPU usage (%)  - red = above 80%", fontsize=10)
        ax.grid(axis="y", alpha=0.3)
        self.fig.tight_layout(pad=2.0)
        self.canvas.draw_idle()


# =========================================================================== Scheduler simulation tab
class SchedulerTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.result: Optional[ScheduleResult] = None
        self._anim = None
        left = ttk.Frame(self, width=380)
        left.pack(side="left", fill="y", padx=(0, 8))
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True)

        add = ttk.LabelFrame(left, text="Add job", padding=6)
        add.pack(fill="x")
        self.vars = {}
        for i, (name, default) in enumerate((("ID", "P1"), ("Arrival", "0"), ("Burst", "5"), ("Priority", "1"))):
            ttk.Label(add, text=name).grid(row=0, column=i, sticky="w")
            v = tk.StringVar(value=default)
            ttk.Entry(add, textvariable=v, width=7).grid(row=1, column=i, padx=2)
            self.vars[name] = v
        ttk.Button(add, text="Add", command=self.add_job).grid(row=1, column=4, padx=4)

        frame, self.jobs_tree = make_tree(left, ("ID", "Arrival", "Burst", "Priority"), (70, 70, 70, 70),
                                          height=10, anchor_left=("ID",))
        frame.pack(fill="x", pady=6)
        btns = ttk.Frame(left)
        btns.pack(fill="x")
        ttk.Button(btns, text="Remove", command=self.remove_job).pack(side="left")
        ttk.Button(btns, text="Clear", command=lambda: self.set_jobs([])).pack(side="left", padx=2)
        ttk.Button(btns, text="Example", command=lambda: self.set_jobs(example_jobs())).pack(side="left", padx=2)
        ttk.Button(btns, text="Random", command=lambda: self.set_jobs(random_jobs(6))).pack(side="left", padx=2)

        opts = ttk.LabelFrame(left, text="Algorithm", padding=6)
        opts.pack(fill="x", pady=8)
        self.algo = tk.StringVar(value=ROUND_ROBIN)
        for a in ALGORITHMS:
            ttk.Radiobutton(opts, text=a, value=a, variable=self.algo).pack(anchor="w")
        q = ttk.Frame(opts)
        q.pack(fill="x", pady=(4, 0))
        ttk.Label(q, text="Time quantum (RR):").pack(side="left")
        self.quantum = tk.StringVar(value="2")
        ttk.Spinbox(q, from_=1, to=20, textvariable=self.quantum, width=5).pack(side="left", padx=4)
        self.animate = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Animate Gantt chart", variable=self.animate).pack(anchor="w", pady=(4, 0))

        run = ttk.Frame(left)
        run.pack(fill="x")
        ttk.Button(run, text="Run", command=self.run).pack(side="left", fill="x", expand=True)
        ttk.Button(run, text="Compare all", command=self.compare).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(left, text="Export results (CSV)", command=self.export).pack(fill="x", pady=4)
        ttk.Label(left, text="Lower priority number = more important.\n"
                             "TAT = finish - arrival\nWaiting = TAT - burst\n"
                             "Response = first run - arrival", foreground="#555", justify="left").pack(anchor="w", pady=6)

        self.fig = Figure(figsize=(8, 3.6), dpi=90)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        cols = ("Job", "Arrival", "Burst", "Priority", "Start", "Finish", "Turnaround", "Waiting", "Response")
        frame, self.res_tree = make_tree(right, cols, (60, 70, 60, 70, 60, 70, 90, 70, 80), height=7,
                                         anchor_left=("Job",))
        frame.pack(fill="x", pady=(6, 0))
        self.avg = ttk.Label(right, text="Add jobs and press Run.", font=("Helvetica", 12, "bold"), justify="left")
        self.avg.pack(fill="x", pady=6)
        self.set_jobs(example_jobs())

    # ---------------------------------------------------------------- job list
    def set_jobs(self, jobs: List[Job]):
        self.jobs_tree.delete(*self.jobs_tree.get_children())
        for j in jobs:
            self.jobs_tree.insert("", "end", values=(j.job_id, j.arrival, j.burst, j.priority))
        self.vars["ID"].set(f"P{len(jobs) + 1}")

    def get_jobs(self) -> List[Job]:
        return [Job(str(v[0]), int(v[1]), int(v[2]), int(v[3]))
                for v in (self.jobs_tree.item(i, "values") for i in self.jobs_tree.get_children())]

    def add_job(self):
        try:
            job = Job(self.vars["ID"].get().strip() or "P?", int(self.vars["Arrival"].get()),
                      int(self.vars["Burst"].get()), int(self.vars["Priority"].get()))
        except ValueError as exc:
            messagebox.showerror("Invalid job", f"Use whole numbers; burst > 0, arrival >= 0.\n\n{exc}")
            return
        if any(j.job_id == job.job_id for j in self.get_jobs()):
            messagebox.showerror("Invalid job", f"Job ID {job.job_id} already exists.")
            return
        self.set_jobs(self.get_jobs() + [job])

    def remove_job(self):
        for i in self.jobs_tree.selection():
            self.jobs_tree.delete(i)

    # ---------------------------------------------------------------- run
    def _quantum(self) -> int:
        q = int(self.quantum.get())
        if q <= 0:
            raise ValueError("Quantum must be positive")
        return q

    def run(self):
        try:
            jobs = self.get_jobs()
            self.result = run_algorithm(self.algo.get(), jobs, self._quantum())
        except ValueError as exc:
            messagebox.showerror("Cannot schedule", str(exc))
            return
        if self._anim:
            self.after_cancel(self._anim)
            self._anim = None
        self.show_table(self.result)
        if self.animate.get():
            self._animate(0)
        else:
            self._draw(self.result.timeline)

    def _title(self) -> str:
        r = self.result
        return f"Gantt chart - {r.algorithm}" + (f" (quantum={fmt_num(r.quantum)})" if r.quantum else "")

    def _draw(self, timeline):
        ids = [j.job_id for j in self.result.jobs]
        draw_gantt(self.ax, timeline, ids, self._title(), end=self.result.timeline[-1].end)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _animate(self, k):
        self._draw(self.result.timeline[:k])
        if k < len(self.result.timeline):
            self._anim = self.after(350, self._animate, k + 1)
        else:
            self._anim = None

    def show_table(self, r: ScheduleResult):
        self.res_tree.delete(*self.res_tree.get_children())
        for s in r.jobs:
            self.res_tree.insert("", "end", values=(s.job_id, fmt_num(s.arrival), fmt_num(s.burst), s.priority,
                                                    fmt_num(s.start), fmt_num(s.finish), fmt_num(s.turnaround),
                                                    fmt_num(s.waiting), fmt_num(s.response)))
        a = r.averages
        self.avg.config(text=f"Avg waiting: {a['avg_waiting']:.2f}    Avg turnaround: {a['avg_turnaround']:.2f}    "
                             f"Avg response: {a['avg_response']:.2f}\n"
                             f"Throughput: {a['throughput']:.3f} jobs/unit    CPU utilization: "
                             f"{a['cpu_utilization']:.1f}%    Context switches: {a['context_switches']}    "
                             f"Makespan: {fmt_num(a['makespan'])}")

    def compare(self):
        try:
            results = compare_all(self.get_jobs(), self._quantum())
        except ValueError as exc:
            messagebox.showerror("Cannot schedule", str(exc))
            return
        CompareWindow(self, results)

    def export(self):
        if not self.result:
            messagebox.showinfo("Nothing to export", "Run a schedule first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="schedule_results.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        r = self.result
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["algorithm", r.algorithm, "quantum", r.quantum or ""])
            w.writerow(["job", "arrival", "burst", "priority", "start", "finish", "turnaround", "waiting", "response"])
            for s in r.jobs:
                w.writerow([s.job_id, s.arrival, s.burst, s.priority, s.start, s.finish,
                            s.turnaround, s.waiting, s.response])
            w.writerow([])
            for k, v in r.averages.items():
                w.writerow([k, round(v, 4)])
            w.writerow([])
            w.writerow(["slice_job", "start", "end"])
            for s in r.timeline:
                w.writerow([s.job_id or "idle", s.start, s.end])
        self.app.set_status(f"Saved {path}")


class CompareWindow(tk.Toplevel):
    def __init__(self, master, results: List[ScheduleResult]):
        super().__init__(master)
        self.title("Algorithm comparison")
        self.geometry("1100x760")
        fig = Figure(figsize=(11, 7.5), dpi=90)
        n = len(results)
        ax = fig.add_subplot(2, 1, 1)
        metrics = [("avg_waiting", "Avg waiting"), ("avg_turnaround", "Avg turnaround"), ("avg_response", "Avg response")]
        width = 0.8 / n
        for i, r in enumerate(results):
            vals = [r.averages[m] for m, _ in metrics]
            xs = [k + (i - (n - 1) / 2) * width for k in range(len(metrics))]
            bars = ax.bar(xs, vals, width, label=r.algorithm, color=PALETTE[i])
            for b, v in zip(bars, vals):
                ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}", ha="center", va="bottom", fontsize=8)
        ax.set_xticks(range(len(metrics)))
        ax.set_xticklabels([label for _, label in metrics])
        ax.set_ylabel("time units (lower is better)")
        q = next((r.quantum for r in results if r.quantum), None)
        ax.set_title(f"Scheduling algorithms on the same jobs (RR quantum = {fmt_num(q)})")
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.3)
        ids = [j.job_id for j in results[0].jobs]
        end = max(r.timeline[-1].end for r in results)
        for i, r in enumerate(results):
            sub = fig.add_subplot(2, n, n + i + 1)
            draw_gantt(sub, r.timeline, ids, r.algorithm, end=end)
            sub.tick_params(labelsize=7)
        fig.tight_layout()
        FigureCanvasTkAgg(fig, master=self).get_tk_widget().pack(fill="both", expand=True)
        best = min(results, key=lambda r: r.averages["avg_waiting"])
        fastest = min(results, key=lambda r: r.averages["avg_response"])
        ttk.Label(self, padding=6, font=("Helvetica", 12, "bold"),
                  text=f"Lowest avg waiting: {best.algorithm}    |    Fastest avg response: {fastest.algorithm}").pack()


# =========================================================================== Real process tab
class RealTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.sched: Optional[RealScheduler] = None
        self.events: "queue.Queue[str]" = queue.Queue()
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(0, 8))
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True)

        ttk.Label(left, text="Each job is a REAL child process that needs\nN seconds of CPU. The scheduler thread\n"
                             "pauses/resumes them with SIGSTOP/SIGCONT.", foreground="#555",
                  justify="left").pack(anchor="w")
        add = ttk.LabelFrame(left, text="Add job", padding=6)
        add.pack(fill="x", pady=6)
        self.vars = {}
        for i, (name, default) in enumerate((("ID", "D"), ("CPU sec", "1.5"), ("Priority", "2"), ("Arrival s", "0"))):
            ttk.Label(add, text=name).grid(row=0, column=i, sticky="w")
            v = tk.StringVar(value=default)
            ttk.Entry(add, textvariable=v, width=7).grid(row=1, column=i, padx=2)
            self.vars[name] = v
        ttk.Button(add, text="Add", command=self.add_job).grid(row=1, column=4, padx=4)
        frame, self.jobs_tree = make_tree(left, ("ID", "CPU sec", "Priority", "Arrival s"), (60, 70, 70, 70),
                                          height=7, anchor_left=("ID",))
        frame.pack(fill="x")
        b = ttk.Frame(left)
        b.pack(fill="x", pady=4)
        ttk.Button(b, text="Remove", command=lambda: [self.jobs_tree.delete(i) for i in self.jobs_tree.selection()]
                   ).pack(side="left")
        ttk.Button(b, text="Default jobs", command=self.default_jobs).pack(side="left", padx=4)

        opts = ttk.LabelFrame(left, text="Algorithm", padding=6)
        opts.pack(fill="x", pady=6)
        self.algo = tk.StringVar(value=ROUND_ROBIN)
        for a in REAL_ALGORITHMS:
            ttk.Radiobutton(opts, text=a, value=a, variable=self.algo).pack(anchor="w")
        qf = ttk.Frame(opts)
        qf.pack(fill="x")
        ttk.Label(qf, text="Quantum (seconds):").pack(side="left")
        self.quantum = tk.StringVar(value="0.5")
        ttk.Entry(qf, textvariable=self.quantum, width=6).pack(side="left", padx=4)
        rb = ttk.Frame(left)
        rb.pack(fill="x")
        self.start_btn = ttk.Button(rb, text="Start", command=self.start)
        self.start_btn.pack(side="left", fill="x", expand=True)
        self.stop_btn = ttk.Button(rb, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(left, text="Show children in Process Tree",
                   command=lambda: app.tree_tab.focus_pid(os.getpid())).pack(fill="x", pady=4)

        cols = ("Job", "PID", "State", "Priority", "CPU needed", "Time on CPU")
        frame, self.status = make_tree(right, cols, (60, 70, 140, 70, 90, 90), height=5, anchor_left=("State",))
        frame.pack(fill="x")
        self.fig = Figure(figsize=(8, 2.8), dpi=90)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, pady=4)
        self.log = tk.Text(right, height=10, font=("Menlo", 11))
        self.log.pack(fill="both", expand=True)
        self.default_jobs()

    def default_jobs(self):
        self.jobs_tree.delete(*self.jobs_tree.get_children())
        for row in (("A", 2.0, 3, 0), ("B", 1.0, 1, 0), ("C", 1.5, 2, 0.5)):
            self.jobs_tree.insert("", "end", values=row)

    def add_job(self):
        try:
            v = self.vars
            job_id = v["ID"].get().strip()
            Job(job_id, 0, 1, 0)
            cpu, prio, arr = float(v["CPU sec"].get()), int(v["Priority"].get()), float(v["Arrival s"].get())
            if cpu <= 0 or cpu > 30 or arr < 0:
                raise ValueError("CPU seconds must be in (0, 30], arrival >= 0")
        except ValueError as exc:
            messagebox.showerror("Invalid job", str(exc))
            return
        self.jobs_tree.insert("", "end", values=(job_id, cpu, prio, arr))

    def get_jobs(self) -> List[Job]:
        jobs = []
        for i in self.jobs_tree.get_children():
            jid, cpu, prio, arr = self.jobs_tree.item(i, "values")
            j = Job(str(jid), 0, 1, int(prio))
            j.arrival, j.burst = float(arr), float(cpu)  # real mode uses seconds (floats)
            jobs.append(j)
        return jobs

    def start(self):
        if self.sched and not self.sched.finished:
            return
        try:
            jobs = self.get_jobs()
            if not jobs:
                raise ValueError("Add at least one job")
            if len({j.job_id for j in jobs}) != len(jobs):
                raise ValueError("Job IDs must be unique")
            self.sched = RealScheduler(jobs, self.algo.get(), float(self.quantum.get()), on_event=self.events.put)
        except ValueError as exc:
            messagebox.showerror("Cannot start", str(exc))
            return
        self.log.delete("1.0", "end")
        self.sched.start()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.poll()

    def stop(self):
        if self.sched:
            self.sched.stop()

    def poll(self):
        s = self.sched
        while True:
            try:
                self.log.insert("end", self.events.get_nowait() + "\n")
                self.log.see("end")
            except queue.Empty:
                break
        self.status.delete(*self.status.get_children())
        for row in s.status_rows():
            self.status.insert("", "end", values=row)
        ids = [rj.job.job_id for rj in s.jobs]
        tl = s.timeline_copy()
        now = s.now() if s.t0 else 0
        title = f"Live CPU timeline - {s.algorithm}" + (f" (quantum {s.quantum}s)" if s.algorithm == ROUND_ROBIN else "")
        draw_gantt(self.ax, tl, ids, title, end=max(now, 1))
        self.ax.set_xlabel("seconds")
        self.fig.tight_layout()
        self.canvas.draw_idle()
        if not s.finished:
            self.after(250, self.poll)
            return
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        if s.result:
            a = s.result.averages
            self.log.insert("end", f"\nRESULTS  avg waiting {a['avg_waiting']:.2f}s | avg turnaround "
                                   f"{a['avg_turnaround']:.2f}s | avg response {a['avg_response']:.2f}s | "
                                   f"throughput {a['throughput']:.2f} jobs/s | context switches "
                                   f"{a['context_switches']}\n")
            self.log.see("end")


# =========================================================================== main window
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CPU / Process Monitor & Job Scheduler")
        self.geometry("1320x840")
        self.minsize(1000, 650)
        try:
            ttk.Style(self).theme_use("clam")
        except tk.TclError:
            pass
        try:
            import getpass
            self.username = getpass.getuser()
        except Exception:
            self.username = ""
        self.monitor = mon.MonitorThread(interval=1.5)
        self.monitor.start()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        self.proc_tab = ProcessesTab(self.notebook, self)
        self.tree_tab = TreeTab(self.notebook, self)
        self.sys_tab = SystemTab(self.notebook, self)
        self.sched_tab = SchedulerTab(self.notebook, self)
        self.real_tab = RealTab(self.notebook, self)
        self.notebook.add(self.proc_tab, text="  Processes  ")
        self.notebook.add(self.tree_tab, text="  Process Tree  ")
        self.notebook.add(self.sys_tab, text="  System Monitor  ")
        self.notebook.add(self.sched_tab, text="  Scheduler (Simulation)  ")
        self.notebook.add(self.real_tab, text="  Real Process Scheduler  ")
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab)

        self.status_var = tk.StringVar(value="Starting monitor thread...")
        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w", padding=3).pack(fill="x")
        self._msg, self._msg_until = "", 0.0
        self._last_sample = -1
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(500, self.tick)

    def set_status(self, msg: str):
        self._msg, self._msg_until = msg, time.time() + 5

    def on_tab(self, _event=None):
        if self.notebook.select() == str(self.tree_tab) and not self.tree_tab.built:
            self.tree_tab.rebuild()
        self._last_sample = -1  # force refresh of the newly shown tab

    def tick(self):
        """Runs on the GUI thread every 0.5 s; pulls the latest data from the monitor thread."""
        procs, stats, history = self.monitor.latest()
        current = self.notebook.select()
        if self.monitor.samples != self._last_sample and procs:
            self._last_sample = self.monitor.samples
            if current == str(self.proc_tab):
                self.proc_tab.update_data(procs)
            elif current == str(self.sys_tab):
                self.sys_tab.update_data(stats, history)
        extra = f"   |   {self._msg}" if time.time() < self._msg_until else ""
        if stats:
            self.status_var.set(f"Monitor thread: {self.monitor.samples} samples   |   CPU {stats.cpu_total:.1f}%   "
                                f"Mem {stats.mem_percent:.1f}%   |   {stats.process_count} processes   |   "
                                f"Active Python threads in this app: {threading.active_count()}   |   "
                                f"This app PID {os.getpid()}{extra}")
        self.after(500, self.tick)

    def on_close(self):
        self.monitor.stop()
        if self.real_tab.sched and not self.real_tab.sched.finished:
            self.real_tab.sched.stop()
            self.real_tab.sched.join(timeout=2)
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
