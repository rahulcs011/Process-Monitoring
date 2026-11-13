import os
import unittest

from procsched import monitor as mon
from procsched.executor import RealScheduler
from procsched.scheduler import (FCFS, ROUND_ROBIN, Job, compare_all, example_jobs, fcfs, parse_jobs,
                                 priority_non_preemptive, priority_preemptive, round_robin)


def finish_times(result):
    return {s.job_id: s.finish for s in result.jobs}


def order(result):
    return [s.job_id for s in result.timeline]


class TestAlgorithms(unittest.TestCase):
    """Expected values were worked out by hand (see README)."""

    def test_fcfs(self):
        r = fcfs(example_jobs())
        self.assertEqual(order(r), ["P1", "P2", "P3"])
        self.assertEqual(finish_times(r), {"P1": 5, "P2": 8, "P3": 9})
        self.assertAlmostEqual(r.averages["avg_waiting"], 10 / 3)
        self.assertAlmostEqual(r.averages["avg_turnaround"], 19 / 3)

    def test_priority_non_preemptive(self):
        r = priority_non_preemptive(example_jobs())
        self.assertEqual(order(r), ["P1", "P3", "P2"])
        self.assertAlmostEqual(r.averages["avg_waiting"], 8 / 3)

    def test_priority_preemptive(self):
        r = priority_preemptive(example_jobs())
        self.assertEqual(order(r), ["P1", "P2", "P3", "P2", "P1"])
        self.assertEqual(finish_times(r), {"P1": 9, "P2": 5, "P3": 3})
        self.assertAlmostEqual(r.averages["avg_waiting"], 5 / 3)
        self.assertEqual(r.averages["avg_response"], 0)

    def test_round_robin(self):
        r = round_robin(example_jobs(), 2)
        self.assertEqual(order(r), ["P1", "P2", "P3", "P1", "P2", "P1"])
        self.assertEqual(finish_times(r), {"P1": 9, "P2": 8, "P3": 5})
        self.assertAlmostEqual(r.averages["avg_waiting"], 10 / 3)
        self.assertAlmostEqual(r.averages["avg_response"], 1.0)
        self.assertEqual(r.averages["context_switches"], 5)

    def test_round_robin_large_quantum_equals_fcfs(self):
        jobs = example_jobs()
        self.assertEqual(finish_times(round_robin(jobs, 100)), finish_times(fcfs(jobs)))

    def test_idle_gap(self):
        r = fcfs([Job("A", 0, 2), Job("B", 5, 1)])
        self.assertEqual([(s.job_id, s.start, s.end) for s in r.timeline],
                         [("A", 0, 2), (None, 2, 5), ("B", 5, 6)])
        self.assertAlmostEqual(r.averages["cpu_utilization"], 50.0)

    def test_all_jobs_finish_and_burst_conserved(self):
        jobs = parse_jobs("A:0:7:2,B:2:4:1,C:4:1:3,D:5:4:2,E:20:3:1")
        for r in compare_all(jobs, 3):
            for s in r.jobs:
                ran = sum(sl.length for sl in r.timeline if sl.job_id == s.job_id)
                self.assertEqual(ran, s.burst, f"{r.algorithm} {s.job_id}")
                self.assertGreaterEqual(s.waiting, 0)
                self.assertGreaterEqual(s.start, s.arrival)

    def test_validation(self):
        with self.assertRaises(ValueError):
            Job("X", 0, 0)
        with self.assertRaises(ValueError):
            fcfs([Job("A", 0, 1), Job("A", 1, 1)])
        with self.assertRaises(ValueError):
            round_robin(example_jobs(), 0)


class TestMonitor(unittest.TestCase):
    def test_snapshot_contains_self_and_tree(self):
        procs = mon.snapshot()
        pids = {p.pid for p in procs}
        self.assertIn(os.getpid(), pids)
        roots, children = mon.build_tree(procs)
        self.assertIn(os.getpid(), children.get(os.getppid(), []))
        chain = mon.ancestors(os.getpid(), procs)
        self.assertEqual(chain[0], os.getpid())
        self.assertIn(chain[-1], roots)

    def test_refuses_to_signal_self(self):
        with self.assertRaises(PermissionError):
            mon.send_signal(os.getpid(), "kill")


class TestRealScheduler(unittest.TestCase):
    def test_round_robin_real_processes(self):
        a, b = Job("A", 0, 1), Job("B", 0, 1)
        a.burst, b.burst = 0.6, 0.3
        s = RealScheduler([a, b], ROUND_ROBIN, 0.2)
        s.start()
        s.join(20)
        self.assertTrue(s.finished)
        self.assertIsNotNone(s.result)
        self.assertEqual(order(s.result)[:3], ["A", "B", "A"])
        fin = finish_times(s.result)
        self.assertLess(fin["B"], fin["A"])

    def test_fcfs_real_processes(self):
        a, b = Job("A", 0, 1), Job("B", 0, 1)
        a.burst, b.burst = 0.3, 0.2
        s = RealScheduler([a, b], FCFS, 1)
        s.start()
        s.join(20)
        self.assertEqual([x for x in order(s.result) if x], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
