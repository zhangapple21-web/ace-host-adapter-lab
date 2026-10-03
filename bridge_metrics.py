"""Lightweight metrics collector for ACE Bridge."""
from __future__ import annotations
import time
import threading
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Dict, Optional


@dataclass
class MetricSnapshot:
    """Snapshot of metrics at a point in time."""
    requests_total: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    latency_sum: Dict[str, float] = field(default_factory=lambda: defaultdict(float))
    latency_count: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    errors_total: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    start_time: float = field(default_factory=time.monotonic)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for reporting."""
        avg_latency = {}
        for key in self.latency_sum:
            if self.latency_count[key] > 0:
                avg_latency[key] = self.latency_sum[key] / self.latency_count[key]
        
        return {
            "uptime_seconds": time.monotonic() - self.start_time,
            "requests_total": dict(self.requests_total),
            "avg_latency_seconds": avg_latency,
            "errors_total": dict(self.errors_total),
        }


class MetricsCollector:
    """Thread-safe metrics collector with per-action breakdown."""
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._lock = threading.Lock()
        self._snapshot = MetricSnapshot()
    
    def record_request(self, action: str, status: str, latency_seconds: float) -> None:
        """Record a request."""
        if not self.enabled:
            return
        key = f"{action}:{status}"
        with self._lock:
            self._snapshot.requests_total[key] += 1
            self._snapshot.latency_sum[key] += latency_seconds
            self._snapshot.latency_count[key] += 1
    
    def record_error(self, action: str, error_code: str) -> None:
        """Record an error."""
        if not self.enabled:
            return
        key = f"{action}:{error_code}"
        with self._lock:
            self._snapshot.errors_total[key] += 1
    
    def get_snapshot(self) -> MetricSnapshot:
        """Get a copy of current metrics."""
        with self._lock:
            # Create a shallow copy
            snap = MetricSnapshot()
            snap.requests_total = self._snapshot.requests_total.copy()
            snap.latency_sum = self._snapshot.latency_sum.copy()
            snap.latency_count = self._snapshot.latency_count.copy()
            snap.errors_total = self._snapshot.errors_total.copy()
            snap.start_time = self._snapshot.start_time
            return snap
    
    def get_metrics_dict(self) -> dict:
        """Get metrics as dictionary for JSON serialization."""
        return self.get_snapshot().to_dict()
    
    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._snapshot = MetricSnapshot()


# 全局指标收集器实例
_global_metrics: Optional[MetricsCollector] = None


def get_metrics(config=None) -> MetricsCollector:
    """Get global metrics collector instance."""
    global _global_metrics
    if _global_metrics is None:
        enabled = config.metrics_enabled if config and hasattr(config, 'metrics_enabled') else False
        _global_metrics = MetricsCollector(enabled=enabled)
    return _global_metrics


def record_metric(action: str, status: str, latency_seconds: float, config=None) -> None:
    """Convenience function to record a metric."""
    get_metrics(config).record_request(action, status, latency_seconds)


def record_error_metric(action: str, error_code: str, config=None) -> None:
    """Convenience function to record an error metric."""
    get_metrics(config).record_error(action, error_code)