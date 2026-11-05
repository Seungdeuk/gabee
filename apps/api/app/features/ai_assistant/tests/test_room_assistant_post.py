"""가족 채팅방에서 @가비 로 부른 답은 모두 서버가 가비 이름으로 가족 전체방에 저장한다(개인 대화는 저장하지 않는다)."""

import pytest
from sqlalchemy import func, select

from app.features.ai_assistant.knowledge import rag_chat
from app.features.family_chat import ai_repository, assistant
from app.features.family_chat.models import ASSISTANT_NAME, ASSISTANT_USER_ID, Message
from app.features.family_group.models import GroupMember, User
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.ai_consent import enable_ai

MSG = "/family-chat/messages"
SUB_ANSWER = "이번 달 지출은 총 0원이에요."


def _tool_use(name, args):
    return {"content": [{"type": "tool_use", "id": "t1", "name": name, "input": args}]}


def _text(text):
    return {"content": [{"type": "text", "text": text}]}


@pytest.fixture
def ask(client, family, monkeypatch):
    a, b, group = family
    enable_ai(group["id"])
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    def go(first_tool, first_args, sub_tool=None, sub_text=SUB_ANSWER, **body):
        def fake_post(req):
            if "가계(정산) 담당" in req["system"]:
                if len(req["messages"]) == 1:
                    return _tool_use(sub_tool, {})
                return _text(sub_text)
            if first_tool is None:
                return _text("안녕하세요!")
            if len(req["messages"]) == 1:
                return _tool_use(first_tool, first_args)
            return _text("메인 최종 답")

        monkeypatch.setattr(rag_chat, "_post", fake_post)
        r = client.post("/ai-assistant/chat", json={"message": "질문", **body}, headers=a)
        assert r.status_code == 200, r.text
        return r.json()

    return go


def _room_messages(client, headers):
    return client.get(MSG, headers=headers).json()


def test_shareable_room_answer_is_posted_as_gabi(client, family, ask):
    a, b, _ = family
    out = ask("ask_billing", {"question": "이번 달 지출"}, "get_month_summary", audience="room")
    assert out["visibility"] == "room" and out["posted_message_id"] is not None
    for headers in (a, b):  # 가족 누구나 방에서 본다
        msgs = _room_messages(client, headers)
        assert [m["text"] for m in msgs] == [out["reply"]]  # 응답으로 돌려준 답이 그대로 저장된다
        assert msgs[0]["user_name"] == ASSISTANT_NAME and msgs[0]["is_assistant"] is True
        assert msgs[0]["id"] == out["posted_message_id"]


def test_allowance_answer_in_room_is_posted_too(client, family, ask):
    """예전에는 개인용이라 저장하지 않던 답(자녀 용돈 장부)도 방에서 부르면 가족 모두에게 저장된다."""
    a, b, _ = family
    out = ask("ask_billing", {"question": "용돈"}, "list_allowances", audience="room")
    assert out["visibility"] == "room" and out["private_reasons"] == []
    assert out["posted_message_id"] is not None
    for headers in (a, b):
        assert [m["text"] for m in _room_messages(client, headers)] == [out["reply"]]


def test_personal_chat_is_never_posted(client, family, ask):
    a, _, _ = family
    out = ask("ask_billing", {"question": "이번 달 지출"}, "get_month_summary")
    assert out["posted_message_id"] is None and _room_messages(client, a) == []


def test_old_apps_private_flag_in_history_is_ignored(client, family, ask):
    """예전 앱이 보내는 history 의 private 표시는 더 이상 저장을 막지 않는다."""
    a, _, _ = family
    history = [
        {"role": "user", "text": "아이 용돈 잔액 알려줘"},
        {"role": "assistant", "text": "잔액은 12,000원이에요.", "private": True},
    ]
    out = ask(None, None, audience="room", history=history)
    assert out["visibility"] == "room" and out["posted_message_id"] is not None
    assert [m["text"] for m in _room_messages(client, a)] == [out["reply"]]


def test_public_history_does_not_block_posting(client, family, ask):
    a, _, _ = family
    history = [
        {"role": "user", "text": "안녕"},
        {"role": "assistant", "text": "안녕하세요!"},
    ]
    out = ask(None, None, audience="room", history=history)
    assert out["visibility"] == "room" and out["posted_message_id"] is not None


