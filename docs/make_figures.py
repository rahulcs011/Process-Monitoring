# make_figures.py - draws the charts used in the report and the slides.
# run: .venv/bin/python docs/make_figures.py
import os
import sys

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from procsched.gui import PALETTE, draw_gantt
from procsched.scheduler import compare_all, example_jobs

OUT = os.path.join(os.path.dirname(__file__), "figures")
os.makedirs(OUT, exist_ok=True)

results = compare_all(example_jobs(), 2)
ids = ["P1", "P2", "P3"]

# 1. gantt chart of every algorithm
fig = Figure(figsize=(10, 6))
for i, r in enumerate(results):
    ax = fig.add_subplot(2, 2, i + 1)
    draw_gantt(ax, r.timeline, ids, r.algorithm, end=9)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "gantt_all.png"), dpi=150)

# 2. average waiting / turnaround / response for every algorithm
fig = Figure(figsize=(9, 4.5))
ax = fig.add_subplot(111)
metrics = [("avg_waiting", "Waiting"), ("avg_turnaround", "Turnaround"), ("avg_response", "Response")]
w = 0.2
for i, r in enumerate(results):
    vals = [r.averages[m] for m, _ in metrics]
    xs = [k + (i - 1.5) * w for k in range(3)]
    bars = ax.bar(xs, vals, w, label=r.algorithm, color=PALETTE[i])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.05, "%.2f" % v, ha="center", fontsize=8)
ax.set_xticks(range(3))
ax.set_xticklabels([n for _, n in metrics])
ax.set_ylabel("average time (lower is better)")
ax.legend(fontsize=8)
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "compare.png"), dpi=150)

# 3. profiling: before vs after (numbers from profiling/results)
def read_times(path):
    times = {}
    for line in open(path):
        if line.rstrip().endswith(" s") and "snapshot" not in line:
            name, val = line.rsplit(None, 2)[0], line.split()[-2]
            times[name.strip()] = float(val)
    return times

res = os.path.join(os.path.dirname(__file__), "..", "profiling", "results")
before = read_times(os.path.join(res, "timing_before.txt"))
after = read_times(os.path.join(res, "timing_after.txt"))
names = list(before)
fig = Figure(figsize=(9, 4.5))
ax = fig.add_subplot(111)
xs = range(len(names))
ax.bar([x - 0.2 for x in xs], [before[n] for n in names], 0.4, label="before", color=PALETTE[3])
ax.bar([x + 0.2 for x in xs], [after[n] for n in names], 0.4, label="after (heap)", color=PALETTE[2])
for x, n in zip(xs, names):
    ax.text(x - 0.2, before[n] + 0.01, "%.4f" % before[n], ha="center", fontsize=8)
    ax.text(x + 0.2, after[n] + 0.01, "%.4f" % after[n], ha="center", fontsize=8)
ax.set_xticks(list(xs))
ax.set_xticklabels(names, fontsize=8)
ax.set_ylabel("seconds for 3000 jobs")
ax.set_title("Scheduler run time before and after optimisation")
ax.legend()
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "profiling.png"), dpi=150)
print("figures written to", OUT)
