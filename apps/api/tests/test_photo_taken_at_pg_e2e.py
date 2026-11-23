"""사진 촬영일 칸(message_attachments.taken_at, 리비전 4c1f8a62b7d9)의 마이그레이션을 PostgreSQL 16 에서 검증한다.

이전 head(8b4e2a71c9d3)에서 기존 사진 행을 만들어 두고 head 로 올렸을 때 칸이 nullable 로 생기고 기존 행은 NULL 로 남는지,
timestamptz 로 값이 왕복하는지, 모델과 스키마가 일치하는지(check_schema_matches_models), head 가 하나인지, 내리면 칸만 사라지는지 본다.
Docker 가 필요하므로 GABEE_PG16_E2E=1 일 때만 실행한다. 이 시험이 띄운 임시 컨테이너만 쓰며 공용 DB·개인 DB·MVP DB 에는 접속하지 않는다.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime

import pytest

from tests.test_schema_gate_pg_e2e import (  # noqa: F401
    API_ROOT,
    admin,
    create_db,
    migrate,
    pg16,
    seed,
    url,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("GABEE_PG16_E2E") != "1", reason="GABEE_PG16_E2E=1 일 때만 실행(Docker 필요)"
)

PREVIOUS_HEAD = "8b4e2a71c9d3"
THIS_REVISION = "4c1f8a62b7d9"
FILL = {
    "character varying": "x",
    "text": "x",
    "integer": 1,
    "bigint": 1,
    "boolean": False,
    "timestamp with time zone": datetime(2026, 1, 1, tzinfo=UTC),
    "date": datetime(2026, 1, 1).date(),
    "json": "{}",
    "jsonb": "{}",
}


def _alembic(pg, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG") and k != "DATABASE_URL"}
    env["DATABASE_URL"] = url(pg)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _insert(conn, table: str, **values):
    """NOT NULL 이고 기본값 없는 칸은 형식에 맞는 자리 값으로 채워 한 줄을 넣고 id 를 돌려준다(이 시험은 taken_at 만 본다)."""
    row = dict(values)
    for name, dtype, nullable, default in conn.execute(
        "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns"
        " WHERE table_name = %s AND table_schema = 'public'",
        (table,),
    ).fetchall():
        if name in row or nullable == "YES" or default is not None:
            continue
        row[name] = FILL.get(dtype, "x")
    columns = ", ".join(row)
    marks = ", ".join(["%s"] * len(row))
    return conn.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({marks}) RETURNING id", tuple(row.values())
    ).fetchone()[0]


def _column(pg):
    with admin(pg) as c:
        return c.execute(
            "SELECT data_type, is_nullable FROM information_schema.columns"
            " WHERE table_name = 'message_attachments' AND column_name = 'taken_at'"
            " AND table_schema = 'public'"
        ).fetchone()


def _old_photo(pg):
    seed(pg)
    with admin(pg) as c:
        _insert(c, "chat_rooms", id="r1", group_id="g1", kind="family")
        message_id = _insert(c, "messages", group_id="g1", room_id="r1", user_id="u1", text="")
        _insert(
            c,
            "message_attachments",
            id="a1",
            message_id=message_id,
            group_id="g1",
            room_id="r1",
            kind="image",
            path="chat_photos/a1.jpg",
            size_bytes=1,
        )


def test_taken_at_is_added_as_nullable_timestamptz_and_old_rows_stay_null(pg16):  # noqa: F811
    create_db(pg16)
    migrate(pg16, PREVIOUS_HEAD)
    assert _column(pg16) is None  # 이전 head 에는 칸이 없다
    _old_photo(pg16)

    migrate(pg16, "head")
    assert _column(pg16) == ("timestamp with time zone", "YES")
    with admin(pg16) as c:
        assert c.execute(
            "SELECT count(*), count(taken_at) FROM message_attachments"
        ).fetchone() == (1, 0)  # 기존 사진은 그대로 있고 촬영 시각은 NULL(보낸 날 기준)
        c.execute(
            "UPDATE message_attachments SET taken_at = %s WHERE id = 'a1'",
            (datetime(2024, 10, 5, 5, 30, tzinfo=UTC),),
        )
        assert c.execute("SELECT taken_at FROM message_attachments").fetchone()[0] == datetime(
            2024, 10, 5, 5, 30, tzinfo=UTC
        )


def test_there_is_a_single_head_and_the_schema_matches_the_models(pg16):  # noqa: F811
    """이 리비전 뒤에 새 리비전이 생겨도 깨지지 않는다: head 가 하나인지와 최신 스키마가 모델과 같은지만 본다."""
    create_db(pg16)
    migrate(pg16, "head")
    heads = _alembic(pg16, "heads")
    assert heads.returncode == 0, heads.stderr[-300:]
    assert len([line for line in heads.stdout.splitlines() if "(head)" in line]) == 1
    history = _alembic(pg16, "history")
    assert history.returncode == 0 and THIS_REVISION in history.stdout  # 이 리비전이 이력에 있다
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG") and k != "DATABASE_URL"}
    env["DATABASE_URL"] = url(pg16)
    env["PYTHONIOENCODING"] = "utf-8"
    check = subprocess.run(
        [sys.executable, "scripts/check_schema_matches_models.py"],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert check.returncode == 0, (check.stdout + check.stderr)[-800:]


def test_downgrade_drops_only_the_column_and_upgrade_works_again(pg16):  # noqa: F811
    create_db(pg16)
    migrate(pg16, PREVIOUS_HEAD)
    _old_photo(pg16)
    migrate(
        pg16, THIS_REVISION
    )  # 리비전을 직접 지정한다(뒤에 새 리비전이 생겨도 이 시험은 같은 구간만 본다)
    down = _alembic(pg16, "downgrade", PREVIOUS_HEAD)
    assert down.returncode == 0, down.stderr[-300:]
    assert _column(pg16) is None
    with admin(pg16) as c:  # 사진 행과 다른 데이터는 그대로다
        assert c.execute("SELECT count(*) FROM message_attachments").fetchone()[0] == 1
    migrate(pg16, THIS_REVISION)  # 다시 올려도 된다
    assert _column(pg16) == ("timestamp with time zone", "YES")
