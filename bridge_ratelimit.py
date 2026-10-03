"""Token bucket rate limiter for ACE Bridge."""
from __future__ import annotations
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional
from collections import defaultdict


@dataclass
class TokenBucket:
    """Thread-safe token bucket for rate limiting."""
    capacity: int
    refill_rate: float  # tokens per second
    tokens: float = field(init=False)
    last_refill: float = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    
    def __post_init__(self):
        self.tokens = float(self.capacity)
        self.last_refill = time.monotonic()
    
    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if successful."""
        with self._lock:
            now = time.monotonic()
            # Refill tokens based on elapsed time
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    def get_available(self) -> float:
        """Get current available tokens (without consuming)."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            return min(self.capacity, self.tokens + elapsed * self.refill_rate)


class RateLimiter:
    """Multi-tenant rate limiter with per-key token buckets."""
    
    def __init__(self, default_capacity: int = 20, default_refill_rate: float = 10.0, enabled: bool = True):
        self.default_capacity = default_capacity
        self.default_refill_rate = default_refill_rate
        self.enabled = enabled
        self._buckets: Dict[str, TokenBucket] = {}
        self._lock = threading.Lock()
        # 配置覆盖
        self._overrides: Dict[str, tuple[int, float]] = {}  # key -> (capacity, refill_rate)
    
    def set_limit(self, key: str, capacity: int, refill_rate: float) -> None:
        """Set custom limit for a specific key."""
        with self._lock:
            self._overrides[key] = (capacity, refill_rate)
            if key in self._buckets:
                del self._buckets[key]  # Force recreation with new params
    
    def _get_bucket(self, key: str) -> TokenBucket:
        """Get or create bucket for key."""
        if key not in self._buckets:
            with self._lock:
                if key not in self._buckets:  # Double-check
                    capacity, refill_rate = self._overrides.get(key, (self.default_capacity, self.default_refill_rate))
                    self._buckets[key] = TokenBucket(capacity, refill_rate)
        return self._buckets[key]
    
    def check_limit(self, key: str, tokens: int = 1) -> tuple[bool, dict]:
        """
        Check if request is allowed.
        Returns: (allowed, info_dict)
        info_dict contains: allowed, remaining, retry_after_seconds, limit, refill_rate
        """
        if not self.enabled:
            return True, {"allowed": True, "remaining": float('inf'), "retry_after": 0, "limit": self.default_capacity, "refill_rate": self.default_refill_rate}
        
        bucket = self._get_bucket(key)
        allowed = bucket.consume(tokens)
        remaining = bucket.get_available()
        
        info = {
            "allowed": allowed,
            "remaining": remaining,
            "retry_after": 0 if allowed else (tokens - remaining) / bucket.refill_rate if bucket.refill_rate > 0 else 60,
            "limit": bucket.capacity,
            "refill_rate": bucket.refill_rate,
        }
        return allowed, info
    
    def get_status(self, key: str) -> dict:
        """Get current status without consuming tokens."""
        if not self.enabled:
            return {"allowed": True, "remaining": float('inf'), "limit": self.default_capacity, "refill_rate": self.default_refill_rate}
        bucket = self._get_bucket(key)
        return {
            "allowed": True,
            "remaining": bucket.get_available(),
            "limit": bucket.capacity,
            "refill_rate": bucket.refill_rate,
        }


# 全局限流器实例
_global_limiter: Optional[RateLimiter] = None


def get_rate_limiter(config=None) -> RateLimiter:
    """Get global rate limiter instance."""
    global _global_limiter
    if _global_limiter is None:
        if config:
            _global_limiter = RateLimiter(
                default_capacity=config.burst_per_host if hasattr(config, 'burst_per_host') else 20,
                default_refill_rate=config.max_rps_per_host if hasattr(config, 'max_rps_per_host') else 10.0,
                enabled=config.enable_rate_limit if hasattr(config, 'enable_rate_limit') else False,
            )
        else:
            _global_limiter = RateLimiter()
    return _global_limiter


def check_rate_limit(host_id: str, action: str, config=None) -> tuple[bool, dict]:
    """Convenience function to check rate limit for host+action."""
    limiter = get_rate_limiter(config)
    key = f"{host_id}:{action}"
    return limiter.check_limit(key)