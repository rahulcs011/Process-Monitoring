# 5-minute presentation plan

The slides are 6 pages. Page 1 has the topic, the team and the roles; "Thank you" is at the bottom of page 6. Ganesh presents the slides, since Ganesh made the report and slides. Rahul runs the live demo and answers code questions, since Rahul wrote the code. Both of us stand on stage the whole time.

**Before going on stage**
- Run `./scripts/setup.sh` and `./scripts/run_tests.sh` once, so nothing has to install during the demo.
- Open `presentation/slides.pdf` full screen, start the app (`./scripts/run.sh`), and open a second terminal in the project folder.
- Make the terminal font large (Cmd and +). Close heavy apps so the CPU graph is calm.

| Time | Who | Slide / screen | What to say |
|---|---|---|---|
| 0:00-0:40 | Rahul | 1. Topic, team and roles | Good morning. We are Rahul Ahirwar and Ganesh. Our project is a CPU / Process Monitor and Job Scheduler. Rahul designed and wrote all the code: the scheduler, the process monitor, the real scheduler with threads and signals, the GUI, scripts, tests and profiling. I wrote the LaTeX report and slides and I'm presenting. |
| 0:40-1:05 | Ganesh | 2. Problem statement | Hundreds of processes, one CPU core. Two questions: what is running now (monitoring) and who runs next (scheduling). Our app answers both. |
| 1:05-1:50 | Ganesh | 3. Proposed approach | We split the problem into five parts. What is running now: every 1.5 seconds we read all running programs and show them in a table, a family tree and graphs. Who runs next: we coded FCFS, Priority and Round Robin, drew a timeline for each and measured waiting time. Does it work for real: we run real programs and pause or resume them in turns. Keeping the app smooth: background threads collect the data. Is it fast and correct: we profiled to find the slow part, made it up to 133 times faster, and wrote 26 tests that all pass. |
| 1:50-2:15 | Ganesh | 4. Results | We ran three jobs: one long, one medium, one short. Priority (the version that can interrupt a running job) has the least waiting, 1.67. Round Robin gives the quickest first reply, 1.00. Our program's answers match what we worked out by hand. |
| 2:15-4:15 | Rahul | 5. Working demo, then switch to the app | **Processes**: in terminal 2 run `./scripts/stress.sh 2 60`, sort by CPU %, Suspend a worker (CPU drops to 0, SIGSTOP), Resume (SIGCONT). **Process Tree**: "Find this app", chain up to PID 1. **System Monitor**: live graph from the monitor thread. **Scheduler**: Example, Round Robin, Run, then Compare all. **Real Process Scheduler**: Round Robin, Start; the log shows fork/exec, SIGSTOP, SIGCONT. |
| 4:15-4:50 | Rahul | 6. Conclusion | One app shows what is running now and decides who runs next. There is no single best method: Priority suits urgent jobs, Round Robin is the fairest. Next we'd add Shortest Job First. |
| 4:50-5:00 | Ganesh | 6. "Thank you!" | Thank you, we are happy to take questions. |

**Backup if the GUI fails:** `./scripts/demo.sh` shows everything in the terminal.

**Likely questions**
- *Why can't Tk be updated from a thread?* Tk is not thread safe. Only the main thread touches widgets; other threads pass data through a lock or queue.
- *Why does the real job measure CPU time, not wall time?* So that pausing it with SIGSTOP really delays it, like a real CPU-bound job.
- *What is a zombie / orphan?* Zombie: finished, but the parent has not called wait(). Orphan: the parent died, so PID 1 adopts it.
- *How do you choose the RR quantum?* Too small means many context switches. Too large and it behaves like FCFS. Our test `test_round_robin_large_quantum_equals_fcfs` shows the second case.
- *What does cumtime mean in cProfile?* Time spent in a function including everything it calls. tottime excludes the functions it calls.
- *Draw the Round Robin (q=2) Gantt chart:* P1 0-2, P2 2-4, P3 4-5, P1 5-7, P2 7-8, P1 8-9.
