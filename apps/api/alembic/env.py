from logging.config import fileConfig

from alembic import context
from app.shared.db import Base, engine, import_all_models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

import_all_models()
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """URL만으로 SQL 을 생성한다(DB 연결 없이)."""
    context.configure(
        url=engine.url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """app.shared.db.engine 을 그대로 재사용한다(DATABASE_URL, SQLite 처리 로직 포함)."""
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
