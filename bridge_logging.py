"""Structured logging configuration for ACE Bridge."""
from __future__ import annotations
import logging
import sys
import json
import os
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """JSON log formatter with consistent fields."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        # 添加额外字段
        for key, value in record.__dict__.items():
            if key not in {"name", "msg", "args", "created", "filename", "funcName", "levelname", "levelno",
                          "lineno", "module", "msecs", "message", "msg", "name", "pathname", "process",
                          "processName", "relativeCreated", "thread", "threadName", "exc_info", "exc_text", "stack_info"}:
                log_obj[key] = value
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj, ensure_ascii=False)


def setup_logging(name: str = "ace_bridge", level: str = None) -> logging.Logger:
    """Configure structured JSON logging."""
    if level is None:
        level = os.environ.get("ACE_BRIDGE_LOG_LEVEL", "INFO")
    
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # 避免重复添加 handler
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    
    return logger


def get_logger(name: str = None) -> logging.Logger:
    """Get logger instance."""
    return logging.getLogger(name or "ace_bridge")


# 便捷函数
def log_request(logger: logging.Logger, request_id: str, host_id: str, action: str, **extra):
    logger.info("request_received", extra={"request_id": request_id, "host_id": host_id, "action": action, **extra})

def log_response(logger: logging.Logger, request_id: str, status: str, **extra):
    logger.info("response_sent", extra={"request_id": request_id, "status": status, **extra})

def log_error(logger: logging.Logger, request_id: str, error_code: str, message: str, **extra):
    logger.error("request_error", extra={"request_id": request_id, "error_code": error_code, "error_message": message, **extra})

def log_timing(logger: logging.Logger, request_id: str, operation: str, duration_ms: float, **extra):
    logger.info("timing", extra={"request_id": request_id, "operation": operation, "duration_ms": duration_ms, **extra})