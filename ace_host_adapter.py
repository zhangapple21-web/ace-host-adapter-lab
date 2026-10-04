#!/usr/bin/env python3
"""Read-only host bridge projecting the canonical ACE Runtime."""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bridge_config import BridgeConfig, get_config
from bridge_errors import BridgeError, ErrorCodes, refuse, refuse_simple
from bridge_logging import get_logger, log_request, log_response, log_error, log_timing
from bridge_ratelimit import check_rate_limit
from bridge_metrics import record_metric, record_error_metric

PROTOCOL = "ace.host_adapter.v0"
READ_ACTIONS = {"capabilities", "status", "tasks", "learning", "archaeology", "governance", "query", "health", "metrics"}
MUTATING_ACTIONS = {"request_task", "approve", "execute", "cancel"}
TASK_STATUSES = ("pending", "active", "blocked", "review", "approved", "archived", "rejected", "graveyard")
QUERY_TYPES = {"auto", "map", "library", "lineage", "capability", "status", "tasks", "learning", "archaeology", "governance", "relation"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, ace_root: Path, config: BridgeConfig = None) -> Any:
    if config is None:
        config = get_config()
    if not path.resolve().is_relative_to(ace_root.resolve()):
        raise ValueError("path_outside_ace_root")
    data = path.read_bytes()
    if len(data) > config.max_snapshot_size:
        raise ValueError("snapshot_too_large")
    return json.loads(data.decode("utf-8-sig"))


def _task_summary(path: Path, ace_root: Path, config: BridgeConfig) -> dict[str, Any] | None:
    try:
        payload = _read_json(path, ace_root, config)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    fields = ("task_id", "status", "priority", "created_at", "updated_at")
    return {key: payload[key] for key in fields if isinstance(payload.get(key), (str, int, float, bool))}


def _read_snapshot(ace_root: Path, relative: str, config: BridgeConfig) -> dict[str, Any]:
    try:
        payload = _read_json(ace_root / relative, ace_root, config)
    except (OSError, ValueError, json.JSONDecodeError):
        return {"available": False, "reason": "snapshot_unavailable", "path": relative}
    if not isinstance(payload, dict):
        return {"available": False, "reason": "snapshot_invalid", "path": relative}
    return {"available": True, "path": relative, "keys": sorted(str(k) for k in payload)[:100]}


def _read_lineage(ace_root: Path, limit: int = 20, config: BridgeConfig = None) -> dict[str, Any]:
    if config is None:
        config = get_config()
    relative = "06_RUNTIME/ace/data/local_archaeologist_state.lineage.jsonl"
    path = ace_root / relative
    if not path.is_file():
        return {"available": False, "path": relative, "entries": [], "source": "missing"}
    try:
        if path.stat().st_size > config.max_snapshot_size:
            return {"available": False, "path": relative, "entries": [], "source": "read_error", "reason": "snapshot_too_large"}
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()[-max(1, min(limit, 100)):]
    except OSError:
        return {"available": False, "path": relative, "entries": [], "source": "read_error"}
    entries = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            entries.append({key: item[key] for key in ("at", "fingerprint", "source_ref", "policy", "governance") if key in item})
    return {"available": True, "path": relative, "entries": entries, "source": "canonical_runtime_lineage"}


def _read_status(ace_root: Path, config: BridgeConfig) -> dict[str, Any]:
    relative = "06_RUNTIME/ace/data/memory/daemon_state.json"
    try:
        payload = _read_json(ace_root / relative, ace_root, config)
    except (OSError, ValueError, json.JSONDecodeError):
        return {"available": False, "reason": "daemon_state_unavailable", "path": relative, "liveness": "UNKNOWN"}
    if not isinstance(payload, dict):
        return {"available": False, "reason": "daemon_state_invalid", "path": relative, "liveness": "UNKNOWN"}
    allowed = {"run_status", "last_run", "last_heartbeat", "continuity_status", "updated_at"}
    return {"available": True, "source": "canonical_persisted_snapshot", "path": relative, "liveness": "UNKNOWN", "freshness": "snapshot_liveness_unknown", **{key: payload[key] for key in sorted(allowed) if isinstance(payload.get(key), (str, int, bool))}}


def _read_tasks(ace_root: Path, limit: int, config: BridgeConfig) -> list[dict[str, Any]]:
    pool = ace_root / "task_pool"
    results: list[dict[str, Any]] = []
    if not pool.is_dir():
        return results
    for status in TASK_STATUSES:
        status_dir = pool / status
        if not status_dir.is_dir():
            continue
        for path in sorted(status_dir.glob("RQ-*.json")):
            item = _task_summary(path, ace_root, config)
            if item is not None:
                results.append(item)
            if len(results) >= limit:
                return results
    return results


