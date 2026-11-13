# 5-minute demo plan

**Before going on stage**
- Run `./scripts/setup.sh` and `./scripts/run_tests.sh` once, so nothing has to install during the demo.
- Open two terminal windows in the project folder, and have `presentation/slides.pdf` open.
- Make the terminal font large (Cmd and +).
- Close heavy apps so the CPU graph is calm before the stress test.

| Time | Who | What to show | What to say |
|---|---|---|---|
| 0:00-0:40 | Member 1 | Slides 1-3 | The problem: many processes, one CPU. Our app monitors processes and schedules jobs. The course topics we used. |
| 0:40-1:30 | Member 2 | `./scripts/run.sh`, **Processes** tab. In terminal 2: `./scripts/stress.sh 2 60` | Sort by CPU %: the two workers jump to the top at about 100%. Select one and press **Suspend**: its CPU drops to 0 (SIGSTOP). Press **Resume** (SIGCONT). |
| 1:30-2:00 | Member 2 | **Process Tree** tab, "Find this app", search for `bash` | Every process has a parent (PPID). Show the chain up to launchd (PID 1). The stress workers are children of the bash script. |
| 2:00-2:20 | Member 3 | **System Monitor** tab | Live CPU graph from the monitor thread. The GUI stays smooth because the data is collected on a separate thread. |
| 2:20-3:20 | Member 1 / 3 | **Scheduler** tab: Example, Round Robin, Run (animated). Then **Compare all** | FCFS: short jobs wait behind P1 (convoy effect). Round Robin: same waiting, but response time 1.00 vs 3.33. Preemptive priority is best here but can starve low-priority jobs. |
| 3:20-4:05 | Member 4 | **Real Process Scheduler** tab: Round Robin, Start. Then "Show children in Process Tree" | These are real processes. The log shows fork/exec, SIGSTOP when the quantum ends, and SIGCONT. The chart is real time in seconds. |
| 4:05-4:45 | Member 5 | Terminal: `./scripts/profile.sh 3000`, then the profiling slide | cProfile showed 6.2 million `min()` calls in priority scheduling, which is O(n^2). We used a heap and it became 133 times faster. 26 tests and a check against a reference version prove the results stayed the same. |
| 4:45-5:00 | Member 5 | `git log --oneline \| head`, conclusion slide | Git history, bash scripts, report. AI declaration. Thank you. |

**Backup if the GUI fails:** `./scripts/demo.sh` shows everything in the terminal.

**Likely questions**
- *Why can't Tk be updated from a thread?* Tk is not thread safe. Only the main thread touches widgets; other threads pass data through a lock or queue.
- *Why does the real job measure CPU time, not wall time?* So that pausing it with SIGSTOP really delays it, like a real CPU-bound job.
- *What is a zombie / orphan?* Zombie: finished, but the parent has not called wait(). Orphan: the parent died, so PID 1 adopts it.
- *How do you choose the RR quantum?* Too small means many context switches. Too large and it behaves like FCFS. Our test `test_round_robin_large_quantum_equals_fcfs` shows the second case.
- *What does cumtime mean in cProfile?* Time spent in a function including everything it calls. tottime excludes the functions it calls.
