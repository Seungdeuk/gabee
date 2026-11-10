"""채팅방 공유 카드의 내용이 @가비·AI 도우미(대화 분석·답장·주제)의 대화 맥락에 들어간다.
카드 메시지의 글자(messages.text)는 고정 문구라서, AI 로 읽을 때만 카드 내용을 한 줄 요약으로 바꿔 넣고
(DB 는 그대로), 요약도 일반 메시지와 같은 가명화(이름·전화번호 가리기)를 거쳐 나간다. 실제 Anthropic 은 부르지 않는다."""

# 다른 시험 파일의 fixture(fake·trio)를 가져다 쓰고, 시험 함수 인자로 받는다(pytest 방식이라 F811 은 무시한다)
# ruff: noqa: F811
import json

import pytest
from sqlalchemy import select

from app.features.ai_assistant.knowledge import rag_chat
from app.features.family_chat import ai_repository, ai_service
from app.features.family_chat.models import Message
from app.features.family_chat.share_text import card_names, card_text
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.ai_consent import enable_ai

from .test_ai_analysis import analyze, enable, fake, say  # noqa: F401  (fake 는 fixture)
from .test_chat_share import MSG, _drop_share_table, _event, _settled, _share
from .test_rooms import _direct, _send, _uid, trio  # noqa: F401  (trio 는 fixture)

EVENT_FIXED = "일정을 공유했어요"
SETTLEMENT_FIXED = "정산을 공유했어요"
LEAVE_FAMILY = "/family-group/groups/me/leave"


