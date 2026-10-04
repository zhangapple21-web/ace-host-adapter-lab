"""Regression tests for the three integration defects fixed on 2026-10-04.

Each of these guards a failure that was observed in production, not a
hypothetical: the adapter ignored stdin EOF and hung for its full 300s idle
timeout, refusals never reached the metrics collector, and the capsule
subprocess inherited host stdio handles on Windows and blocked in
communicate() until timeout.
"""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))

import ace_capsule
from ace_capsule import invoke as capsule_invoke
from ace_host_adapter import PROTOCOL, handle
from bridge_config import get_config
from bridge_metrics import get_metrics


class AdapterEofRegression(unittest.TestCase):
    """The adapter must exit promptly once its stdin closes."""

    def test_exits_promptly_on_stdin_eof(self):
        request = json.dumps({
            "protocol": PROTOCOL, "request_id": "eof-1", "host_id": "regression",
            "action": "capabilities",
        }) + "\n"
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                [sys.executable, "-B", str(LAB / "ace_host_adapter.py"),
                 str(get_config().ace_root)],
                input=request, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=20, check=False,
            )
        except subprocess.TimeoutExpired:
            self.fail("adapter did not exit within 20s after stdin EOF; "
                      "the reader thread must wake the main loop on EOF")
        elapsed = time.perf_counter() - started
        self.assertEqual(proc.returncode, 0)
        self.assertLess(elapsed, 15, "adapter lingered after answering")
        payload = json.loads([l for l in proc.stdout.splitlines() if l.strip()][0])
        self.assertEqual(payload["status"], "READY")
        self.assertEqual(payload["request_id"], "eof-1")


class RefusalMetricsRegression(unittest.TestCase):
    """Every refusal must be counted exactly once, and errors must be counted."""

    def setUp(self):
        get_metrics().reset()
        self.config = get_config()

    def _call(self, request_id, action, **extra):
        return handle({"protocol": PROTOCOL, "request_id": request_id,
                       "host_id": "regression", "action": action, **extra},
                      self.config.ace_root, self.config)

    def test_refusal_is_recorded_once_in_both_counters(self):
        response = self._call("mut", "execute")
        self.assertEqual(response["error"]["code"], "MUTATION_DISABLED")
        snap = get_metrics().get_metrics_dict()
        self.assertEqual(snap["errors_total"], {"execute:MUTATION_DISABLED": 1})
        self.assertEqual(snap["requests_total"], {"execute:REFUSED": 1})

    def test_every_mutating_action_is_refused_and_counted(self):
        for action in ("execute", "approve", "cancel", "request_task"):
            with self.subTest(action=action):
                response = self._call(f"m-{action}", action)
                self.assertEqual(response["status"], "REFUSED")
                self.assertEqual(response["error"]["code"], "MUTATION_DISABLED")
        snap = get_metrics().get_metrics_dict()
        self.assertEqual(len(snap["errors_total"]), 4)
        self.assertEqual(sum(snap["requests_total"].values()), 4)

    def test_unknown_action_and_protocol_mismatch_are_counted(self):
        self._call("unk", "definitely_not_an_action")
        self._call("proto", "status", protocol="wrong.protocol.v0")
        snap = get_metrics().get_metrics_dict()
        self.assertEqual(snap["errors_total"], {
            "definitely_not_an_action:UNKNOWN_ACTION": 1,
            "status:INVALID_PROTOCOL": 1,
        })

    def test_success_is_not_double_counted(self):
        self._call("ok", "status")
        snap = get_metrics().get_metrics_dict()
        self.assertEqual(snap["errors_total"], {})
        self.assertEqual(snap["requests_total"], {"status:OK": 1})


class CapsuleMetricsRegression(unittest.TestCase):
    """The mutating surface must be countable, including its refusals."""

    def setUp(self):
        get_metrics().reset()
        self.config = get_config()
        self.name = f"capmetric{time.time_ns()}"

    def tearDown(self):
        import shutil
        shutil.rmtree(Path(tempfile.gettempdir()) / "ace-pi-bridge" / self.name,
                      ignore_errors=True)

    def test_success_and_refusal_are_both_counted(self):
        ok = capsule_invoke({"command": "list-pending", "pool": "scratch",
                             "scratch_name": self.name})
        self.assertEqual(ok["status"], "LISTED")
        refused = capsule_invoke({"command": "execute", "pool": "scratch",
                                  "scratch_name": self.name})
        self.assertEqual(refused["status"], "REFUSED")

        snap = get_metrics().get_metrics_dict()
        self.assertEqual(snap["requests_total"].get("capsule:list-pending:LISTED"), 1)
        self.assertEqual(snap["requests_total"].get("capsule:execute:REFUSED"), 1)
        self.assertEqual(snap["errors_total"].get("capsule:execute:INVALID_COMMAND"), 1)
        # The read surface must not be polluted by capsule labels.
        self.assertFalse([k for k in snap["requests_total"] if k.startswith("execute:")])


class CapsuleSubprocessGuard(unittest.TestCase):
    """The capsule CLI must not inherit the host's stdio handles."""

    def test_capsule_spawn_closes_stdin(self):
        captured = {}
        real_run = ace_capsule.subprocess.run

        def spy(argv, **kwargs):
            captured.update(kwargs)
            return real_run(argv, **kwargs)

        name = f"guard{time.time_ns()}"
        ace_capsule.subprocess.run = spy
        try:
            response = capsule_invoke(
                {"command": "list-pending", "pool": "scratch", "scratch_name": name})
        finally:
            ace_capsule.subprocess.run = real_run

        self.assertEqual(response["status"], "LISTED")
        self.assertIn("stdin", captured, "subprocess.run must be called with an explicit stdin")
        self.assertEqual(captured["stdin"], subprocess.DEVNULL,
                         "stdin must be DEVNULL so Windows closes inherited handles")
        self.assertTrue(captured.get("capture_output"))

        import shutil
        import os
        pool = Path(tempfile.gettempdir()) / "ace-pi-bridge" / name
        shutil.rmtree(pool, ignore_errors=True)
        del os


if __name__ == "__main__":
    unittest.main()