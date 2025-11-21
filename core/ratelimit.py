from __future__ import annotations
"""In-memory token bucket rate limiter (per key).

Usage:
    limiter = RateLimiter(capacity=10, refill_rate=5)  # 10 tokens max, 5 tokens/sec
    if limiter.allow():
        ...

Thread-safety: simplified (single-threaded async event loop expected).
"""
import time
from dataclasses import dataclass

@dataclass
class Bucket:
    capacity: int
    tokens: float
    refill_rate: float  # tokens per second
    last: float

class RateLimiter:
    def __init__(self, capacity: int, refill_rate: float):
        self.bucket = Bucket(capacity=capacity, tokens=capacity, refill_rate=refill_rate, last=time.time())

    def _refill(self) -> None:
        now = time.time()
        delta = now - self.bucket.last
        if delta <= 0:
            return
        self.bucket.tokens = min(self.bucket.capacity, self.bucket.tokens + delta * self.bucket.refill_rate)
        self.bucket.last = now

    def allow(self, cost: float = 1.0) -> bool:
        self._refill()
        if self.bucket.tokens >= cost:
            self.bucket.tokens -= cost
            return True
        return False

__all__ = ["RateLimiter"]