def _group_id(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["active_group_id"]


def _context(client, headers, room_id=None):
    """@가비 맥락(room_context)이 만든 가명화된 대화. 부른 쪽이 닫아야 하는 대응표는 여기서 닫는다."""
    with SessionLocal() as db:
        ctx = ai_service.room_context(db, _group_id(client, headers), room_id)
        if ctx is None:
            return None
        try:
            return ctx.transcript
        finally:
            ctx.close()


def _event_card(client, headers, room_id=None, title="치과 정기검진", **extra):
    event = _event(client, headers, title=title, place="미소치과", **extra)
    r = _share(client, headers, "event", event["id"], room_id)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def gabee(client, trio, monkeypatch):
    """@가비 호출을 가짜로 받는다: 그 가족의 AI 동의를 켜고, 모델에 간 system 글을 모은 목록을 돌려준다."""
    a, _, _ = trio
    enable_ai(_group_id(client, a))
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    systems = []

    def fake_post(req):
        systems.append(req["system"])
        return {"content": [{"type": "text", "text": "답이에요"}]}

    monkeypatch.setattr(rag_chat, "_post", fake_post)
    return systems


def _ask_gabee(client, headers, **body):
    r = client.post(
        "/ai-assistant/chat",
        json={"message": "방금 일정 알려줘", "audience": "room", **body},
        headers=headers,
    )
    assert r.status_code == 200, r.text


# ---------- card_text 단위 ----------


def test_event_text_has_title_full_date_time_place_and_who():
    payload = {
        "title": "치과 정기검진",
        "date": "2026-11-12",
        "start_time": "10:00",
        "end_time": "11:00",
        "place": "역삼 미소치과",
        "kind": 1,
        "with_names": ["아빠"],
    }
    assert (
        card_text("event", payload)
        == "[일정 공유] 치과 정기검진 · 2026-11-12 10:00~11:00 · 역삼 미소치과 · 함께: 아빠"
    )  # 연도까지 쓴다(내년 일정과 헷갈리지 않게)


def test_event_text_leaves_out_what_is_missing():
    base = {"title": "장보기", "date": None, "start_time": None, "end_time": None}
    assert (
        card_text("event", {**base, "place": "", "with_names": []})
        == "[일정 공유] 장보기 · 날짜 미정"
    )
    only_start = {**base, "date": "2026-11-12", "start_time": "09:30"}
    assert card_text("event", only_start) == "[일정 공유] 장보기 · 2026-11-12 09:30"
    only_day = {**base, "date": "2026-11-12", "with_names": ["엄마", "아빠"]}
    assert card_text("event", only_day) == "[일정 공유] 장보기 · 2026-11-12 · 함께: 엄마, 아빠"


def test_todo_kind_is_called_a_todo():
    payload = {"title": "택배 받기", "date": None, "kind": 2}
    assert card_text("event", payload).startswith("[할 일 공유] 택배 받기")


def test_settlement_text_is_from_the_sharers_point_of_view_with_commas():
    """돈의 방향은 카드를 올린 사람 기준이다(요청한 사람 입장으로 읽다가 거꾸로 이해하지 않게 주어를 붙인다)."""
    payload = {
        "month": "2026-11",
        "remaining": 1333,
        "lines": [
            {"direction": "send", "name": "아빠", "amount": 667},
            {"direction": "receive", "name": "하늘", "amount": 2000},
        ],
    }
    assert card_text("settlement", payload) == (
        "[정산 공유 2026-11] 공유한 사람이 받을 돈 1,333원"
        " · 아빠에게 667원 보낼 돈 · 하늘에게서 2,000원 받을 돈"
    )


def test_settlement_text_for_money_to_send_zero_and_no_lines():
    owe = {"month": "2026-11", "remaining": -667, "lines": []}
    assert card_text("settlement", owe) == "[정산 공유 2026-11] 공유한 사람이 보낼 돈 667원"
    zero = {"month": "2026-11", "remaining": 0, "lines": []}
    assert card_text("settlement", zero) == "[정산 공유 2026-11] 공유한 사람은 정산할 돈 없음"
    no_lines = {"month": "2026-11", "remaining": 1234567}
    assert (
        card_text("settlement", no_lines) == "[정산 공유 2026-11] 공유한 사람이 받을 돈 1,234,567원"
    )


@pytest.mark.parametrize(
    ("kind", "payload", "fixed"),
    [
        ("event", None, EVENT_FIXED),
        ("event", "문자열", EVENT_FIXED),
        ("event", {}, EVENT_FIXED),
        ("event", {"title": 123}, EVENT_FIXED),
        ("event", {"title": "  "}, EVENT_FIXED),
        ("settlement", None, SETTLEMENT_FIXED),
        ("settlement", {}, SETTLEMENT_FIXED),
        ("settlement", {"month": "2026-11", "remaining": "많이"}, SETTLEMENT_FIXED),
        ("settlement", {"month": "2026-11", "remaining": True}, SETTLEMENT_FIXED),
        ("unknown", {"title": "x"}, "공유했어요"),
    ],
)
def test_broken_payload_or_unknown_kind_falls_back_to_a_fixed_phrase(kind, payload, fixed):
    assert fixed in card_text(kind, payload)  # 예외 없이 고정 문구


def test_broken_parts_are_skipped_without_raising():
    payload = {
        "title": "치과",
        "date": "내일쯤",
        "start_time": 10,
        "end_time": None,
        "place": None,
        "with_names": "아빠",
    }
    assert card_text("event", payload) == "[일정 공유] 치과 · 날짜 미정"
    settlement = {
        "month": "2026-11",
        "remaining": 100,
        "lines": [
            "깨짐",
            {"direction": "send", "name": "아빠"},
            {"direction": "sideways", "name": "삼촌", "amount": 5},
            {"direction": "send", "name": "엄마", "amount": 300},
        ],
    }
    assert (
        card_text("settlement", settlement)
        == "[정산 공유 2026-11] 공유한 사람이 받을 돈 100원 · 엄마에게 300원 보낼 돈"
    )


def test_whitespace_is_collapsed():
    spaced = card_text("event", {"title": "치과\n\n  정기검진", "date": None})
    assert "\n" not in spaced and "치과 정기검진" in spaced


def test_long_text_drops_whole_items_from_the_back_and_never_cuts_a_name():
    """400자를 넘으면 뒤 항목을 통째로 빼고 … 를 붙인다(이름·줄 중간에서 자르지 않는다)."""
    event = {
        "title": "치과 정기검진",
        "date": "2026-11-12",
        "place": "나" * 380,
        "with_names": [f"가족{i:02d}" for i in range(30)],
    }
    text = card_text("event", event)
    assert len(text) <= 400 and text.endswith("…")
    assert text.startswith("[일정 공유] 치과 정기검진 · 2026-11-12")
    assert "함께" not in text and "가족" not in text  # 함께하는 사람 항목은 통째로 빠졌다
    lines = [{"direction": "send", "name": f"사람{i:02d}", "amount": 10000} for i in range(60)]
    settlement = card_text("settlement", {"month": "2026-11", "remaining": -600000, "lines": lines})
    assert len(settlement) <= 400 and settlement.endswith("…")
    kept = settlement.removesuffix(" …").split(" · ")
    assert kept[0].startswith("[정산 공유 2026-11] 공유한 사람이 보낼 돈 600,000원")
    assert 1 < len(kept) < 60
    assert all(part.endswith("에게 10,000원 보낼 돈") for part in kept[1:])  # 줄은 온전하다


def test_a_title_longer_than_the_limit_is_cut_and_the_rest_is_dropped():
    payload = {"title": "가" * 1000, "date": "2026-11-12", "place": "나" * 10}
    text = card_text("event", payload)
    assert len(text) <= 400 and text.startswith("[일정 공유] 가가") and text.endswith("…")
    assert "2026-11-12" not in text and "나나" not in text


def test_card_names_are_the_names_written_when_it_was_sent():
    event = {"title": "x", "with_names": ["수진", " 아빠 ", 3, "", "수진"]}
    assert card_names("event", event) == ["수진", "아빠"]
    settlement = {
        "month": "2026-11",
        "remaining": 0,
        "lines": [{"direction": "send", "name": "하늘", "amount": 1}, "깨짐", {"name": 5}],
    }
    assert card_names("settlement", settlement) == ["하늘"]
    assert card_names("event", None) == [] and card_names("unknown", {"with_names": ["수진"]}) == []


# ---------- @가비 맥락 ----------


def test_room_context_has_the_event_and_settlement_summaries(client, trio):
    a, b, c = trio
    _event_card(client, a, share_with=[_uid(client, b)])
    _settled(client, a)
    _share(client, a, "settlement", "2026-10")
    transcript = _context(client, a)
    assert "치과 정기검진" in transcript and "2030-01-05" in transcript and "미소치과" in transcript
    assert "10:00~11:00" in transcript
    assert "공유한 사람이 받을 돈 20,000원" in transcript and "2026-10" in transcript
    assert (
        EVENT_FIXED not in transcript and SETTLEMENT_FIXED not in transcript
    )  # 고정 문구 대신 요약


def test_names_in_the_summary_are_pseudonymized_like_normal_messages(client, trio):
    a, b, c = trio
    _event_card(client, a, share_with=[_uid(client, b)])
    _settled(client, a)
    _share(client, a, "settlement", "2026-10")
    transcript = _context(client, a)
    # '삼촌' 같은 호칭은 일반 메시지에서도 가명화하지 않는 말이라(엄마·아빠와 같다) 이름으로 확인하지 않는다
    for real in ("수진", "지민"):
        assert real not in transcript  # 이름이 그대로 나가지 않는다
    assert "[PERSON_" in transcript


def test_normal_messages_and_other_text_are_unchanged(client, trio):
    a, b, _ = trio
    say(client, b, "토요일에 낚시 가자")
    _event_card(client, a)
    transcript = _context(client, a)
    assert "토요일에 낚시 가자" in transcript and "치과 정기검진" in transcript


def test_deleted_card_is_left_out(client, trio):
    a, b, _ = trio
    card = _event_card(client, a)
    say(client, b, "그럼 그때 봐요")
    assert client.delete(f"{MSG}/{card['id']}", headers=a).status_code == 200
    transcript = _context(client, a)
    assert "치과 정기검진" not in transcript and EVENT_FIXED not in transcript
    assert "그럼 그때 봐요" in transcript


def test_card_in_the_family_room_is_not_in_a_direct_room_and_the_other_way_round(client, trio):
    a, b, c = trio
    direct_ab = _direct(client, a, _uid(client, b))
    direct_ac = _direct(client, a, _uid(client, c))
    _event_card(client, a, direct_ab["id"])
    say(client, a, "가족방 이야기")
    _send(client, a, "삼촌과 둘만의 이야기", room_id=direct_ac["id"])
    in_ab = _context(client, a, direct_ab["id"])
    in_ac = _context(client, a, direct_ac["id"])
    in_family = _context(client, a)
    assert "치과 정기검진" in in_ab and "가족방 이야기" not in in_ab
    assert "치과 정기검진" not in in_family and "가족방 이야기" in in_family  # 가족방 맥락
    # 다른 1:1 방에는 자기 방 글만 있고 수진과의 방 카드는 섞이지 않는다
    assert "삼촌과 둘만의 이야기" in in_ac and "치과 정기검진" not in in_ac
    assert "삼촌과 둘만의 이야기" not in in_ab and "삼촌과 둘만의 이야기" not in in_family


def test_the_summary_does_not_touch_the_stored_message(client, trio):
    a, _, _ = trio
    card = _event_card(client, a)
    with SessionLocal() as db:
        ctx = ai_service.room_context(db, _group_id(client, a), None)
        assert "치과 정기검진" in ctx.transcript
        ctx.close()
        assert not db.dirty and not db.new  # 요약 때문에 세션이 더러워지지 않았다
        db.commit()
    with SessionLocal() as db:
        assert db.get(Message, card["id"]).text == EVENT_FIXED  # DB 의 글자는 고정 문구 그대로
        assert db.scalars(select(Message.text)).all() == [EVENT_FIXED]


def test_summary_is_not_used_when_the_share_table_is_missing(client, trio):
    """표(message_shares)가 아직 없는 DB(공용 DB 반영 전)에서도 예외 없이 고정 문구로 동작한다."""
    a, _, _ = trio
    _event_card(client, a)
    say(client, a, "다른 글")
    restore = _drop_share_table()
    try:
        transcript = _context(client, a)
    finally:
        restore()
    assert EVENT_FIXED in transcript and "치과 정기검진" not in transcript
    assert "다른 글" in transcript


# ---------- 대화 분석 ----------


def test_analysis_sends_the_card_summary_masked(client, trio, fake):
    a, b, _ = trio
    enable(client, a)
    say(client, b, "내일 병원 가요")
    _event_card(client, a, share_with=[_uid(client, b)])
    _settled(client, a)
    _share(client, a, "settlement", "2026-10")
    r = analyze(client, a)
    assert r.status_code == 200, r.text
    prompt = fake.calls[-1]["prompt"]
    assert (
        "치과 정기검진" in prompt
        and "미소치과" in prompt
        and "공유한 사람이 받을 돈 20,000원" in prompt
    )
    assert EVENT_FIXED not in prompt and SETTLEMENT_FIXED not in prompt
    assert "수진" not in prompt  # 이름은 가명 토큰으로(호칭인 '삼촌' 은 일반 메시지처럼 그대로)
    assert "[PERSON_" in prompt


def test_analysis_works_when_the_share_table_is_missing(client, trio, fake):
    a, b, _ = trio
    enable(client, a)
    say(client, b, "내일 병원 가요")
    _event_card(client, a)
    say(client, a, "다녀올게요")
    restore = _drop_share_table()
    try:
        r = analyze(client, a)
    finally:
        restore()
    assert r.status_code == 200, r.text
    prompt = fake.calls[-1]["prompt"]
    assert EVENT_FIXED in prompt and "치과 정기검진" not in prompt


def test_direct_room_analysis_has_the_card_but_the_family_room_analysis_does_not(
    client, trio, fake
):
    a, b, _ = trio
    enable(client, a)
    direct = _direct(client, a, _uid(client, b))
    _event_card(client, a, direct["id"])
    for i in range(2):
        _send(client, a if i else b, f"둘만의 이야기 {i}", room_id=direct["id"])
        say(client, a if i else b, f"가족방 이야기 {i}")
    say(client, a, "가족방 이야기 2")
    assert analyze(client, a, room_id=direct["id"]).status_code == 200
    assert "치과 정기검진" in fake.calls[-1]["prompt"]
    assert analyze(client, a).status_code == 200
    assert "치과 정기검진" not in fake.calls[-1]["prompt"]


# ---------- @가비 호출 전체 경로 ----------


def test_asking_gabee_sends_the_card_summary_as_context(client, trio, gabee):
    a, b, _ = trio
    _event_card(client, b)
    _ask_gabee(client, a)
    sent = gabee[-1]
    assert "방의 최근 대화" in sent and "치과 정기검진" in sent
    assert "수진" not in sent.split("방의 최근 대화", 1)[1]  # 보낸 사람 이름도 토큰으로 나간다


def test_asking_gabee_in_a_direct_room_reads_that_rooms_card_only(client, trio, gabee):
    a, b, c = trio
    direct = _direct(client, a, _uid(client, b))
    _event_card(client, b, direct["id"])
    _event_card(client, c, title="가족방 모임")
    _ask_gabee(client, a, room_id=direct["id"])
    sent = gabee[-1]
    assert "치과 정기검진" in sent and "미소치과" in sent
    assert "가족방 모임" not in sent  # 가족방 카드는 1:1 방 맥락에 섞이지 않는다
    _ask_gabee(client, a)  # room_id 가 없으면 가족방 맥락
    sent = gabee[-1]
    assert "가족방 모임" in sent and "치과 정기검진" not in sent


# ---------- 가명화 규칙(일반 메시지와 같다) ----------


def test_names_of_someone_who_left_the_family_are_still_masked(client, trio, fake):
    """카드의 이름은 보낸 시점에 찍힌 값이라 지금 구성원 사전에 없는 사람(나간 사람)의 이름도 가려야 한다."""
    a, b, c = trio
    enable(client, a)
    _event_card(client, a, share_with=[_uid(client, b)])
    _settled(client, a)
    _share(client, a, "settlement", "2026-10")
    say(client, c, "그날 봐요")
    assert client.post(LEAVE_FAMILY, headers=b).status_code in (200, 204)
    transcript = _context(client, a)
    assert "수진" not in transcript and "공유한 사람이 받을 돈 20,000원" in transcript
    assert analyze(client, a).status_code == 200
    prompt = fake.calls[-1]["prompt"]
    assert "수진" not in prompt  # 나간 사람의 실명이 그대로 나가지 않는다
    assert "[PERSON_" in prompt and "20,000원" in prompt


@pytest.mark.parametrize(
    ("label", "number"), [("계좌", "110-222-333444"), ("주민번호", "900101-1234567")]
)
def test_account_and_id_numbers_in_a_card_are_masked_like_a_normal_message(
    client, trio, label, number
):
    """제목에 든 번호도 일반 메시지와 같은 규칙으로 가려진다(같은 가림 토큰으로 바뀐다)."""
    a, b, _ = trio
    _event_card(client, a, title=f"병원비 {label} {number}")
    say(client, b, f"병원비 {label} {number}")
    transcript = _context(client, a)
    assert number not in transcript
    card_line, plain_line = (json.loads(line) for line in transcript.splitlines())
    assert plain_line["text"] != f"병원비 {label} {number}"  # 일반 메시지가 가려졌고
    assert plain_line["text"] in card_line["text"]  # 카드의 같은 글도 같은 토큰으로 가려졌다


def test_recent_messages_still_returns_the_stored_rows(client, trio):
    """요약은 서비스 층에서 만든다: 저장소는 카드 메시지도 DB 그대로(고정 문구) 돌려준다."""
    a, _, _ = trio
    card = _event_card(client, a)
    with SessionLocal() as db:
        rows = ai_repository.recent_messages(db, _group_id(client, a), 10)
        assert [(type(m), m.id, m.text) for m, _ in rows] == [(Message, card["id"], EVENT_FIXED)]
