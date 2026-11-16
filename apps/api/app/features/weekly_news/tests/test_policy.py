"""주간 가족 뉴스 개인정보·탈퇴 정책 시험(2026-11-11 사용자 결정).

① 의료·금융·법률·신분 같은 민감한 주제의 일정·할 일·문서 제목은 개인정보 탐지(NER)와 상관없이 재료에서 미리 뺀다.
② 문서는 종류 라벨·날짜만 재료로 쓴다(제목은 보내지 않는다 — `test_sources`).
③ 가족을 나가면 본인 뉴스 줄이 같은 트랜잭션에서 지워진다.
"""

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.features.weekly_news.models import MemberWeeklyNews
from app.shared import weekly_sources
from app.shared.db import SessionLocal
from app.shared.weekly_sources import SourceRecord
from tests.helpers import join_family

LEAVE_FAMILY = "/family-group/groups/me/leave"
URL = "/report/news"
LAST_MON = date(2026, 11, 2)


# ── 민감 주제 사전 제외 ───────────────────────────────────────


@pytest.fixture
def providers(monkeypatch):
    monkeypatch.setattr(weekly_sources, "_providers", {})
    monkeypatch.setattr(
        weekly_sources.monitor,
        "status",
        lambda *a, **k: SimpleNamespace(feature_ready=lambda f: True),
    )

    def put(records):
        weekly_sources.register_provider("schedule", "schedule", lambda *a: list(records))
        weekly_sources.register_provider("documents", "documents", lambda *a: [])

    return put


def _rec(kind, title, ref=None):
    return SourceRecord(kind, ref or title, title, date(2026, 11, 3), None)


def _collect():
    with SessionLocal() as db:
        return weekly_sources.collect(db, "g", "u", date(2026, 11, 2), date(2026, 11, 8))


SENSITIVE = [
    "항암 치료 일정",
    "이혼 상담 변호사 약속",
    "신한은행 대출 상담",
    "엄마 병원 진료",
    "박서연 소아과 예약",
    "치과 예약",
    "주민등록등본 떼기",
    "진단서",
    "건강검진 결과 확인",
    "약국에서 처방약 받기",
    "정신과 상담",
    "보험금 청구",
    "소송 서류 제출",
    "통장 개설",
]
NEUTRAL = ["학교 공연", "장보기", "분리수거", "할머니 댁 방문", "가정통신문", "생일 파티"]


@pytest.mark.parametrize("title", SENSITIVE)
@pytest.mark.parametrize("kind", ["event", "todo", "document"])
def test_sensitive_topic_titles_are_excluded_for_every_kind(providers, title, kind):
    providers([_rec(kind, title), _rec(kind, "학교 공연", ref="keep")])
    got = _collect()
    assert [r.title for r in got.records] == ["학교 공연"], (kind, title)
    assert got.excluded == 1


@pytest.mark.parametrize("title", NEUTRAL)
def test_neutral_titles_are_kept(providers, title):
    providers([_rec("event", title)])
    got = _collect()
    assert [r.title for r in got.records] == [title] and got.excluded == 0


def test_matching_ignores_spaces_case_and_width(providers):
    providers(
        [
            _rec("event", "항 암 치료"),
            _rec("event", "ｍｒｉ 촬영"),
            _rec("event", "병\u200b원 가기"),
            _rec("event", "학교 공연", ref="keep"),
        ]
    )
    assert [r.title for r in _collect().records] == ["학교 공연"]


def test_excluded_count_never_carries_titles(providers):
    providers([_rec("event", "항암 치료 일정")])
    got = _collect()
    assert got.excluded == 1 and "항암" not in repr(got)


def test_sensitive_filter_runs_before_truncation(providers):
    # 민감한 기록이 상한(약속 30)을 차지해 멀쩡한 기록을 밀어내면 안 된다
    many = [_rec("event", f"병원 {i}", ref=f"s{i}") for i in range(40)]
    providers([*many, _rec("event", "학교 공연", ref="keep")])
    got = _collect()
    assert [r.title for r in got.records] == ["학교 공연"] and not got.truncated