def _fa_result(ace_root: Path) -> dict[str, Any]:
    sandbox = ace_root / "07_SANDBOX" / "free_research"
    names = ("experiments", "distillations", "promotion_proposals", "reports")
    return {"id": "free_zone", "name": "FA / Free Zone", "kind": "sandbox", "location": str(sandbox.relative_to(ace_root)), "entrypoints": ["core.free_zone_autonomy.FreeZoneAutonomy", "core.sandbox_society.SandboxSociety"], "assets": {name: len(list((sandbox / name).glob("*.json"))) if (sandbox / name).is_dir() else 0 for name in names}, "production_integration": False}


def _query(ace_root: Path, query: str, query_type: str = "auto", limit: int = 20, config: BridgeConfig = None) -> dict[str, Any]:
    if config is None:
        config = get_config()
    text = query.strip().lower()
    if not text:
        return {"query": query, "query_type": query_type, "result": [], "missing": ["query"], "epistemic_status": "UNKNOWN"}
    if query_type not in QUERY_TYPES:
        return {"query": query, "query_type": query_type, "result": [], "errors": ["unsupported_query_type"], "epistemic_status": "UNKNOWN"}
    # 路径遍历和变异操作关键词过滤
    mutation_tokens = (
        "../", "..\\", ":\\", "/",
        "execute", "approve", "delete", "删除", "执行", "审批",
        "创建", "新建", "添加", "修改", "更新", "编辑", "变更", "取消", "撤销", "移除",
        "运行", "启动", "停止", "暂停", "恢复", "批准", "拒绝", "通过", "驳回"
    )
    if any(token in text for token in mutation_tokens):
        return {"query": query, "query_type": query_type, "result": [], "errors": ["arbitrary_path_or_mutation_query_refused"], "epistemic_status": "UNKNOWN"}
    if query_type in {"auto", "map", "library", "capability"} and (re.search(r"\bfa\b", text) or any(token in text for token in ("free zone", "free_research", "自由区"))):
        if not (ace_root / "07_SANDBOX" / "free_research").is_dir():
            return {"query": query, "query_type": query_type, "result": [], "missing": ["free_zone_source"], "epistemic_status": "UNKNOWN"}
        return {"query": query, "query_type": "map", "result": [_fa_result(ace_root)], "source": "canonical_ace_layout", "confidence": "high", "epistemic_status": "FACT_FROM_RUNTIME_LAYOUT", "evidence": ["07_SANDBOX/free_research", "docs/ACE_FREE_RESEARCH_SANDBOX_001.md"]}
    if query_type in {"auto", "status"} and any(token in text for token in ("status", "状态", "running", "运行")):
        return {"query": query, "query_type": "status", "result": [_read_status(ace_root, config)], "source": "canonical_persisted_snapshot", "confidence": "medium", "epistemic_status": "SNAPSHOT_NOT_LIVENESS", "evidence": ["06_RUNTIME/ace/data/memory/daemon_state.json"]}
    if query_type in {"auto", "tasks"} and any(token in text for token in ("task", "任务", "pending", "阻塞")):
        return {"query": query, "query_type": "tasks", "result": _read_tasks(ace_root, limit, config), "source": "canonical_task_pool", "confidence": "high", "epistemic_status": "BOUNDED_STATE_PROJECTION", "evidence": ["task_pool/"]}
    if query_type in {"lineage", "archaeology"}:
        safe_limit = int(limit) if isinstance(limit, (int, float)) else config.default_limit
        return {"query": query, "query_type": "lineage", "result": [_read_lineage(ace_root, safe_limit, config)], "source": "canonical_runtime_lineage", "confidence": "high", "epistemic_status": "LINEAGE_EVIDENCE"}
    return {"query": query, "query_type": query_type, "result": [], "source": "canonical_ace_runtime", "confidence": "low", "missing": ["no_bounded_match"], "epistemic_status": "UNKNOWN"}


