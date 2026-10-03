"""Read-only stdio MCP facade; ACE remains the independent authority."""
import argparse
from pathlib import Path
from uuid import uuid4
from typing import Any
import time
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from bridge_config import BridgeConfig, get_config
from bridge_errors import ErrorCodes, refuse
from bridge_metrics import get_metrics
from ace_host_adapter import PROTOCOL, handle
from ace_capsule import invoke as invoke_capsule


def create_server(ace_root: Path, config: BridgeConfig = None) -> FastMCP:
    if config is None:
        config = get_config()
    server = FastMCP("ACE Host Adapter")
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                  idempotentHint=True, openWorldHint=False)

    def read(action: str, **extra) -> dict[str, Any]:
        return handle(dict(protocol=PROTOCOL, request_id=str(uuid4()),
                           host_id="mcp", action=action, **extra), ace_root, config)

    def _refuse_mcp(code: str, message: str) -> dict[str, Any]:
        return refuse(code, message) | {"protocol": PROTOCOL, "request_id": str(uuid4()), "at": datetime.now(timezone.utc).isoformat()}

    @server.tool(annotations=annotations, structured_output=True)
    def ace_capabilities() -> dict[str, Any]:
        """Query adapter capabilities. Host labels are not authorization."""
        return read("capabilities")

    @server.tool(annotations=annotations, structured_output=True)
    def ace_status() -> dict[str, Any]:
        """Read default persisted ACE state. Snapshot liveness is UNKNOWN."""
        return read("status")

    @server.tool(annotations=annotations, structured_output=True)
    def ace_tasks(limit: int = 20) -> dict[str, Any]:
        """Read bounded TaskPool ID/status summaries; excludes bodies and credentials."""
        if not 1 <= limit <= config.max_limit:
            raise ValueError("limit must be between 1 and 100")
        return read("tasks", limit=limit)

    @server.tool(annotations=annotations, structured_output=True)
    def ace_learning() -> dict[str, Any]:
        """Read bounded LearningReturn/self-evolution metadata."""
        return read("learning")

    @server.tool(annotations=annotations, structured_output=True)
    def ace_archaeology() -> dict[str, Any]:
        """Read bounded archaeology snapshot and append-only lineage."""
        return read("archaeology")

    @server.tool(annotations=annotations, structured_output=True)
    def ace_governance() -> dict[str, Any]:
        """Read bounded governance snapshot metadata."""
        return read("governance")

    @server.tool(annotations=annotations, structured_output=True)
    def ace_query(query: str, query_type: str = "auto", limit: int = 20) -> dict[str, Any]:
        """Return a bounded, source-aware ACE cognition result for direct hits."""
        if not 1 <= limit <= config.max_limit:
            raise ValueError("limit must be between 1 and 100")
        if not isinstance(query, str) or len(query) > config.query_max_len:
            raise ValueError("query must be at most 256 characters")
        return read("query", query=query, query_type=query_type, limit=limit)

    @server.tool(annotations=annotations, structured_output=True)
    def ace_health() -> dict[str, Any]:
        """Health check endpoint for liveness/readiness probes."""
        start = time.perf_counter()
        checks = {
            "ace_root": {"status": "ok" if ace_root.is_dir() else "fail", "path": str(ace_root)},
            "task_pool": {"status": "ok" if (ace_root / "task_pool").is_dir() else "degraded"},
            "runtime": {"status": "ok" if (ace_root / "06_RUNTIME").is_dir() else "degraded"},
        }
        overall = "healthy" if all(c["status"] == "ok" for c in checks.values()) else "degraded"
        return {
            "status": overall,
            "checks": checks,
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "protocol": PROTOCOL,
            "version": "0.1.0",
        }

    @server.tool(annotations=annotations, structured_output=True)
    def ace_metrics() -> dict[str, Any]:
        """Return collected metrics (request counts, latency, errors)."""
        metrics = get_metrics(config)
        return {"metrics": metrics.get_metrics_dict(), "protocol": PROTOCOL}

    write_annotations = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                        idempotentHint=False, openWorldHint=False)

    @server.tool(annotations=write_annotations, structured_output=True)
    def ace_capsule(command: str, pool: str = "production", scratch_name: str = "",
                    task_id: str = "", owner: str = "", actor: str = "", claim: str = "",
                    token: int | None = None, reason: str = "", failure_type: str = "retryable",
                    capsule_hash: str = "",
                    payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run one existing ACE worker-capsule command. ACE validates credentials and pool face."""
        if isinstance(token, bool):
            return _refuse_mcp(ErrorCodes.TOKEN_MUST_BE_INT, "token_must_be_int_not_bool")
        request = {"command": command, "pool": pool, "failure_type": failure_type}
        if scratch_name:
            request["scratch_name"] = scratch_name
        for key, value in {"task_id": task_id, "owner": owner, "actor": actor, "claim": claim, "reason": reason, "capsule_hash": capsule_hash}.items():
            if value:
                request[key] = value
        if token is not None:
            request["token"] = token
        if payload is not None:
            request["payload"] = payload
        return invoke_capsule(request, config)

    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ace-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.ace_root.resolve()
    if not root.is_dir():
        parser.error("ACE root must be an existing directory")
    config = get_config()
    config.ace_root = root
    create_server(root, config).run(transport="stdio")


if __name__ == "__main__":
    main()