import json
import tempfile
import unittest
from pathlib import Path

from ace_host_adapter import PROTOCOL, _read_json, handle


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "ace"
        self.root.mkdir()

    def request(self, action, **extra):
        return handle(dict(protocol=PROTOCOL, request_id="r1", host_id="codex", action=action, **extra), self.root)

    def test_capabilities(self):
        self.assertEqual(self.request("capabilities")["mutation_policy"], "fail_closed")

    def test_mutations_refused(self):
        for action in ("request_task", "approve", "execute", "cancel"):
            result = self.request(action)
            self.assertEqual(result["status"], "REFUSED")
            self.assertFalse(result["runtime_mutation"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_protocol_and_ids(self):
        self.assertEqual(handle([], self.root)["status"], "REFUSED")
        self.assertEqual(handle({"host_id": "pi"}, self.root)["status"], "REFUSED")
        self.assertEqual(handle(dict(request_id="r", host_id="pi", action="status"), self.root)["reason"], "protocol_mismatch")
        self.assertEqual(self.request("shell")["reason"], "unknown_action")

    def test_status_missing_and_invalid(self):
        self.assertFalse(self.request("status")["ace"]["available"])
        path = self.root / "06_RUNTIME/ace/data/memory/daemon_state.json"
        path.parent.mkdir(parents=True)
        path.write_text("broken", encoding="utf-8")
        self.assertFalse(self.request("status")["ace"]["available"])

    def test_status_projection_and_no_writes(self):
        path = self.root / "06_RUNTIME/ace/data/memory/daemon_state.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"run_status": "alive", "api_key": "secret", "updated_at": {"secret": "hidden"}}), encoding="utf-8")
        before = path.read_bytes()
        result = self.request("status")["ace"]
        self.assertEqual(result["liveness"], "UNKNOWN")
        self.assertEqual(result["run_status"], "alive")
        self.assertNotIn("api_key", result)
        self.assertNotIn("updated_at", result)
        self.assertEqual(before, path.read_bytes())

    def test_tasks_projection_and_limit(self):
        folder = self.root / "task_pool/pending"
        folder.mkdir(parents=True)
        for index in range(3):
            (folder / f"RQ-{index}.json").write_text(json.dumps({"task_id": f"RQ-{index}", "status": "pending", "title": "private", "claim_id": "secret", "evidence": ["private"]}), encoding="utf-8")
        tasks = self.request("tasks", limit=2)["tasks"]
        self.assertEqual(len(tasks), 2)
        self.assertEqual(set(tasks[0]), {"task_id", "status"})
        self.assertEqual(self.request("tasks", limit="bad")["reason"], "invalid_limit")

    def test_outside_root_and_large_file(self):
        outside = Path(self.temp.name) / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            _read_json(outside, self.root)
        large = self.root / "large.json"
        large.write_bytes(b" " * (1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            _read_json(large, self.root)


if __name__ == "__main__":
    unittest.main()
