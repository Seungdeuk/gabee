from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
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


def _ensure_pgvector_extension() -> None:
    """개발용 PostgreSQL 에 pgvector 확장을 켠다. SQLite 에는 해당 없음."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


def init_db() -> None:
    """개발용: 모델의 테이블을 만든다. 운영 DB 변경은 supabase/migrations 의 SQL 로 한다."""
    from app.features.ai_assistant import models as _ai  # noqa: F401
    from app.features.billing import models as _billing  # noqa: F401
    from app.features.care import models as _care  # noqa: F401
    from app.features.family_chat import models as _chat  # noqa: F401
    from app.features.family_group import models as _group  # noqa: F401
    from app.features.schedule import models as _schedule  # noqa: F401

    try:
        _ensure_pgvector_extension()
        Base.metadata.create_all(engine)
    except OperationalError as exc:
        safe_url = engine.url.render_as_string(hide_password=True)
        raise RuntimeError(f"데이터베이스 연결에 실패했습니다 ({safe_url}): {exc}") from exc
