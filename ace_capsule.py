#!/usr/bin/env python3
"""Bounded facade over ACE's existing worker capsule CLI.

No shell, no arbitrary paths, and no second TaskPool. Production is the ACE
task_pool. Scratch pools must live under the machine temp root, which is the
same gate the CLI already enforces.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from bridge_config import BridgeConfig, get_config
from bridge_errors import BridgeError, ErrorCodes, refuse, refuse_simple
from bridge_logging import get_logger, log_request, log_response, log_error, log_timing
from bridge_metrics import record_error_metric, record_metric

COMMANDS = {
    "list-pending": set(),
    "show": {"task_id"},
    "recover": {"owner"},
    "reclaim": {"task_id", "actor"},
    "start": {"task_id", "owner"},
    "render": {"task_id", "claim", "token"},
    "renew": {"task_id", "claim", "token", "owner"},
    "submit": {"task_id", "claim", "token", "actor", "payload"},
    "fail": {"task_id", "claim", "token", "actor", "reason"},
}
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _refuse_response(error_code: str, message: str, retryable: bool = False, details: dict = None) -> dict[str, Any]:
    return refuse(error_code, message, retryable, details) | {"runtime_mutation": False}


def pool_dir(request: dict[str, Any], config: BridgeConfig) -> Path:
    mode = request.get("pool", "production")
    if mode == "production":
        return config.ace_root / "task_pool"
    if mode != "scratch":
        raise ValueError("pool_must_be_production_or_scratch")
    name = request.get("scratch_name", "")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError("invalid_scratch_name")
    # 深度路径遍历防御：拒绝 ..、绝对路径、UNC、设备路径、保留名
    normalized = os.path.normpath(name)
    if normalized != name or ".." in name.split(os.sep) or os.path.isabs(name):
        raise ValueError("invalid_scratch_name_traversal")
    # Windows 保留名检查
    reserved = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
                "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}
    if name.upper().split(".")[0] in reserved:
        raise ValueError("invalid_scratch_name_reserved")
    # 使用与 CLI 一致的 scratch 根目录判定逻辑
    def _scratch_roots():
        return {Path(value).resolve() for value in (os.environ.get("TEMP"), os.environ.get("TMP"), os.environ.get("TMPDIR")) if value}
    roots = _scratch_roots()
    if not roots:
        # 兜底：用系统 temp 目录
        roots = {Path(tempfile.gettempdir()).resolve()}
    target = None
    for root in roots:
        candidate = (root / "ace-pi-bridge" / name).resolve()
        # 双重检查：确保解析后仍在允许的根目录下
        if root in candidate.parents:
            target = candidate
            break
    if target is None:
        # 如果没有匹配的根，用第一个根创建
        root = next(iter(roots))
        target = (root / "ace-pi-bridge" / name).resolve()
    # 最终确认：target 必须在某个允许根目录下
    if not any(root in target.parents for root in roots):
        raise ValueError("invalid_scratch_name_escape")
    target.mkdir(parents=True, exist_ok=True)
    return target


def _argv(command: str, pool: Path, request: dict[str, Any], config: BridgeConfig) -> list[str]:
    argv = [str(config.python), "-B", "-m", "ops.worker_capsule_cli", "--pool", str(pool), command]
    for key, flag in (("task_id", "--task-id"), ("owner", "--owner"), ("actor", "--actor"), ("claim", "--claim")):
        if key in COMMANDS[command] and key != "payload":
            value = request.get(key)
            if not isinstance(value, str) or not ID_RE.fullmatch(value):
                raise ValueError(f"invalid_{key}")
            argv.extend([flag, value])
    if "token" in COMMANDS[command]:
        token = request.get("token")
        if isinstance(token, bool) or not isinstance(token, int):
            raise ValueError("invalid_token")
        argv.extend(["--token", str(token)])
    if command == "fail":
        reason = request.get("reason")
        failure_type = request.get("failure_type", "retryable")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > config.reason_max_len:
            raise ValueError("invalid_reason")
        if failure_type not in {"retryable", "permanent", "manual_gate", "external_condition"}:
            raise ValueError("invalid_failure_type")
        argv.extend(["--reason", reason, "--type", failure_type])
    if command == "submit":
        payload = request.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("payload_must_be_object")
        argv.extend(["--payload", json.dumps(payload, ensure_ascii=False)])
        capsule_hash = request.get("capsule_hash", "")
        if capsule_hash:
            if not isinstance(capsule_hash, str) or not ID_RE.fullmatch(capsule_hash):
                raise ValueError("invalid_capsule_hash")
            argv.extend(["--capsule-hash", capsule_hash])
    return argv


def invoke(request: dict[str, Any], config: BridgeConfig = None) -> dict[str, Any]:
    if config is None:
        config = get_config()
    logger = get_logger("ace_capsule")
    start_time = time.perf_counter()
    command = request.get("command") if isinstance(request, dict) else None
    
    if command:
        log_request(logger, request.get("request_id", "unknown"), request.get("host_id", "unknown"), f"capsule:{command}")
    
    def _refuse_resp(code: str, message: str, retryable: bool = False, details: dict = None) -> dict[str, Any]:
        if command:
            log_error(logger, request.get("request_id", "unknown"), code, message)
            log_response(logger, request.get("request_id", "unknown"), "REFUSED")
        # The capsule path is this bridge's only mutating surface, so make it
        # countable. Labeled capsule:<command> to stay distinct from the
        # adapter's read actions and to keep refusals visible next to successes.
        label = f"capsule:{command}" if isinstance(command, str) and command else "capsule:unknown"
        record_error_metric(label, code, config)
        record_metric(label, "REFUSED", time.perf_counter() - start_time, config)
        return _refuse_response(code, message, retryable, details)
    
    if not isinstance(request, dict):
        return _refuse_resp(ErrorCodes.INVALID_JSON, "request_must_be_object")
    
    command = request.get("command")
    if command not in COMMANDS:
        return _refuse_resp(ErrorCodes.INVALID_COMMAND, "unknown_or_disabled_command")
    
    try:
        argv = _argv(command, pool_dir(request, config), request, config)
    except ValueError as error:
        return _refuse_resp(ErrorCodes.INVALID_ARGUMENTS, str(error))
    
    try:
        # stdin=DEVNULL also forces close_fds=True on Windows. Without it the
        # child inherits this host's stdio pipe handles, and if any grandchild
        # keeps one open, communicate() blocks until timeout even though the CLI
        # already finished. Measured: capsule calls ran the full 180s timeout from
        # an MCP host while the identical call took ~130ms standalone.
        result = subprocess.run(
            argv, cwd=str(config.ace_root), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=config.cli_timeout, check=False,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired as e:
        try:
            if e.process is not None:
                e.process.kill()
                e.process.wait(timeout=5)
        except Exception:
            pass
        return _refuse_resp(ErrorCodes.ACE_CLI_TIMEOUT, "ace_cli_timeout", retryable=True)
    except OSError as e:
        return _refuse_resp(ErrorCodes.ACE_CLI_UNAVAILABLE, "ace_cli_unavailable", retryable=True, details={"error": str(e)})
    
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        return _refuse_resp(ErrorCodes.ACE_CLI_OUTPUT_INVALID, "ace_cli_output_invalid", details={"stdout_lines": len(lines), "stderr": result.stderr[:500]})
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError:
        return _refuse_resp(ErrorCodes.ACE_CLI_OUTPUT_INVALID, "ace_cli_output_invalid", details={"raw": lines[0][:500]})
    if not isinstance(payload, dict):
        return _refuse_resp(ErrorCodes.ACE_CLI_OUTPUT_INVALID, "ace_cli_output_invalid")
    
    if command:
        duration_ms = (time.perf_counter() - start_time) * 1000
        log_timing(logger, request.get("request_id", "unknown"), f"capsule:{command}", duration_ms)
        log_response(logger, request.get("request_id", "unknown"), payload.get("status", "OK"))
        record_metric(f"capsule:{command}", payload.get("status", "OK"), duration_ms / 1000.0, config)
    
    return payload


def main() -> int:
    config = get_config()
    logger = get_logger("ace_capsule")
    logger.info("starting", extra={"ace_root": str(config.ace_root), "python": str(config.python)})
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = invoke(request, config)
        except json.JSONDecodeError:
            response = _refuse_response(ErrorCodes.INVALID_JSON, "invalid_json")
        print(json.dumps(response, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())