from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    parsed = make_url(url)
    kwargs = {}
    if parsed.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
        if parsed.database and parsed.database != ":memory:":
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, **kwargs)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def import_all_models() -> None:
    """모든 기능의 models 모듈을 불러와 Base.metadata 에 테이블을 등록한다.
    init_db() 와 alembic/env.py 가 함께 쓴다."""
    from app.features.ai_assistant import models as _ai  # noqa: F401
    from app.features.billing import models as _billing  # noqa: F401
    from app.features.care import models as _care  # noqa: F401
    from app.features.family_chat import models as _chat  # noqa: F401
    from app.features.family_group import models as _group  # noqa: F401
    from app.features.schedule import models as _schedule  # noqa: F401


def _current_alembic_head() -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    api_root = Path(__file__).resolve().parents[2]
    cfg = Config()
    cfg.set_main_option("script_location", str(api_root / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def _check_postgres_migrations() -> None:
    """PostgreSQL 스키마는 Alembic 이 전담한다. 서버는 테이블을 만들지 않고
    마이그레이션이 최신인지만 확인한다(자동으로 고치지 않음)."""
    head = _current_alembic_head()
    try:
        with engine.connect() as conn:
            current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except ProgrammingError:
        current = None

    if current != head:
        safe_url = engine.url.render_as_string(hide_password=True)
        raise RuntimeError(
            f"DB 마이그레이션이 최신이 아닙니다 ({safe_url}, 현재: {current}, 최신: {head}). "
            "`alembic upgrade head` 를 먼저 실행하세요."
        )


def init_db() -> None:
    """SQLite(테스트): 모델 테이블을 바로 만든다.
    PostgreSQL: 테이블은 Alembic 이 관리하므로 마이그레이션이 적용됐는지만 확인한다."""
    import_all_models()
    try:
        if engine.dialect.name == "sqlite":
            Base.metadata.create_all(engine)
        else:
            _check_postgres_migrations()
    except OperationalError as exc:
        safe_url = engine.url.render_as_string(hide_password=True)
        raise RuntimeError(f"데이터베이스 연결에 실패했습니다 ({safe_url}): {exc}") from exc
