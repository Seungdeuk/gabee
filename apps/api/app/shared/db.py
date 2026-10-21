from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
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


def init_db() -> None:
    """개발용: 모델의 테이블을 만든다. 운영 DB 변경은 supabase/migrations 의 SQL 로 한다."""
    from app.features.ai_assistant import models as _ai  # noqa: F401
    from app.features.billing import models as _billing  # noqa: F401
    from app.features.care import models as _care  # noqa: F401
    from app.features.family_chat import models as _chat  # noqa: F401
    from app.features.family_group import models as _group  # noqa: F401
    from app.features.schedule import models as _schedule  # noqa: F401

    Base.metadata.create_all(engine)
