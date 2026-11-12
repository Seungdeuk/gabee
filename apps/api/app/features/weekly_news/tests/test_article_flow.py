# ruff: noqa: F811  (test_generate.py 의 픽스처를 가져다 쓴다)
"""기사형 뉴스 생성·읽기(`POST/GET /report/news`) 시험. LLM 은 가짜고 외부 네트워크는 부르지 않는다.

픽스처는 test_generate.py 것을 그대로 쓴다. v1(헤드라인·역할·분류 없는) 저장본도 그대로 읽힌다.
"""

import uuid
from datetime import UTC, date, datetime

import pytest

from app.features.weekly_news import generate
from app.features.weekly_news.models import MemberWeeklyNews
from app.features.weekly_news.week import issue_of, week_start_of
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.weekly_sources import SourceRecord

from .test_generate import (  # noqa: F401  (픽스처)
    LAST_MON,
    THIS_MON,
    URL,
    _env,
    _ids,
    _rename,
    at,
    fake,
    post,
    ready,
    records,
    rows,
)


def v2(items, title="공연과 생일이 있던 주"):
    return {"title": title, "items": items}


def art(text, ids, headline=None):
    item = {"text": text, "source_ids": ids}
    if headline is not None:
        item["headline"] = headline
    return item


# ── 생성: 프롬프트·스키마 ─────────────────────────────────────


def test_prompt_version_and_schema_ask_for_headline_text_and_ids_only(client, ready, fake):
    a, _ = ready
    assert post(client, a).status_code == 200
    props = fake.calls[0]["schema"]["properties"]["items"]["items"]
    assert set(props["required"]) == {"headline", "text", "source_ids"}
    assert set(props["properties"]) == {
        "headline",
        "text",
        "source_ids",
    }  # 역할·분류는 모델이 정하지 않는다
    assert generate.PROMPT_VERSION == "v2"
    system = fake.calls[0]["system"]
    for phrase in ("headline", "가비 기자", "관계", "원인", "결과", "참석", "있었어요"):
        assert phrase in system


# ── 생성: 저장·복원 ───────────────────────────────────────────


def test_articles_are_saved_with_headline_role_category_and_restored_names(client, ready, fake):
    a, _ = ready
    fake.data = v2(
        [
            art("[PERSON_1] 생일 파티가 있었어요", ["e2"], "[PERSON_1] 생일 파티"),
            art("화요일 오후 2시 30분에 학교 공연이 있었어요", ["e1"], "학교 공연 소식"),
        ]
    )
    r = post(client, a)
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"]
    # 근거 수가 같으면 이른 날짜(11/3 공연)가 메인, 나머지는 단신
    assert [i["role"] for i in items] == ["lead", "brief"]
    assert items[0]["headline"] == "학교 공연 소식" and items[0]["category"] == "일정"
    assert items[1]["headline"] == "지민 생일 파티"  # 이름은 기존 복원 경로로 되돌아온다
    assert items[1]["text"] == "지민 생일 파티가 있었어요"
    assert not any("[PERSON" in (i["headline"] or "") + i["text"] for i in items)
    saved = rows()[0]
    assert saved.prompt_version == "v2"
    assert (
        saved.body["items"][0]["role"] == "lead"
        and saved.body["items"][0]["headline"] == "학교 공연 소식"
    )


def test_headline_with_a_bad_token_is_dropped_but_the_article_stays(client, ready, fake):
    a, _ = ready
    fake.data = v2([art("학교 공연이 있었어요", ["e1"], "[PERSON_9] 소식")])
    items = post(client, a).json()["items"]
    assert items[0]["text"] == "학교 공연이 있었어요" and items[0]["headline"] is None


def test_headline_with_a_link_is_dropped_but_the_article_stays(client, ready, fake):
    a, _ = ready
    fake.data = v2([art("학교 공연이 있었어요", ["e1"], "evil.com 공연")])
    items = post(client, a).json()["items"]
    assert items[0]["headline"] is None and len(items) == 1


def test_activity_claims_about_events_never_reach_the_saved_news(client, ready, fake):
    a, _ = ready
    fake.data = v2(
        [
            art("학교 공연을 다녀왔어요", ["e1"], "공연 다녀온 날"),
            art("[PERSON_1] 생일 파티가 잘 마무리되었어요", ["e2"]),
            art("[PERSON_1] 생일 파티가 있었어요", ["e2"], "생일 파티 소식"),
        ]
    )
    body = post(client, a).json()
    assert body["status"] == "ready"
    assert [i["text"] for i in body["items"]] == ["지민 생일 파티가 있었어요"]
    assert {s["id"] for s in body["sources"]} == {"e2"}  # 버려진 기사의 근거는 남지 않는다


def test_only_invalid_articles_make_the_news_fail_like_before(client, ready, fake):
    a, _ = ready
    fake.data = v2([art("학교 공연을 다녀왔어요", ["e1"])])
    assert post(client, a).json()["status"] == "failed"
    assert rows()[0].error_code == "invalid_output"