def test_assistant_account_is_not_a_login_or_a_family_member(client, family, ask):
    ask("ask_billing", {"question": "이번 달 지출"}, "get_month_summary", audience="room")
    with SessionLocal() as db:
        user = db.get(User, ASSISTANT_USER_ID)
        assert user.login_id is None and user.email is None and user.password_hash is None
        assert user.active_group_id is None
        members = db.scalar(
            select(func.count()).select_from(GroupMember).where(GroupMember.user_id == user.id)
        )
        assert members == 0  # 구성원 목록·할 일 담당자·읽음 계산에 나오지 않는다


def test_assistant_account_is_created_once(client, family):
    _, _, group = family
    with SessionLocal() as db:
        first = assistant.get_or_create_assistant(db)
        second = assistant.get_or_create_assistant(db)
        assert first.id == second.id == ASSISTANT_USER_ID
        assistant.post_as_assistant(db, group["id"], "하나")
        assistant.post_as_assistant(db, group["id"], "둘")
        count = db.scalar(
            select(func.count()).select_from(User).where(User.id == ASSISTANT_USER_ID)
        )
        assert count == 1


def test_citation_numbers_are_removed_from_the_room_message():
    assert assistant.clip('전기요금은 61,240원이에요 [1]. 제목은 "9월 전기요금"이에요 [2].') == (
        '전기요금은 61,240원이에요. 제목은 "9월 전기요금"이에요.'
    )


def test_markdown_marks_are_removed_from_the_room_message():
    text = "## 이번 달 지출\n\n총액은 **205,000원**이에요.\n\n- 식비: 160,000원\n- 교통: 45,000원"
    assert (
        assistant.clip(text)
        == "이번 달 지출\n\n총액은 205,000원이에요.\n\n• 식비: 160,000원\n• 교통: 45,000원"
    )
    assert assistant.clip("가격은 #1 입니다") == "가격은 #1 입니다"  # 줄 맨 앞이 아닌 # 는 그대로


def test_list_lines_get_bullets_and_short_dates_for_readability():
    from datetime import date

    year = date.today().year
    text = (
        f"**{year}년 11월 지출 내역** (총 203,800원, 5건)\n\n"
        f"- {year}-11-04: 지우 문구류 9,500원 (기타, 시험 엄마 결제)\n"
        f"* {year}-11-03: 교통카드 충전 30,000원\n"
        "- 2024-01-05: 작년 영수증 1,000원\n\n\n\n"
        "카테고리별 합계\n"
        "1. 식비 151,500원"
    )
    assert (
        assistant.clip(text)
        == (
            f"{year}년 11월 지출 내역 (총 203,800원, 5건)\n\n"
            "• 11/04 지우 문구류 9,500원 (기타, 시험 엄마 결제)\n"
            "• 11/03 교통카드 충전 30,000원\n"
            "• 2024-01-05 작년 영수증 1,000원\n\n"  # 올해가 아닌 날짜는 연도를 지키고, 빈 줄은 한 줄까지만
            "카테고리별 합계\n"
            "1. 식비 151,500원"  # 번호 목록은 그대로
        )
    )
    assert (
        assistant.clip("납부기한은 2026-11-20 까지예요") == "납부기한은 2026-11-20 까지예요"
    )  # 문장 속 날짜는 건드리지 않는다


def test_long_answer_is_clipped_to_the_message_limit():
    assert assistant.clip("가" * 3000).endswith("…") and len(assistant.clip("가" * 3000)) == 2000
    assert assistant.clip("  짧은 글  ") == "짧은 글"


def test_ai_analysis_does_not_read_assistant_messages(client, family):
    a, b, group = family
    for i in range(3):
        client.post(MSG, json={"text": f"가족 메시지 {i}"}, headers=a if i % 2 == 0 else b)
    with SessionLocal() as db:
        assistant.post_as_assistant(db, group["id"], "가비의 답")
        rows = ai_repository.recent_messages(db, group["id"], 50)
        assert [m.text for m, _ in rows] == ["가족 메시지 0", "가족 메시지 1", "가족 메시지 2"]
        assert (
            db.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.user_id == ASSISTANT_USER_ID)
            )
            == 1
        )


def test_people_messages_are_not_marked_as_assistant(client, family):
    a, _, _ = family
    client.post(MSG, json={"text": "안녕"}, headers=a)
    assert [m["is_assistant"] for m in _room_messages(client, a)] == [False]
