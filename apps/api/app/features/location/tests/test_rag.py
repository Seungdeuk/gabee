"""위치 요약 조각: 문장 만들기·적재·검색·권한·삭제 시험. 해시 임베더만 쓰므로 모델 파일 없이 돈다."""

import re
from datetime import datetime

import pytest
from sqlalchemy import select

from app.features.ai_assistant.knowledge.embedding import HashingEmbedder, set_embedder
from app.features.location import rag
from app.features.location.models import LocationChunk
from app.features.location.summary import Span, build_chunks, merge_spans, split_by_day
from app.shared.config import settings
from app.shared.db import SessionLocal

GROUP = "g1"


def _t(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute)


def _spans(person: str = "a", name: str = "수진") -> list[Span]:
    return [
        Span(person, name, _t(9, 0), _t(9, 7), "stay", "집"),
        Span(person, name, _t(9, 7), _t(9, 8), "stay", "집"),  # 이어진 같은 장소: 한 번의 방문
        Span(person, name, _t(9, 8), _t(9, 8, 30), "move", "학교", "집"),
        Span(person, name, _t(9, 8, 30), _t(9, 14), "stay", "학교"),
        Span(person, name, _t(9, 14), _t(10, 2), "paused"),  # 자정을 넘는 일시정지
    ]


@pytest.fixture
def hashing():
    embedder = HashingEmbedder()
    set_embedder(embedder)
    yield embedder
    set_embedder(None)


def test_merge_joins_adjacent_same_place_and_split_cuts_at_midnight():
    merged = merge_spans(_spans())
    assert [(s.kind, s.place) for s in merged] == [
        ("stay", "집"),
        ("move", "학교"),
        ("stay", "학교"),
        ("paused", None),
    ]
    pieces = split_by_day(merged[-1])
    assert [(p.start.day, p.end.hour) for p in pieces] == [(9, 0), (10, 2)]


def test_chunk_texts_have_date_weekday_and_no_coordinates():
    drafts = build_chunks(_spans())
    kinds = {d.kind for d in drafts}
    assert kinds == {"span", "move", "day", "place"}
    texts = [d.text for d in drafts]
    assert "수진 | 11-09(월) 00:00~08:00 | 집에서 머묾" in texts
    assert "수진 | 11-09(월) 08:00~08:30 | 집에서 학교(으)로 이동" in texts
    assert any("위치 공유 일시정지" in t and "24:00" in t for t in texts)  # 하루 끝은 24:00 으로
    assert any(t.startswith("수진 | 11-09(월) 하루 | 집 → 학교 → 일시정지") for t in texts)
    assert any("학교 방문 1번" in t for t in texts)
    assert not any(
        re.search(r"\d+\.\d{3,}", t) for t in texts
    )  # 좌표 모양(소수점 아래 세 자리 이상)이 없다


def test_build_is_deterministic():
    assert build_chunks(_spans()) == build_chunks(list(reversed(_spans())))


def _index(db, hashing):
    spans = _spans("a", "수진") + [
        Span("b", "하준", _t(9, 0), _t(9, 8), "stay", "집"),
        Span("b", "하준", _t(9, 8), _t(9, 20), "stay", "병원"),
    ]
    return rag.index_spans(db, GROUP, {"a": "ua", "b": "ub"}, spans, hashing)


def test_index_replaces_previous_chunks(client, hashing):
    with SessionLocal() as db:
        first = _index(db, hashing)
        second = _index(db, hashing)
        db.commit()
        assert first == second
        assert len(list(db.scalars(select(LocationChunk)))) == second


def test_search_only_sees_visible_users_and_other_groups_are_excluded(client, hashing):
    with SessionLocal() as db:
        _index(db, hashing)
        mine = rag.search(db, GROUP, ["ua"], "하준이 병원에 있었어?", 20, hashing)
        assert mine and {c.user_id for c, _ in mine} == {
            "ua"
        }  # 하준을 물어도 권한 밖이면 후보에도 없다
        both = rag.search(db, GROUP, ["ua", "ub"], "하준이 병원에 있었어?", 20, hashing)
        assert "ub" in {c.user_id for c, _ in both}
        assert rag.search(db, GROUP, [], "병원", 5, hashing) == []
        assert rag.search(db, "other-group", ["ua", "ub"], "병원", 5, hashing) == []


def test_search_filters_by_date_kind_and_puts_covering_chunk_first(client, hashing):
    with SessionLocal() as db:
        _index(db, hashing)
        day = (_t(9, 0), _t(10, 0))
        found = rag.search(db, GROUP, ["ua"], "어디 있었어", 20, hashing, date_range=day)
        assert found and all(c.starts_at < day[1] and c.ends_at > day[0] for c, _ in found)
        moves = rag.search(db, GROUP, ["ua"], "어디로 이동", 20, hashing, kinds=("move",))
        assert moves and {c.kind for c, _ in moves} == {"move"}
        at = rag.search(db, GROUP, ["ua"], "어디 있었어", 5, hashing, at=_t(9, 10))
        assert at[0][0].starts_at <= _t(9, 10) < at[0][0].ends_at


def test_withdrawing_consent_deletes_chunks(client, family, hashing, monkeypatch):
    monkeypatch.setattr(settings, "location_enabled", True)
    a, b, _ = family
    uid = client.get("/family-group/me", headers=b).json()["id"]
    assert client.put("/location/consent", json={"consent": True}, headers=b).status_code == 200
    with SessionLocal() as db:
        rag.index_spans(db, GROUP, {"x": uid}, _spans("x"), hashing)
        db.commit()
        assert list(db.scalars(select(LocationChunk).where(LocationChunk.user_id == uid)))
    assert client.put("/location/consent", json={"consent": False}, headers=b).status_code == 200
    with SessionLocal() as db:
        assert not list(db.scalars(select(LocationChunk).where(LocationChunk.user_id == uid)))
