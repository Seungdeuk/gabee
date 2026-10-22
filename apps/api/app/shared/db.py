from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
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
    else:
        # DB 가 응답하지 않을 때 요청이 오래 붙잡히지 않게 하고, 재시작·배포로 끊긴 연결은 자동으로 버린다
        kwargs["connect_args"] = {"connect_timeout": 5}
        kwargs["pool_pre_ping"] = True
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
    from app.shared import location_consent as _consent  # noqa: F401


def _script_directory():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    api_root = Path(__file__).resolve().parents[2]
    cfg = Config()
    cfg.set_main_option("script_location", str(api_root / "alembic"))
    return ScriptDirectory.from_config(cfg)


def init_db() -> None:
    """SQLite(테스트·로컬): 모델 테이블을 바로 만든다.
    PostgreSQL: 테이블은 Alembic 이 관리한다. DB 가 코드보다 뒤처졌거나 연결에 실패해도 서버는 시작하고,
    스키마가 준비되지 않은 기능의 API 만 503 을 돌려준다(shared/schema.py, schema_gate.py)."""
    import_all_models()
    if engine.dialect.name == "sqlite":
        try:
            Base.metadata.create_all(engine)
        except OperationalError as exc:
            safe_url = engine.url.render_as_string(hide_password=True)
            raise RuntimeError(f"데이터베이스 초기화에 실패했습니다 ({safe_url}): {exc}") from exc
    from .schema import monitor

    monitor.reset()
    monitor.status(force=True)  # 시작 시 상태를 로그에 남긴다(실패해도 시작은 계속)
