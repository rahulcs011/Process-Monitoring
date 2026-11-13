# test_extra.py - more tests: optimised priority code vs a simple reference,
# edge cases, helpers, the monitor and the command line.
import contextlib
import io
import os
import unittest

from procsched import cli
from procsched import monitor as mon
from procsched.scheduler import (Job, ascii_gantt, compare_all, fcfs, parse_jobs,
                                 priority_non_preemptive, priority_preemptive,
                                 random_jobs, round_robin)


def slow_priority(jobs, preemptive):
    # simple 1-time-unit-at-a-time version, easy to check by hand.
    # used to make sure the fast heap version gives the same answer.
    remaining = {j.job_id: j.burst for j in jobs}
    order = {j.job_id: i for i, j in enumerate(jobs)}
    finish = {}
    running = None
    t = 0
    while len(finish) < len(jobs):
        ready = [j for j in jobs if j.arrival <= t and j.job_id not in finish]
        if not ready:
            t += 1
            continue
        if preemptive or running is None:
            running = min(ready, key=lambda j: (j.priority, j.arrival, order[j.job_id]))
        remaining[running.job_id] -= 1
        t += 1
        if remaining[running.job_id] == 0:
            finish[running.job_id] = t
            running = None
    return finish


def finish_times(result):
    return {s.job_id: s.finish for s in result.jobs}


class TestAgainstReference(unittest.TestCase):
    def test_priority_np_matches_reference(self):
        for seed in range(150):
            jobs = random_jobs(8, max_arrival=12, max_burst=6, max_priority=3, seed=seed)
            self.assertEqual(finish_times(priority_non_preemptive(jobs)),
                             slow_priority(jobs, preemptive=False), "seed %d" % seed)

    def test_priority_p_matches_reference(self):
        for seed in range(150):
            jobs = random_jobs(8, max_arrival=12, max_burst=6, max_priority=3, seed=seed)
            self.assertEqual(finish_times(priority_preemptive(jobs)),
                             slow_priority(jobs, preemptive=True), "seed %d" % seed)


class TestEdgeCases(unittest.TestCase):
    def test_single_job(self):
        for r in compare_all([Job("A", 3, 4)], 2):
            self.assertEqual(r.jobs[0].finish, 7)
            self.assertEqual(r.jobs[0].waiting, 0)

    def test_all_arrive_together_rr_quantum_1(self):
        r = round_robin([Job("A", 0, 2), Job("B", 0, 2)], 1)
        self.assertEqual([s.job_id for s in r.timeline], ["A", "B", "A", "B"])

    def test_starvation_of_low_priority_job(self):
        # L has low priority and keeps getting pushed back by new important jobs
        jobs = [Job("L", 0, 2, 9)] + [Job("H%d" % i, i * 2, 2, 1) for i in range(5)]
        r = priority_preemptive(jobs)
        low = [s for s in r.jobs if s.job_id == "L"][0]
        self.assertEqual(low.finish, 12)
        self.assertEqual(low.waiting, 10)

    def test_convoy_effect(self):
        # one long job first makes short jobs wait a lot in FCFS, RR helps them
        jobs = [Job("Long", 0, 20), Job("S1", 1, 1), Job("S2", 1, 1)]
        self.assertGreater(fcfs(jobs).averages["avg_waiting"],
                           round_robin(jobs, 2).averages["avg_waiting"])

    def test_same_priority_uses_arrival_order(self):
        r = priority_non_preemptive([Job("A", 0, 1, 2), Job("B", 0, 1, 2)])
        self.assertEqual([s.job_id for s in r.timeline], ["A", "B"])


class TestHelpers(unittest.TestCase):
    def test_parse_jobs(self):
        jobs = parse_jobs("A:0:3, B:2:4:1")
        self.assertEqual((jobs[1].job_id, jobs[1].arrival, jobs[1].burst, jobs[1].priority), ("B", 2, 4, 1))
        with self.assertRaises(ValueError):
            parse_jobs("A:1")

    def test_random_jobs_same_seed_same_jobs(self):
        self.assertEqual(random_jobs(5, seed=3), random_jobs(5, seed=3))

    def test_ascii_gantt(self):
        g = ascii_gantt(fcfs([Job("A", 0, 2), Job("B", 4, 1)]))
        self.assertIn("idle", g)
        self.assertTrue(g.splitlines()[1].endswith("5"))


class TestMonitorAndCli(unittest.TestCase):
    def test_tree_text_has_this_process(self):
        procs = mon.snapshot()
        self.assertIn("(%d)" % os.getpid(), mon.tree_text(procs))

    def test_system_stats_look_sane(self):
        s = mon.system_stats()
        self.assertTrue(0 <= s.mem_percent <= 100)
        self.assertGreater(s.process_count, 1)
        self.assertGreater(len(s.cpu_per_core), 0)

    def test_cli_schedule_output(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["schedule", "--algo", "rr", "-q", "2"])
        self.assertIn("Avg response 1.00", out.getvalue())

    def test_cli_bad_input_exit_code(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                cli.main(["schedule", "--jobs", "A:0:0"])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
