"""'처음 한 번만 기본 데이터를 만든다' 코드를 동시에 두 번 돌지 않게 잠근다.

화면이 같은 그룹에 요청을 동시에 보내면 둘 다 "아직 없다"고 보고 기본 항목을 중복으로 만들 수 있다.
한 프로세스 안에서는 스레드 잠금으로, 여러 프로세스(PostgreSQL)에서는 트랜잭션 단위 advisory lock 으로 막는다.
사용법: `with seed_lock(db, "subscriptions:<group>"):` 안에서 다시 한 번 있는지 확인하고 만든다.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

_lock = threading.Lock()


@contextmanager
def seed_lock(db: Session, key: str) -> Iterator[None]:
    with _lock:
        if db.get_bind().dialect.name == "postgresql":
            # 이 트랜잭션이 끝날 때(commit/rollback) 풀린다
            db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": key})
        try:
            yield
        finally:
            db.commit()  # 만든 게 없어도 트랜잭션을 끝내 advisory lock 을 바로 푼다
