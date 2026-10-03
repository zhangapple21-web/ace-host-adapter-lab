"""Unified error model for ACE Bridge."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Optional


@dataclass(frozen=True)
class BridgeError:
    """Structured error with machine-readable code and retryability."""
    code: str                    # 机器可读错误码，如 "INVALID_LIMIT", "ACE_CLI_TIMEOUT"
    message: str                 # 人类可读消息
    retryable: bool = False      # 是否可重试
    details: Optional[dict[str, Any]] = None  # 结构化上下文

    def to_dict(self) -> dict[str, Any]:
        d = {"code": self.code, "message": self.message, "retryable": self.retryable}
        if self.details:
            d["details"] = self.details
        return d


# 预定义错误码
class ErrorCodes:
    # 请求格式错误
    INVALID_JSON = "INVALID_JSON"
    INVALID_PROTOCOL = "INVALID_PROTOCOL"
    INVALID_REQUEST_ID = "INVALID_REQUEST_ID"
    INVALID_HOST_ID = "INVALID_HOST_ID"
    UNKNOWN_ACTION = "UNKNOWN_ACTION"
    MUTATION_DISABLED = "MUTATION_DISABLED"
    
    # 参数验证错误
    INVALID_LIMIT = "INVALID_LIMIT"
    INVALID_QUERY = "INVALID_QUERY"
    INVALID_QUERY_TYPE = "INVALID_QUERY_TYPE"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_MUST_BE_INT = "TOKEN_MUST_BE_INT"
    INVALID_REASON = "INVALID_REASON"
    INVALID_FAILURE_TYPE = "INVALID_FAILURE_TYPE"
    INVALID_CAPSULE_HASH = "INVALID_CAPSULE_HASH"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    INVALID_COMMAND = "INVALID_COMMAND"
    INVALID_POOL = "INVALID_POOL"
    INVALID_SCRATCH_NAME = "INVALID_SCRATCH_NAME"
    INVALID_SCRATCH_NAME_TRAVERSAL = "INVALID_SCRATCH_NAME_TRAVERSAL"
    INVALID_SCRATCH_NAME_RESERVED = "INVALID_SCRATCH_NAME_RESERVED"
    INVALID_SCRATCH_NAME_ESCAPE = "INVALID_SCRATCH_NAME_ESCAPE"
    INVALID_TASK_ID = "INVALID_TASK_ID"
    INVALID_OWNER = "INVALID_OWNER"
    INVALID_ACTOR = "INVALID_ACTOR"
    INVALID_CLAIM = "INVALID_CLAIM"
    CAPSULE_COMMAND_REQUIRED = "CAPSULE_COMMAND_REQUIRED"
    
    # 资源/IO 错误
    SNAPSHOT_TOO_LARGE = "SNAPSHOT_TOO_LARGE"
    SNAPSHOT_UNAVAILABLE = "SNAPSHOT_UNAVAILABLE"
    SNAPSHOT_INVALID = "SNAPSHOT_INVALID"
    PATH_OUTSIDE_ACE_ROOT = "PATH_OUTSIDE_ACE_ROOT"
    ACE_CLI_UNAVAILABLE = "ACE_CLI_UNAVAILABLE"
    ACE_CLI_TIMEOUT = "ACE_CLI_TIMEOUT"
    ACE_CLI_OUTPUT_INVALID = "ACE_CLI_OUTPUT_INVALID"
    ACE_CLI_FAILED = "ACE_CLI_FAILED"
    
    # 查询拒绝
    PATH_OR_MUTATION_REFUSED = "PATH_OR_MUTATION_REFUSED"
    NO_BOUNDED_MATCH = "NO_BOUNDED_MATCH"
    FREE_ZONE_UNAVAILABLE = "FREE_ZONE_UNAVAILABLE"
    
    # 系统错误
    INTERNAL_ERROR = "INTERNAL_ERROR"


def refuse(code: str, message: str, retryable: bool = False, details: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Convenience function to create a REFUSED response."""
    return {"status": "REFUSED", "error": BridgeError(code, message, retryable, details).to_dict(), "runtime_mutation": False}


def refuse_simple(reason: str) -> dict[str, Any]:
    """Backward compatible simple refusal."""
    return {"status": "REFUSED", "reason": reason, "runtime_mutation": False}