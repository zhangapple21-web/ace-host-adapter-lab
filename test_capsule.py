import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, r"C:\tmp\ace_core")
from core.task import TaskPool
from ace_capsule import invoke

ADMISSION = {
    "source_type": "evidence",
    "source_ref": "pi-bridge",
    "why_now": "prove the PI bridge uses the existing capsule port",
    "evidence": [{"source": "field-scan", "content": "ops.worker_capsule_cli exists"}],
    "expected_result": "scratch round trip",
    "verification_method": "existing CLI",
    "risk": "scratch pool only",
    "estimated_scope": "one test",
}


class CapsuleBridgeTests(unittest.TestCase):
    def test_scratch_round_trip_and_refusals(self):
        name = f"pi{time.time_ns()}"
        pool = Path(__import__("tempfile").gettempdir()) / "ace-pi-bridge" / name
        admission = dict(ADMISSION, source_ref=name)
        task = TaskPool(str(pool)).create_task(
            "PI bridge drill", hypothesis="bridge can use existing CLI", creator="pi",
            complexity="complex", tags=["research"], admission=admission,
        )
        listed = invoke({"command": "list-pending", "pool": "scratch", "scratch_name": name})
        self.assertEqual(listed["status"], "LISTED")
        self.assertEqual(listed["pending"][0]["task_id"], task.task_id)
        started = invoke({"command": "start", "pool": "scratch", "scratch_name": name, "task_id": task.task_id, "owner": "pi-bridge"})
        self.assertEqual(started["status"], "STARTED")
        rendered = invoke({"command": "render", "pool": "scratch", "scratch_name": name, "task_id": task.task_id, "claim": started["claim_id"], "token": started["fencing_token"]})
        self.assertEqual(rendered["status"], "CAPSULE_READY")
        submitted = invoke({"command": "submit", "pool": "scratch", "scratch_name": name, "task_id": task.task_id, "claim": started["claim_id"], "token": started["fencing_token"], "actor": "pi-bridge", "capsule_hash": rendered["capsule_hash"], "payload": {"summary": "bridge drill complete", "facts": ["existing CLI accepted the result"], "transition": "review"}})
        self.assertEqual(submitted["status"], "SUBMITTED")
        refused_execute = invoke({"command": "execute", "pool": "scratch", "scratch_name": name})
        self.assertEqual(refused_execute["status"], "REFUSED")
        self.assertEqual(refused_execute["error"]["code"], "INVALID_COMMAND")
        self.assertEqual(refused_execute["error"]["message"], "unknown_or_disabled_command")
        refused_pool = invoke({"command": "list-pending", "pool": "elsewhere"})
        self.assertEqual(refused_pool["status"], "REFUSED")
        self.assertEqual(refused_pool["error"]["code"], "INVALID_ARGUMENTS")
        self.assertEqual(refused_pool["error"]["message"], "pool_must_be_production_or_scratch")


if __name__ == "__main__":
    unittest.main()
