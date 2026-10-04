"""Enforce that the three tool surfaces cannot drift apart.

tool-surface.json is the single source of truth. The Python MCP server, the PI
plugin manifest, and the PI plugin runtime must all agree with it, and the ACE
capsule command set and bridge limits must agree too.
"""
import asyncio
import json
import unittest
from pathlib import Path

from ace_capsule import COMMANDS
from ace_mcp_server import create_server
from bridge_config import get_config

ROOT = Path(__file__).resolve().parent
SURFACE = json.loads((ROOT / "tool-surface.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((ROOT / "pi-plugin" / "manifest.json").read_text(encoding="utf-8"))


class ToolSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.config = get_config()
        self.names = [t["name"] for t in SURFACE["read_tools"]] + [SURFACE["capsule_tool"]["name"]]

    def test_mcp_server_registers_exactly_the_declared_tools(self):
        server = create_server(self.config.ace_root, self.config)
        registered = {tool.name for tool in asyncio.run(server.list_tools())}
        self.assertEqual(registered, set(self.names))

    def test_manifest_mirrors_the_surface(self):
        declared = MANIFEST["contributes"]["agentTools"]
        self.assertEqual([t["name"] for t in declared], self.names)
        by_name = {t["name"]: t for t in declared}
        for tool in SURFACE["read_tools"]:
            self.assertEqual(by_name[tool["name"]]["description"], tool["description"])
            self.assertEqual(by_name[tool["name"]]["schema"], tool["schema"])
            self.assertEqual(by_name[tool["name"]]["risk"], tool["risk"])
        capsule = SURFACE["capsule_tool"]
        self.assertEqual(by_name[capsule["name"]]["description"], capsule["description"])
        self.assertEqual(by_name[capsule["name"]]["schema"], capsule["schema"])

    def test_capsule_command_enum_matches_the_ace_bridge(self):
        enum = SURFACE["capsule_tool"]["schema"]["properties"]["command"]["enum"]
        self.assertEqual(sorted(enum), sorted(COMMANDS))
        self.assertEqual(sorted(SURFACE["capsule_tool"]["schema"]["properties"]["pool"]["enum"]),
                         ["production", "scratch"])

    def test_surface_limits_match_bridge_config(self):
        limits = SURFACE["limits"]
        self.assertEqual(self.config.max_limit, limits["task_limit_max"])
        self.assertEqual(self.config.default_limit, limits["default_limit"])
        self.assertEqual(self.config.query_max_len, limits["query_max_len"])

    def test_surface_declares_no_unexpected_mutation(self):
        self.assertEqual(SURFACE["tool_count"], len(self.names))
        self.assertEqual(SURFACE["read_tool_count"], len(SURFACE["read_tools"]))
        # Only ace_capsule may leave the read surface, and it is declared as such.
        self.assertFalse(SURFACE["capsule_tool"]["read_only"])
        self.assertEqual(SURFACE["mutation_policy"], "fail_closed")


if __name__ == "__main__":
    unittest.main()