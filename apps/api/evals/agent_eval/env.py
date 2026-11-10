"""L2 실행 환경: 임시 SQLite 만 쓰게 하고, 사례마다 상태를 비우고, 평가 프로세스 안에서만 설정·시계·네트워크를 바꾼다.

운영 코드는 바꾸지 않는다. 이 모듈의 모든 변경은 `eval_process` 가 열려 있는 동안만이고 끝나면 되돌린다.
- DB 경계: 앱이 쓰는 DB(`settings.database_url`·`db.engine`·환경변수)와 데이터 폴더가 모두 `root` 아래의 SQLite 파일이어야
  시작한다. PostgreSQL·다른 폴더·`:memory:`·쿼리가 붙은 주소는 거부한다.
- 상태 초기화: 사례·반복마다 모든 테이블을 지우고 다시 만든다(분석 결과 캐시 `ai_result_cache`, 기억 `assistant_memories`,
  일정, 사용 기록이 전부 DB 테이블). 일정 되묻기 초안은 서버 프로세스 메모리(`schedule.agent.ask._pending`)에 있으니 그것도
  비운다. 메모리의 속도 제한기도 비운다. 새 메모리 상태가 생기면 `test_env.py` 의 점검이 알려 준다.
- 설정: AI 하루 한도를 크게 올리고(한 질문이 모델을 최대 4번 부른다) 웹 검색을 끈다. 끝나면 원래 값으로 돌린다.
"""

import os
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url

from .clock import REFERENCE_NOW, frozen_clock
from .network import block_network

RAISED_LIMIT = 100_000
_LIMIT_FIELD = re.compile(r"ai_.*max_calls_per_(user|group)_per_day")


class UnsafeEnvironment(RuntimeError):
    """평가가 쓰면 안 되는 DB·폴더를 가리키고 있다."""


def check_database_url(url: str, root: Path) -> None:
    """`root` 아래의 SQLite 파일이 아니면 `UnsafeEnvironment`."""
    try:
        parsed = make_url(url)
    except Exception as e:  # noqa: BLE001
        raise UnsafeEnvironment("DB 주소를 해석할 수 없다") from e
    if parsed.get_backend_name() != "sqlite":
        raise UnsafeEnvironment(
            f"SQLite 가 아닌 DB 는 평가에 쓰지 않는다: {parsed.get_backend_name()}"
        )
    if parsed.query or not parsed.database or parsed.database == ":memory:":
        raise UnsafeEnvironment("파일 SQLite 주소(쿼리 없음)만 허용한다")
    path = Path(parsed.database).resolve()
    if not path.is_relative_to(root.resolve()):
        raise UnsafeEnvironment("허용한 평가 폴더 밖의 DB 파일이다")


def check_process_boundary(root: Path) -> None:
    """앱이 실제로 쓰는 DB·데이터 폴더·환경변수가 모두 `root` 안인지 확인한다."""
    from app.shared import db
    from app.shared.config import settings

    check_database_url(settings.database_url, root)
    check_database_url(db.engine.url.render_as_string(hide_password=False), root)
    if "DATABASE_URL" in os.environ:
        check_database_url(os.environ["DATABASE_URL"], root)
    if not Path(settings.data_dir).resolve().is_relative_to(root.resolve()):
        raise UnsafeEnvironment("데이터 폴더가 허용한 평가 폴더 밖이다")


def count_rows(engine: Engine) -> dict[str, int]:
    from app.shared.db import Base

    with engine.connect() as conn:
        return {
            t.name: conn.execute(text(f'SELECT COUNT(*) FROM "{t.name}"')).scalar_one()
            for t in Base.metadata.sorted_tables
        }


def reset_case_state(root: Path, engine: Engine | None = None) -> None:
    """사례(반복)를 시작하기 전에 DB 의 모든 테이블을 지우고 다시 만들고, 메모리 상태를 비운다."""
    from app.shared import db

    check_process_boundary(root)
    engine = engine or db.engine
    check_database_url(engine.url.render_as_string(hide_password=False), root)
    db.import_all_models()
    db.Base.metadata.drop_all(engine)
    db.Base.metadata.create_all(engine)
    from app.features.family_group.service import login_limiter, mail_limiter
    from app.features.schedule.agent import ask
    from app.shared import mailer

    login_limiter.reset()
    mail_limiter.reset()
    mailer.set_mailer(None)
    with ask._pending_lock:
        ask._pending.clear()  # 앞 사례에서 되물어 둔 일정 초안


@contextmanager
def eval_settings(extra: Iterable[tuple[str, object]] = ()) -> Iterator[None]:
    """한도를 올리고 웹 검색을 끈다(끝나면 원래 값으로)."""
    from app.shared.config import settings

    changes = {
        name: RAISED_LIMIT for name in type(settings).model_fields if _LIMIT_FIELD.fullmatch(name)
    }
    changes["web_search_enabled"] = False
    changes.update(extra)
    saved = {name: getattr(settings, name) for name in changes}
    for name, value in changes.items():
        setattr(settings, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)


@contextmanager
def eval_process(
    root: Path, allow_hosts: Iterable[str] = (), now: datetime = REFERENCE_NOW
) -> Iterator[None]:
    """경계를 확인한 뒤 설정·네트워크 차단·고정 시계를 켠다. 가짜 모델만 쓰면 allow_hosts 를 비운다."""
    check_process_boundary(root)
    with eval_settings(), block_network(allow_hosts), frozen_clock(now):
        yield
