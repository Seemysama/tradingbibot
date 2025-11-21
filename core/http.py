from __future__ import annotations
import time, random, httpx
from typing import Callable, Any

RETRY_STATUS = {429, 418, 500, 502, 503, 504}

class HttpClient:
    def __init__(self, base_url: str, timeout: float = 15.0, max_retries: int = 5, backoff_base: float = 0.1):
        self.client = httpx.Client(base_url=base_url.rstrip('/'), timeout=timeout)
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    def request(self, method: str, path: str, **kw) -> httpx.Response:
        attempt = 0
        while True:
            try:
                resp = self.client.request(method, path, **kw)
            except httpx.HTTPError as e:
                if attempt >= self.max_retries:
                    raise
                delay = self._delay(attempt)
                time.sleep(delay)
                attempt += 1
                continue
            if resp.status_code in RETRY_STATUS and attempt < self.max_retries:
                delay = self._delay(attempt)
                time.sleep(delay)
                attempt += 1
                continue
            return resp

    def _delay(self, attempt: int) -> float:
        return min(self.backoff_base * (2 ** attempt), 2.0) + random.uniform(0, 0.05)

    def get_json(self, path: str, **kw) -> Any:
        r = self.request("GET", path, **kw)
        r.raise_for_status()
        return r.json()

    def close(self):
        self.client.close()
