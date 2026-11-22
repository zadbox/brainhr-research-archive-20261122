from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class InMemoryRateLimiter:
    _events: dict[str, deque[float]] = defaultdict(deque)
    _lock = Lock()

    @classmethod
    def consume(
        cls,
        *,
        bucket: str,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        normalized_key = f"{bucket}:{key}"
        now = monotonic()
        with cls._lock:
            queue = cls._events[normalized_key]
            threshold = now - max(window_seconds, 1)
            while queue and queue[0] <= threshold:
                queue.popleft()

            if len(queue) >= max(limit, 1):
                retry_after = int(max(1, window_seconds - (now - queue[0])))
                return False, retry_after

            queue.append(now)
            return True, 0

    @classmethod
    def reset(cls, *, bucket: str, key: str) -> None:
        normalized_key = f"{bucket}:{key}"
        with cls._lock:
            cls._events.pop(normalized_key, None)
