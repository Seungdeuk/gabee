"""프로세스 메모리 기반 실패 횟수 제한(슬라이딩 윈도). Redis 같은 별도 인프라 없이 쓰는 최소 구현이다.

한계: 재시작하면 초기화되고, 워커 프로세스가 여러 개면 프로세스별로 센다. 그래서 정확한 한도가 아니라
무차별 대입을 늦추는 용도다. 공유 저장소가 필요해지면 DB 테이블로 바꾼다(auth.py 가 이 클래스만 쓰므로 교체가 쉽다).
"""

import threading
import time
from collections import defaultdict, deque


class FailureLimiter:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, window: float) -> deque[float]:
        events = self._failures[key]
        cutoff = self._clock() - window
        while events and events[0] <= cutoff:
            events.popleft()
        if not events:
            self._failures.pop(key, None)
        return events

    def retry_after(self, key: str, limit: int, window: float) -> int:
        """한도에 걸렸으면 다시 시도할 수 있기까지 남은 초(1 이상), 아니면 0."""
        with self._lock:
            events = self._prune(key, window)
            if len(events) < limit:
                return 0
            return max(1, int(events[len(events) - limit] + window - self._clock()) + 1)

    def record(self, key: str) -> None:
        with self._lock:
            self._failures[key].append(self._clock())

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