# ── 탈퇴 시 본인 뉴스 삭제 ──────────────────────────────────────


def _ids(client, headers) -> tuple[str, str]:
    me = client.get("/family-group/me", headers=headers).json()
    return me["id"], me["active_group_id"]


def _save(user_id, group_id, week=LAST_MON):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        db.add(
            MemberWeeklyNews(
                id=uuid.uuid4().hex,
                group_id=group_id,
                user_id=user_id,
                week_start=week,
                status="ok",
                body={"title": "t", "items": []},
                sources=[],
                model="m",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()


def _rows():
    with SessionLocal() as db:
        return list(db.scalars(select(MemberWeeklyNews)))


def test_leaving_deletes_my_news_and_keeps_the_others(client, family):
    a, b, _ = family
    ua, gid = _ids(client, a)
    ub, _ = _ids(client, b)
    _save(ua, gid)
    _save(ub, gid)
    _save(ub, gid, week=date(2026, 10, 26))
    assert client.post(LEAVE_FAMILY, headers=b).status_code == 204
    assert [(r.user_id, r.group_id) for r in _rows()] == [(ua, gid)]


def test_after_leaving_the_old_news_is_unreachable_and_not_back_after_rejoin(client, family):
    a, b, group = family
    ub, gid = _ids(client, b)
    _save(ub, gid)
    client.post(LEAVE_FAMILY, headers=b)
    r = client.get(URL, params={"week_start": LAST_MON.isoformat()}, headers=b)
    assert r.status_code == 400 and r.json()["code"] == "no_group"  # 즉시 접근 불가
    join_family(client, a, group["invite_code"], b)  # 같은 가족에 다시 가입해도
    r = client.get(URL, params={"week_start": LAST_MON.isoformat()}, headers=b)
    assert r.status_code == 200 and r.json()["status"] in ("not_generated", "too_early")
    assert r.json()["items"] == []


def test_leaving_keeps_news_of_other_groups_the_user_belongs_to_no_more(client, family):
    # 다른 가족의 같은 사람 줄(group_id 가 다름)은 이번 가족을 나갈 때 건드리지 않는다
    a, b, _ = family
    ub, gid = _ids(client, b)
    other_group = "other-group-id"
    with SessionLocal() as db:
        from app.features.family_group.models import Group

        db.add(Group(id=other_group, name="다른 가족", owner_id=ub))
        db.commit()
    _save(ub, other_group)
    _save(ub, gid)
    client.post(LEAVE_FAMILY, headers=b)
    assert [(r.user_id, r.group_id) for r in _rows()] == [(ub, other_group)]


def test_leaving_still_works_when_the_news_table_is_not_ready(client, family, monkeypatch):
    a, b, _ = family
    monkeypatch.setattr(
        weekly_sources.monitor,
        "status",
        lambda *a, **k: SimpleNamespace(feature_ready=lambda f: f != "weekly_news"),
    )
    from app.features.weekly_news import service

    monkeypatch.setattr(service.monitor, "status", weekly_sources.monitor.status)
    assert client.post(LEAVE_FAMILY, headers=b).status_code == 204


@pytest.mark.parametrize(
    "title",
    [
        "이비인후과 예약",
        "정신건강의학과 상담",
        "비뇨기과 진료",
        "신경과 예약",
        "독감 예방주사",
        "백신 맞는 날",
        "응급실 다녀옴",
        "보건소 방문",
        "심리상담",
        "요양원 면회",
        "적금 만기",
        "카드값 납부",
        "월세 이체",
        "경찰서 방문",
        "Dentist appointment",
        "hospital visit",
    ],
)
def test_common_medical_and_money_words_are_excluded_from_materials(title):
    """2026-11-11 결정(의료·금융 주제 사전 제외): 흔한 진료과·금융어가 목록에서 빠지면 제목이 외부 AI 로 나간다."""
    from app.shared.weekly_sources import is_sensitive_topic

    assert is_sensitive_topic(title)