def test_old_style_output_without_headlines_still_works(client, ready, fake):
    a, _ = ready
    body = post(client, a).json()  # test_generate.good(): headline·role 없는 v1 모양
    assert body["status"] == "ready" and len(body["items"]) == 2
    assert body["items"][0]["role"] == "lead" and body["items"][0]["headline"] is None


def test_quoted_title_with_a_renamed_member_survives_name_restoration(client, ready, fake, records):
    """복원하면 표시 이름('지니')이 들어가 실제 근거 제목('지민 …')과 달라져도, 가명 상태에서 통과한 기사를 복원 뒤에 다시 버리면 안 된다."""
    a, _ = ready
    _rename(client, a, display="지니")
    records.items = [SourceRecord("event", "ev-1", "지민 할머니 댁 방문", date(2026, 11, 3))]
    fake.data = v2(
        [art("[PERSON_1] 할머니 댁 방문이 있었어요", ["e1"], "[PERSON_1] 할머니 댁 방문 소식")]
    )
    body = post(client, a).json()
    assert body["status"] == "ready", body
    assert body["items"][0]["text"] == "지니 할머니 댁 방문이 있었어요"
    assert body["items"][0]["headline"] == "지니 할머니 댁 방문 소식"


# ── 호수: 서버 주 계산과 같다 ─────────────────────────────────


@pytest.fixture(autouse=True)
def _kst(monkeypatch):
    monkeypatch.setattr(settings, "ai_day_utc_offset_hours", 9)


def test_issue_of_is_the_iso_week_of_the_monday():
    assert issue_of(date(2026, 11, 9)) == (2026, 46)
    assert issue_of(date(2026, 12, 28)) == (2026, 53)  # 2026 은 53주까지 있다
    assert issue_of(date(2025, 12, 29)) == (2026, 1)  # 달력은 2025 년이어도 ISO 주는 2026 년 1주
    assert issue_of(date(2027, 1, 4)) == (2027, 1)


def utc(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (
            utc(2026, 11, 15, 8, 59),
            (2026, 46),
        ),  # 일요일 17:59 KST: 아직 만들 수 없지만 호수는 그 주
        (utc(2026, 11, 15, 9, 0), (2026, 46)),  # 일요일 18:00 KST: 만들 수 있게 되는 순간도 같은 호
        (utc(2026, 11, 15, 15, 0), (2026, 47)),  # 월요일 00:00 KST: 새 호
        (utc(2026, 12, 27, 14, 59), (2026, 52)),
        (utc(2026, 12, 27, 15, 0), (2026, 53)),  # 연말 53주
        (utc(2027, 1, 3, 15, 0), (2027, 1)),  # 1월 4일(월) 00:00 KST: 새해 1호
    ],
)
def test_issue_follows_the_server_week_at_the_boundaries(now, expected):
    assert issue_of(week_start_of(now)) == expected


def test_response_carries_the_issue_for_every_status(client, family, at):
    a, _, _ = family
    at(utc(2026, 1, 1, 3, 0))  # 목요일: 이번 주(2025-12-29)는 아직 만들 때가 아니다
    r = client.get(URL, params={"week_start": "2025-12-29"}, headers=a).json()
    assert r["status"] == "too_early" and (r["issue_year"], r["issue_no"]) == (2026, 1)


def test_sunday_1800_generation_reports_that_weeks_issue(client, ready, fake, at):
    a, _ = ready
    at(utc(2026, 11, 15, 9, 0))
    r = post(client, a, THIS_MON)
    assert r.status_code == 200, r.text
    assert (r.json()["issue_year"], r.json()["issue_no"]) == (2026, 46)


# ── v1 저장본은 그대로 읽힌다 ─────────────────────────────────


def test_v1_saved_news_is_read_without_new_fields(client, family, at):
    a, _, _ = family
    uid, gid = _ids(client, a)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        db.add(
            MemberWeeklyNews(
                id=uuid.uuid4().hex,
                group_id=gid,
                user_id=uid,
                week_start=LAST_MON,
                status="ok",
                body={
                    "title": "옛 뉴스",
                    "items": [{"text": "옛 문장이에요", "source_ids": ["e1"]}],
                },
                sources=[
                    {
                        "id": "e1",
                        "kind": "event",
                        "ref": "x",
                        "label": "학교 공연",
                        "date": "2026-11-03",
                    }
                ],
                model="old",
                prompt_version="v1",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    r = client.get(URL, params={"week_start": LAST_MON.isoformat()}, headers=a)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready" and body["title"] == "옛 뉴스"
    item = body["items"][0]
    assert item == {
        "text": "옛 문장이에요",
        "source_ids": ["e1"],
        "headline": None,
        "role": None,
        "category": None,
    }
    assert (body["issue_year"], body["issue_no"]) == (2026, 45)
