"""DB 오류가 나도 SQL 파라미터(개인 데이터가 든 값)가 오류 문구·로그에 남지 않는지 확인한다(임시 SQLite)."""

import logging

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, text
from sqlalchemy.exc import IntegrityError

from app.shared.db import _make_engine

SECRET = "010-1234-5678-비밀값"


def _table() -> Table:
    return Table("t", MetaData(), Column("id", Integer, primary_key=True), Column("v", String))


def test_engine_hides_parameters_in_error_text():
    engine = _make_engine("sqlite:///:memory:")
    t = _table()
    t.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(t.insert().values(id=1, v="x"))
    with pytest.raises(IntegrityError) as err:
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, v=SECRET))  # 기본키 중복
    assert SECRET not in str(err.value)
    assert SECRET not in repr(err.value)


def test_engine_hides_parameters_in_logs(caplog):
    engine = _make_engine("sqlite:///:memory:")
    t = _table()
    t.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(t.insert().values(id=1, v="x"))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(t.insert().values(id=1, v=SECRET))
    assert SECRET not in caplog.text


def test_plain_text_query_still_works():
    engine = _make_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        assert conn.execute(text("select :a"), {"a": 1}).scalar() == 1