def handle(request: dict[str, Any], ace_root: Path, config: BridgeConfig = None) -> dict[str, Any]:
    if config is None:
        config = get_config()
    logger = get_logger("ace_host_adapter")
    start_time = time.perf_counter()
    request_id = request.get("request_id") if isinstance(request, dict) else None
    host_id = request.get("host_id") if isinstance(request, dict) else None
    action = request.get("action") if isinstance(request, dict) else None
    
    if request_id and host_id and action:
        log_request(logger, request_id, host_id, action)
    
    def _refuse_response(code: str, message: str, retryable: bool = False, details: dict = None) -> dict[str, Any]:
        if request_id and host_id and action:
            log_error(logger, request_id, code, message)
            log_response(logger, request_id, "REFUSED")
        # 单一插桩点：handle() 里每一条拒绝路径都汇聚到这里，包括那些绕过下方
        # 计时段落的提前 return（协议不符、速率限制、mutation 禁用、参数非法等）。
        # 缺了这里 errors_total 永远是空的，拒绝请求也从不进 requests_total。
        _metric_action = action if isinstance(action, str) and action else "unknown"
        record_error_metric(_metric_action, code, config)
        record_metric(_metric_action, "REFUSED", time.perf_counter() - start_time, config)
        # 向后兼容：保留 reason 字段
        base = refuse(code, message, retryable, details)
        base["reason"] = message  # 兼容旧版本
        return base | {"protocol": PROTOCOL, "request_id": request_id, "at": _now()}
    
    if not isinstance(request, dict):
        return _refuse_response(ErrorCodes.INVALID_JSON, "request_must_be_object")
    
    # 验证 request_id 和 host_id
    for key in ("request_id", "host_id"):
        val = request.get(key)
        if not isinstance(val, str) or not val.strip() or len(val) > config.request_id_max_len:
            return _refuse_response(ErrorCodes.INVALID_REQUEST_ID if key == "request_id" else ErrorCodes.INVALID_HOST_ID,
                                    f"{key}_required_or_invalid")
    
    if request.get("protocol") != PROTOCOL:
        return _refuse_response(ErrorCodes.INVALID_PROTOCOL, "protocol_mismatch")
    
    action = str(request.get("action", "")).strip()
    
    # 速率限制检查 (健康检查和能力查询除外)
    if action not in ("health", "capabilities"):
        allowed, rate_info = check_rate_limit(host_id, action, config)
        if not allowed:
            return _refuse_response(ErrorCodes.INVALID_ARGUMENTS, "rate_limit_exceeded", retryable=True, 
                                    details={"retry_after_seconds": rate_info["retry_after"], "limit": rate_info["limit"]})
    
    # 健康检查特殊处理（不需要完整协议验证）
    if action == "health":
        import time as _time
        start = _time.perf_counter()
        checks = {
            "ace_root": {"status": "ok" if ace_root.is_dir() else "fail", "path": str(ace_root)},
            "task_pool": {"status": "ok" if (ace_root / "task_pool").is_dir() else "degraded"},
            "runtime": {"status": "ok" if (ace_root / "06_RUNTIME").is_dir() else "degraded"},
        }
        overall = "healthy" if all(c["status"] == "ok" for c in checks.values()) else "degraded"
        return {"protocol": PROTOCOL, "request_id": request_id, "status": "OK", "health": {
            "status": overall,
            "checks": checks,
            "latency_ms": round((_time.perf_counter() - start) * 1000, 2),
            "protocol": PROTOCOL,
            "version": "0.1.0",
        }, "at": _now()}
    
    if action in MUTATING_ACTIONS:
        return _refuse_response(ErrorCodes.MUTATION_DISABLED, "mutation_disabled_read_only_bridge")
    if action not in READ_ACTIONS:
        return _refuse_response(ErrorCodes.UNKNOWN_ACTION, "unknown_action")
    
    try:
        if action == "capabilities":
            resp = {"protocol": PROTOCOL, "request_id": request["request_id"], "status": "READY", "host_id": request["host_id"], "read_actions": sorted(READ_ACTIONS), "mutation_actions": sorted(MUTATING_ACTIONS), "mutation_policy": "fail_closed", "authority": "canonical_ace_runtime_only", "at": _now()}
        elif action == "status":
            resp = {"protocol": PROTOCOL, "request_id": request["request_id"], "status": "OK", "ace": _read_status(ace_root, config), "at": _now()}
        elif action == "learning":
            relative = "09_KNOWLEDGE/self_evolution/proposals.jsonl"
            path = ace_root / relative
            try:
                count = len(path.read_text(encoding="utf-8-sig", errors="replace").splitlines()) if path.is_file() else 0
                learning = {"available": path.is_file(), "path": relative, "records": count, "production_integration": False}
            except OSError:
                learning = {"available": False, "reason": "snapshot_unavailable", "path": relative}
            resp = {"protocol": PROTOCOL, "request_id": request["request_id"], "status": "OK", "learning": learning, "at": _now()}
        elif action == "archaeology":
            resp = {"protocol": PROTOCOL, "request_id": request["request_id"], "status": "OK", "archaeology": _read_snapshot(ace_root, "06_RUNTIME/ace/data/local_archaeologist_state.json", config), "lineage": _read_lineage(ace_root, config=config), "at": _now()}
        elif action == "query":
            query = request.get("query", "")
            if set(request) - {"protocol", "request_id", "host_id", "action", "query", "query_type", "limit"}:
                return _refuse_response(ErrorCodes.INVALID_ARGUMENTS, "invalid_query_arguments")
            if not isinstance(query, str) or len(query) > config.query_max_len:
                return _refuse_response(ErrorCodes.INVALID_QUERY, "invalid_query")
            raw_limit = request.get("limit", config.default_limit)
            if isinstance(raw_limit, bool) or not isinstance(raw_limit, int) or not 1 <= raw_limit <= config.max_limit:
                return _refuse_response(ErrorCodes.INVALID_LIMIT, "invalid_limit")
            limit = raw_limit
            resp = {"protocol": PROTOCOL, "request_id": request["request_id"], "status": "OK", "cognition": _query(ace_root, query, str(request.get("query_type", "auto")), limit, config), "at": _now()}
        elif action == "governance":
            resp = {"protocol": PROTOCOL, "request_id": request["request_id"], "status": "OK", "governance": _read_snapshot(ace_root, "08_GOVERNANCE/free_zone_exchange/loop_status_latest.json", config), "at": _now()}
        elif action == "metrics":
            from bridge_metrics import get_metrics
            metrics = get_metrics(config)
            resp = {"protocol": PROTOCOL, "request_id": request["request_id"], "status": "OK", "metrics": metrics.get_metrics_dict(), "at": _now()}
        else:  # tasks
            try:
                limit = max(1, min(int(request.get("limit", config.default_limit)), config.max_limit))
            except (TypeError, ValueError):
                return _refuse_response(ErrorCodes.INVALID_LIMIT, "invalid_limit")
            resp = {"protocol": PROTOCOL, "request_id": request["request_id"], "status": "OK", "tasks": _read_tasks(ace_root, limit, config), "at": _now()}
    except Exception as e:
        logger.exception("unhandled_error", extra={"request_id": request_id})
        resp = _refuse_response(ErrorCodes.INTERNAL_ERROR, "internal_error", details={"type": type(e).__name__})
    
    if request_id and host_id and action:
        duration_ms = (time.perf_counter() - start_time) * 1000
        log_timing(logger, request_id, action, duration_ms)
        log_response(logger, request_id, resp.get("status", "UNKNOWN"))
        # 记录指标；拒绝路径已在 _refuse_response 内记录，此处跳过以免重复计数
        if "error" not in resp:
            record_metric(action, resp.get("status", "UNKNOWN"), duration_ms / 1000.0, config)
    
    return resp


