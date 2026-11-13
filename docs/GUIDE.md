# Building this project from zero: step by step

This is the order we built the project in, with the commands for each step. Every step ends with a check, so you know it worked before moving on.

---

## Step 0: Install the tools (macOS)

```bash
# 1. Homebrew (package manager), if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Python with a working Tk, git, and a small LaTeX compiler
brew install python-tk@3.12 git tectonic
```

Ubuntu: `sudo apt install python3 python3-venv python3-tk git texlive-latex-extra`

**Check:** `python3.12 -c "import tkinter; print(tkinter.TkVersion)"` prints 8.6 or higher.

---

## Step 1: Create the project and git repo

```bash
mkdir "SSL Project" && cd "SSL Project"
git init -b main
git config user.name  "Your Name"
git config user.email "you@iitdh.ac.in"
```

Make `.gitignore` (so the virtual environment and temporary files are not committed) and `requirements.txt` (`psutil`, `matplotlib`), then:

```bash
git add .gitignore requirements.txt
git commit -m "Initial project structure and requirements"
```

**Team tip:** put the repo on GitHub and add all five members. Each member works on a branch for their part (`git checkout -b monitor`), commits there, and merges into `main` with a pull request. Then the history shows who did what, which is good for the "git commit history" marks.

---

## Step 2: Virtual environment

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

A virtual environment is a private folder of Python libraries for this project only. (Later, `scripts/setup.sh` does this automatically.)

**Check:** `.venv/bin/python -c "import psutil, matplotlib"` prints nothing (no error).

---

## Step 3: Scheduling algorithms (`procsched/scheduler.py`)

Start with pure logic, without a GUI, because it's the easiest part to test.

1. A `Job` has an id, arrival, burst and priority.
2. Write `fcfs()`: sort by arrival, run each job fully. If no job has arrived yet, add an "idle" slice.
3. Write `priority_non_preemptive()`: at each step pick the ready job with the smallest priority number.
4. Write `priority_preemptive()`: like above, but stop and re-decide whenever a new job arrives.
5. Write `round_robin()`: a `deque` is the ready queue. Run each job for at most `quantum`, then put it at the back.
6. Each algorithm returns the timeline (list of slices) and the statistics: turnaround = finish - arrival, waiting = turnaround - burst, response = first run - arrival.

**Check:** solve the example (P1 0/5/3, P2 1/3/2, P3 2/1/1) on paper, then compare:
```bash
.venv/bin/python main.py --cli schedule --algo all
```
Commit: `git commit -m "Add FCFS, priority and round robin scheduling with stats"`

---

## Step 4: Process monitor (`procsched/monitor.py`)

1. `psutil.process_iter([...])` gives pid, ppid, name, status, cpu_percent, memory and more for every process.
2. Build the tree: group processes by `ppid`. A process whose parent we can't see is a root.
3. `send_signal(pid, action)` uses SIGTERM / SIGKILL / SIGSTOP / SIGCONT.
4. `MonitorThread` loops forever: take a snapshot, store it under a `threading.Lock`, sleep 1.5 s.

**Check:**
```bash
.venv/bin/python main.py --cli monitor --top 5
.venv/bin/python main.py --cli tree --pid 1 --depth 1
```
Compare with `ps -ef | head` and `top` in the terminal.

---

## Step 5: Real process scheduler (`procsched/executor.py`)

1. Each job is a real child process: `subprocess.Popen([python, "-c", "busy loop for N CPU seconds"])` (fork + exec).
2. A `threading.Thread` picks which child runs. It sends `SIGCONT` to the chosen one and `SIGSTOP` to the others.
3. In Round Robin, when the quantum ends it sends `SIGSTOP` and puts the job back in the queue.

**Check:**
```bash
.venv/bin/python main.py --cli real --algo rr -q 0.5
```
You should see `fork/exec`, `SIGSTOP` and `SIGCONT` lines in the log.

---

## Step 6: GUI and plots (`procsched/gui.py`)

1. `tk.Tk()` window + `ttk.Notebook` with 5 tabs.
2. Tables are `ttk.Treeview`. The process tree uses a Treeview with parent/child items.
3. Charts: matplotlib `Figure` put inside Tk with `FigureCanvasTkAgg`. The Gantt chart is `ax.barh()`.
4. **Golden rule:** only the main thread touches widgets. Use `self.after(500, self.tick)` to read new data from the monitor thread every 0.5 s.

**Check:** `./scripts/run.sh` opens the window, and every tab works.

---

## Step 7: Command line (`procsched/cli.py`) and `main.py`

`argparse` with sub-commands `schedule`, `monitor`, `tree` and `real`. `main.py` opens the GUI, or the CLI with `--cli`.

---

## Step 8: Tests (`tests/`)

Use Python's built-in `unittest`.
- Put the hand-solved example into tests (`assertEqual` on order and finish times).
- Test edge cases (idle gaps, one job, invalid input).
- Compare the fast priority code with a slow, simple version on random inputs.

**Check:** `.venv/bin/python -m unittest discover -s tests -v`

---

## Step 9: Bash scripts (`scripts/`)

Make each script executable once: `chmod +x scripts/*.sh`. Things to learn from them:
- `set -e`: stop at the first error
- `$1`, `${1:-3000}`: arguments with a default value
- `command -v x`: check whether a program is installed
- functions, `if`, `for`, `$( )`, pipes, `tee`, `grep -q`
- `trap cleanup EXIT`: run cleanup when the script ends (`stress.sh`)
- `&` and `$!`: start a background process and get its PID

**Check:** `./scripts/run_tests.sh` prints `ALL TESTS PASSED`.

---

## Step 10: Profiling (`profiling/profile_app.py`)

1. Time each algorithm on 3000 random jobs with `time.perf_counter()`.
2. Run the slowest one under `cProfile` and print the top functions with `pstats`, sorted by cumulative time.
3. Read the table: `ncalls` = how many calls, `tottime` = time inside the function itself, `cumtime` = including what it calls.
4. Save the output as `*_before.txt`, fix the slow part, run again, and save `*_after.txt`.

What we found: priority scheduling called `min()` over all ready jobs at every step (O(n^2)). A heap (`heapq`) fixed it, making it up to 133 times faster.

**Check:** `./scripts/profile.sh 3000`
(Optional: `pip install snakeviz` then `snakeviz profiling/results/scheduler_profile.prof` for a visual view.)

---

## Step 11: Report and slides (LaTeX)

- `report/report.tex`: an `article` with sections, tables (`booktabs`), figures (`graphicx`) and code (`listings`).
- `presentation/slides.tex`: `\documentclass{beamer}`, one `\begin{frame}` per slide.
- Fill in your names and roll numbers at the top of both files.

**Check:** `./scripts/build_docs.sh` creates `report/report.pdf` and `presentation/slides.pdf`.

---

## Step 12: Final check before submitting

```bash
./scripts/setup.sh
./scripts/run_tests.sh
./scripts/profile.sh
./scripts/build_docs.sh
git status          # should say "nothing to commit"
git log --oneline   # meaningful history
```
