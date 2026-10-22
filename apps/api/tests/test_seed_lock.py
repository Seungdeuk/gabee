"""seed_lock: 같은 키의 구간은 동시에 하나만 실행된다(처음 한 번만 만드는 기본 데이터의 중복 생성 방지)."""

import threading
import time

from app.shared.db import SessionLocal
from app.shared.seed_lock import seed_lock


def test_critical_sections_never_overlap():
    state = {"active": 0, "peak": 0}
    guard = threading.Lock()

    def work():
        with SessionLocal() as db, seed_lock(db, "group:test"):
            with guard:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.03)  # 잠금이 없으면 다른 스레드가 이 사이에 들어온다
            with guard:
                state["active"] -= 1

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state["peak"] == 1


def test_lock_is_released_after_an_error():
    try:
        with SessionLocal() as db, seed_lock(db, "group:err"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with SessionLocal() as db, seed_lock(db, "group:err"):  # 다시 잡을 수 있어야 한다
        pass