def main(argv: list[str] | None = None) -> int:
    config = get_config()
    logger = get_logger("ace_host_adapter")
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python ace_host_adapter.py <ace-root>", file=sys.stderr)
        return 2
    ace_root = Path(args[0]).expanduser().resolve()
    logger.info("starting", extra={"ace_root": str(ace_root), "protocol": PROTOCOL})
    
    # Windows 上 select 不支持 stdin，使用线程实现读取超时
    import threading
    import queue
    
    stdin_queue: queue.Queue = queue.Queue()
    read_timeout = 300  # 5分钟全局读取超时
    eof_event = threading.Event()  # 标记 EOF
    _EOF = object()  # 队列哨兵：EOF 时唤醒阻塞中的 get()
    
    def stdin_reader():
        try:
            for line in sys.stdin:
                if eof_event.is_set():
                    break
                stdin_queue.put(line)
        finally:
            # EOF 必须同时唤醒主循环。只 set() 事件而不投递哨兵的话，主循环仍阻塞在
            # stdin_queue.get(timeout=300) 上，要等满 read_timeout 才复查 eof_event ——
            # 实测响应早已打印，进程却再挂 300 秒才退出，宿主侧每个调用都会超时。
            eof_event.set()
            stdin_queue.put(_EOF)
    
    reader_thread = threading.Thread(target=stdin_reader, daemon=True)
    reader_thread.start()
    
    while True:
        try:
            # 如果已 EOF 且队列为空，退出
            if eof_event.is_set() and stdin_queue.empty():
                break
            line = stdin_queue.get(timeout=read_timeout)
        except queue.Empty:
            if eof_event.is_set():
                break
            logger.warning("stdin_read_timeout", extra={"timeout_seconds": read_timeout})
            continue
        if line is _EOF:
            break
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = handle(request, ace_root, config)
        except json.JSONDecodeError:
            response = refuse(ErrorCodes.INVALID_JSON, "invalid_json") | {"protocol": PROTOCOL, "request_id": None, "at": _now()}
        print(json.dumps(response, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())