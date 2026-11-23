"""L2 실행 환경: 임시 SQLite 만 쓰게 하고, 사례마다 상태를 비우고, 평가 프로세스 안에서만 설정·시계·네트워크를 바꾼다.

운영 코드는 바꾸지 않는다. 이 모듈의 모든 변경은 `eval_process` 가 열려 있는 동안만이고 끝나면 되돌린다.
- 경계: 허용 폴더(`root`)는 임시 폴더(`tempfile.gettempdir()`) 아래의 하위 폴더여야 한다(개발자 로컬 `./data` 같은 곳을 허용 폴더로 넘기는 실수를
  막는다). 앱이 쓰는 DB(`settings.database_url`·`db.engine`·`SessionLocal` 바인딩·환경변수)와 데이터 폴더·원본 폴더가 모두 그 안의
  SQLite 파일·폴더여야 시작한다. PostgreSQL·다른 폴더·`:memory:`·쿼리가 붙은 주소는 거부한다.
- 상태 초기화(사례·반복마다): 모든 테이블을 지우고 다시 만든다(분석 결과 캐시 `ai_result_cache`, 기억, 일정, 사용 기록이 전부 DB 테이블).
  메모리 상태는 `MEMORY_RESETS`(일정 되묻기 초안 `schedule.agent.ask._pending` 등)를 비우고 앱 전체의 속도 제한기를 모두 비운다. 업로드 폴더도 비운다.
  새 메모리 상태가 생기면 `test_env.py` 의 점검이 알려 준다. 초기화 도중 실패하면 예외로 멈춘다(반쯤 비워진 채 다음 사례로 가지 않는다).
- 설정: AI 하루 한도를 크게 올리고(한 질문이 모델을 최대 4번 부른다) 웹 검색을 끈다. 끝나면 원래 값으로 돌린다.
"""

import importlib
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url

from .clock import REFERENCE_NOW, frozen_clock
from .ids import safe_ids
from .network import block_network

RAISED_LIMIT = 100_000
_LIMIT_FIELD = re.compile(r"ai_.*max_calls_per_(user|group)_per_day")
DATA_SUBDIRS = ("photos", "chat_files", "chat_photos", "profile_photos", "play", "raw")
# 사례 사이에 비울 모듈 수준 메모리 저장소(모듈, 이름). 속도 제한기(FailureLimiter)는 앱 전체를 훑어 따로 비운다.
MEMORY_RESETS = (
    ("app.features.schedule.agent.ask", "_pending"),  # 되물은 일정 초안(10분 유지, 락 필요)
    (
        "app.features.schedule.agent.choice",
        "_pending",
    ),  # 같은 이름이 여럿일 때 어느 쪽인지 되물은 상태(10분 유지)
    ("app.features.ai_assistant.library", "_photo_pending"),
    ("app.features.ai_assistant.library", "_photo_inflight"),
    ("app.features.family_group.social_providers", "_overrides"),
    ("app.features.play.bomb", "_cheer_books"),
    ("app.features.play.bomb_vote", "_books"),
)


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
    if not Path(parsed.database).resolve().is_relative_to(root.resolve()):
        raise UnsafeEnvironment("허용한 평가 폴더 밖의 DB 파일이다")


def check_root(root: Path) -> None:
    """허용 폴더가 임시 폴더 아래의 하위 폴더인지 확인한다."""
    tmp = Path(tempfile.gettempdir()).resolve()
    resolved = root.resolve()
    if resolved == tmp or not resolved.is_relative_to(tmp):
        raise UnsafeEnvironment("허용 폴더는 임시 폴더 아래의 하위 폴더여야 한다")


def _inside(path: str | Path, root: Path) -> bool:
    return Path(path).resolve().is_relative_to(root.resolve())


def check_process_boundary(root: Path) -> None:
    """앱이 실제로 쓰는 DB·데이터 폴더·원본 폴더·환경변수가 모두 `root` 안인지 확인한다."""
    from app.shared import db
    from app.shared.config import settings

    check_root(root)
    check_database_url(settings.database_url, root)
    check_database_url(db.engine.url.render_as_string(hide_password=False), root)
    bind = db.SessionLocal.kw.get("bind")
    if bind is not None:
        check_database_url(bind.url.render_as_string(hide_password=False), root)
    if "DATABASE_URL" in os.environ:
        check_database_url(os.environ["DATABASE_URL"], root)
    if not _inside(settings.data_dir, root) or (
        settings.raw_dir and not _inside(settings.raw_dir, root)
    ):
        raise UnsafeEnvironment("데이터 폴더나 원본 폴더가 허용한 평가 폴더 밖이다")


def count_rows(engine: Engine) -> dict[str, int]:
    from app.shared.db import Base

    with engine.connect() as conn:
        return {
            t.name: conn.execute(text(f'SELECT COUNT(*) FROM "{t.name}"')).scalar_one()
            for t in Base.metadata.sorted_tables
        }


def _limiters() -> list:
    from app.shared.rate_limit import FailureLimiter

    found = []
    for name, module in list(sys.modules.items()):
        if name.startswith("app.") and module is not None:
            found += [v for v in vars(module).values() if isinstance(v, FailureLimiter)]
    return found


def reset_memory_state() -> None:
    """모듈 수준 메모리 저장소와 속도 제한기를 모두 비운다."""
    for module_name, attr in MEMORY_RESETS:
        module = importlib.import_module(module_name)
        container = getattr(module, attr)
        lock = getattr(module, f"{attr}_lock", None)
        if lock is not None:
            with lock:
                container.clear()
        else:
            container.clear()
    for limiter in _limiters():
        limiter.reset()


def reset_data_files(root: Path) -> None:
    """데이터 폴더 아래 업로드 폴더를 비운다(모델 폴더·DB 파일은 건드리지 않는다)."""
    from app.shared.config import settings

    for sub in DATA_SUBDIRS:
        folder = Path(settings.data_dir) / sub
        if _inside(folder, root) and folder.is_dir():
            shutil.rmtree(folder)
    if settings.raw_dir and _inside(settings.raw_dir, root):
        shutil.rmtree(settings.raw_dir, ignore_errors=True)


def reset_case_state(root: Path, engine: Engine | None = None) -> None:
    """사례(반복)를 시작하기 전에 메모리·파일·DB 의 모든 상태를 비운다."""
    from app.shared import db

    check_process_boundary(root)
    engine = engine or db.engine
    check_database_url(engine.url.render_as_string(hide_password=False), root)
    reset_memory_state()
    reset_data_files(root)
    db.import_all_models()
    db.Base.metadata.drop_all(engine)
    db.Base.metadata.create_all(engine)


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
    with eval_settings(), block_network(allow_hosts), frozen_clock(now), safe_ids():
        yield
