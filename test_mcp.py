import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class McpTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "06_RUNTIME/ace/data/memory/daemon_state.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"run_status": "fixture", "api_key": "hidden"}))
            task = root / "task_pool/pending/RQ-test.json"
            task.parent.mkdir(parents=True)
            task.write_text(json.dumps({"task_id": "RQ-test", "title": "private"}))
            before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            params = StdioServerParameters(command=sys.executable, args=["-B",
                str(Path(__file__).with_name("ace_mcp_server.py")), "--ace-root", str(root)],
                env={"PYTHONDONTWRITEBYTECODE": "1", "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows")})
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    self.assertEqual({t.name for t in tools}, {"ace_capabilities", "ace_status", "ace_tasks", "ace_learning", "ace_archaeology", "ace_governance", "ace_query", "ace_capsule", "ace_health", "ace_metrics"})
                    self.assertTrue(all(t.annotations.readOnlyHint for t in tools if t.name != "ace_capsule"))
                    self.assertFalse(next(t for t in tools if t.name == "ace_capsule").annotations.readOnlyHint)
                    result = await session.call_tool("ace_capabilities", {})
                    self.assertFalse(result.isError)
                    self.assertEqual(result.structuredContent["status"], "READY")
                    result = await session.call_tool("ace_status", {})
                    self.assertEqual(result.structuredContent["ace"]["liveness"], "UNKNOWN")
                    status_result = result
                    result = await session.call_tool("ace_query", {"query": "status", "query_type": "status"})
                    self.assertFalse(result.isError)
                    self.assertEqual(result.structuredContent["cognition"]["epistemic_status"], "SNAPSHOT_NOT_LIVENESS")
                    self.assertNotIn("api_key", status_result.structuredContent["ace"])
                    result = await session.call_tool("ace_tasks", {"limit": 1})
                    self.assertEqual(result.structuredContent["tasks"], [{"task_id": "RQ-test"}])
                    self.assertTrue((await session.call_tool("ace_tasks", {"limit": 101})).isError)
                    self.assertTrue((await session.call_tool("execute", {})).isError)
            after = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
