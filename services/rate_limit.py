"""Скользящее окно в памяти процесса. Для одного инстанса бота этого достаточно;
при горизонтальном масштабировании заменить на Redis."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, clock=time.monotonic) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def hit(self, key: int) -> bool:
        """True — действие разрешено (и засчитано), False — лимит исчерпан."""
        now = self._clock()
        q = self._hits[key]
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True

    def retry_after(self, key: int) -> int:
        q = self._hits.get(key)
        if not q:
            return 0
        return max(0, int(self.window - (self._clock() - q[0])) + 1)
