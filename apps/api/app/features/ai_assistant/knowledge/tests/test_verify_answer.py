"""문서 근거 답 검증(verify): 가짜 응답으로 근거 있는 문장은 남기고, 없는 문장은 지우고, 실패하면 초안을 쓰는지 확인한다."""

import json

import pytest

from app.features.ai_assistant.knowledge import rag_chat, verify
from app.shared.config import settings
from app.shared.db import SessionLocal

pytestmark = pytest.mark.usefixtures("client")

BILL = "# 2026년 10월 전기요금 고지서\n분류: 전기요금 고지서\n- 사용량 312 kWh\n- 청구금액 48,200원"
DRAFT = "10월 전기요금은 48,200원이에요 [1]. 보통 11월에는 더 나와요."
FIXED = "10월 전기요금은 48,200원이에요 [1]."


def _add_bill(client, headers):
    r = client.post(
        "/ai-assistant/knowledge/items",
        json={"kind_label": "전기요금 고지서", "title": "10월 전기요금", "body_md": BILL},
        headers=headers,
    )
    assert r.status_code == 201, r.text


def _verdict(answer: str, removed: int = 1, not_found: bool = False) -> dict:
    payload = {"answer": answer, "removed": removed, "not_found": not_found}
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}


class Fake:
    """첫 호출은 검색 도구, 다음은 초안 답, 검증 호출(system 이 VERIFY_SYSTEM)은 verdict 를 돌려준다."""

    def __init__(self, draft=DRAFT, verdict=None, tool="search_knowledge", boom=False):
        self.draft, self.verdict, self.tool, self.boom = draft, verdict, tool, boom
        self.bodies: list[dict] = []

    def __call__(self, body):
        self.bodies.append(body)
        if body["system"] == verify.VERIFY_SYSTEM:
            if self.boom:
                raise ValueError("verify down")
            return self.verdict
        if len(self.bodies) == 1 and self.tool:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": self.tool,
                        "input": {"query": "전기요금"},
                    }
                ]
            }
        return {"content": [{"type": "text", "text": self.draft}]}

    @property
    def verify_calls(self) -> list[dict]:
        return [b for b in self.bodies if b["system"] == verify.VERIFY_SYSTEM]


def _ask(group, fake, **kw):
    with SessionLocal() as db:
        return rag_chat.ask(db, group["id"], "10월 전기요금", post=fake, **kw)


def test_unsupported_sentence_is_removed_and_evidence_is_sent(client, family):
    a, _, group = family
    _add_bill(client, a)
    fake = Fake(verdict=_verdict(FIXED))
    r = _ask(group, fake)
    assert r.answer == FIXED
    (call,) = fake.verify_calls
    content = call["messages"][0]["content"]
    assert "48,200원" in content and DRAFT in content and "<question>" in content
    assert call["model"] == settings.llm_model and "tools" not in call


def test_supported_answer_is_kept(client, family):
    a, _, group = family
    _add_bill(client, a)
    r = _ask(group, Fake(draft=FIXED, verdict=_verdict(FIXED, removed=0)))
    assert r.answer == FIXED


def test_not_found_with_other_value_is_replaced(client, family):
    a, _, group = family
    _add_bill(client, a)
    draft = "11월 전기요금은 찾지 못했어요. 10월은 48,200원이었어요 [1]."
    short = "11월 전기요금은 찾지 못했어요. 앱에서 원본 보기로 확인해 보세요."
    r = _ask(group, Fake(draft=draft, verdict=_verdict(short, 1, True)))
    assert r.answer == short and "48,200" not in r.answer


def test_failed_verify_keeps_the_draft(client, family):
    a, _, group = family
    _add_bill(client, a)
    r = _ask(group, Fake(boom=True))
    assert r.answer == DRAFT and r.source == "ai"


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        json.dumps({"answer": "", "removed": 0, "not_found": False}),
        json.dumps({"answer": FIXED + " 새 내용 " * 20, "removed": 0, "not_found": False}),
        json.dumps({"answer": "48,200원이에요 [7].", "removed": 0, "not_found": False}),
    ],
)
def test_odd_verdict_keeps_the_draft(client, family, text):
    a, _, group = family
    _add_bill(client, a)
    fake = Fake(verdict={"content": [{"type": "text", "text": text}]})
    assert _ask(group, fake).answer == DRAFT


def test_calculated_number_is_kept(client, family):
    a, _, group = family
    _add_bill(client, a)
    draft = "10월 전기요금은 48,200원이고 사용량 312 kWh라서 kWh당 154.5원이에요 [1]."
    r = _ask(group, Fake(draft=draft, verdict=_verdict(draft, removed=0)))
    assert r.answer == draft and r.verify_draft == draft and not r.verify_changed


def test_new_number_in_fixed_answer_keeps_the_draft(client, family):
    a, _, group = family
    _add_bill(client, a)
    r = _ask(group, Fake(verdict=_verdict("10월 전기요금은 52,000원이에요 [1].")))
    assert r.answer == DRAFT


def test_new_app_path_in_fixed_answer_keeps_the_draft(client, family):
    a, _, group = family
    _add_bill(client, a)
    fixed = FIXED + " 앱의 '내 요금 > 전기' 에서 볼 수 있어요."
    r = _ask(group, Fake(verdict=_verdict(fixed)))
    assert r.answer == DRAFT


def test_existing_app_path_is_kept(client, family):
    a, _, group = family
    draft = "10월 전기요금은 48,200원이에요 [1]. '내 요금 > 전기' 에서 볼 수 있어요. 보통 11월에는 더 나와요."
    fixed = "10월 전기요금은 48,200원이에요 [1]. '내 요금 > 전기' 에서 볼 수 있어요."
    _add_bill(client, a)
    assert _ask(group, Fake(draft=draft, verdict=_verdict(fixed))).answer == fixed


def test_verify_records_draft_changed_and_not_found(client, family):
    a, _, group = family
    _add_bill(client, a)
    r = _ask(group, Fake(verdict=_verdict(FIXED)))
    assert r.verify_draft == DRAFT and r.verify_changed and not r.verify_not_found
    short = "11월 전기요금은 찾지 못했어요. 앱에서 원본 보기로 확인해 보세요."
    r = _ask(
        group,
        Fake(
            draft="11월 전기요금은 찾지 못했어요. 10월은 48,200원이었어요 [1].",
            verdict=_verdict(short, 1, True),
        ),
    )
    assert r.verify_not_found


def test_verify_prompt_allows_calculated_values():
    assert "계산" in verify.VERIFY_SYSTEM and "앱 메뉴 경로" in verify.VERIFY_SYSTEM


def test_setting_off_skips_verify(client, family, monkeypatch):
    a, _, group = family
    _add_bill(client, a)
    monkeypatch.setattr(settings, "chat_verify_answer", False)
    fake = Fake(verdict=_verdict(FIXED))
    assert _ask(group, fake).answer == DRAFT and not fake.verify_calls


def test_no_document_search_is_not_verified(client, family):
    _, _, group = family
    fake = Fake(draft="안녕하세요, 무엇을 도와드릴까요? 오늘도 좋은 하루예요.", tool=None)
    r = _ask(group, fake)
    assert "안녕" in r.answer and not fake.verify_calls


def test_web_answer_is_not_verified(client, family, monkeypatch):
    a, _, group = family
    _add_bill(client, a)
    monkeypatch.setattr(settings, "web_search_enabled", True)
    fake = Fake(verdict=_verdict(FIXED))
    assert _ask(group, fake, web=True).answer == DRAFT and not fake.verify_calls


def test_other_tool_use_is_not_verified(client, family):
    a, _, group = family
    _add_bill(client, a)
    fake = Fake(verdict=_verdict(FIXED), tool="list_items")
    assert _ask(group, fake).answer == DRAFT and not fake.verify_calls


def test_direct_agent_reply_is_not_verified():
    run = rag_chat.tool_graph.Run(model=None, handle=lambda c: None, max_steps=4)
    run.done = True
    result = rag_chat.AskResult("답이에요. 충분히 긴 답입니다.", "ai")
    result.doc_searched = True
    assert not rag_chat._should_verify(run, result, False)
    run.done = False
    assert rag_chat._should_verify(run, result, False)
    result.tool_calls.append({"name": "ask_billing", "input": {}})
    assert not rag_chat._should_verify(run, result, False)


def _guarded(client, family, monkeypatch, fake):
    from sqlalchemy import select

    from app.features.family_group.models import User
    from app.shared.ai_usage import AiUsageLog
    from tests.ai_consent import enable_ai

    a, _, group = family
    _add_bill(client, a)
    enable_ai(group["id"])
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.name == "지민")).first()
        r = rag_chat.ask_guarded(
            db,
            user.id,
            group["id"],
            "10월 전기요금",
            feature="assistant_chat",
            post=fake,
            user=user,
        )
        logs = db.scalars(select(AiUsageLog).where(AiUsageLog.group_id == group["id"])).all()
    return r, [(row.api_calls, row.status) for row in logs]


def test_verify_call_is_counted_in_the_usage(client, family, monkeypatch):
    fake = Fake(verdict=_verdict(FIXED))
    r, logs = _guarded(client, family, monkeypatch, fake)
    assert r.answer == FIXED
    assert len(fake.bodies) == 3 and logs == [(3, "ok")]  # 검색 호출 + 답 + 검증 모두 센다


def test_failed_verify_is_still_counted_but_not_an_outage(client, family, monkeypatch):
    fake = Fake(boom=True)
    r, logs = _guarded(client, family, monkeypatch, fake)
    assert r.answer == DRAFT and logs == [(3, "ok")]


def test_long_evidence_is_not_verified(monkeypatch):
    """근거 글이 설정 길이보다 길면 확인 호출을 하지 않고 초안을 그대로 쓴다."""
    from app.features.ai_assistant.knowledge import verify
    from app.shared.config import settings

    monkeypatch.setattr(settings, "chat_verify_max_evidence_chars", 50)
    called = []

    def post(body):
        called.append(body)
        return {"content": [{"type": "text", "text": "{}"}]}

    long_evidence = [{"results": [{"ref": 1, "title": "긴 문서", "text": "가" * 200}]}]
    draft = "관리비는 120,000원이에요 [1]."
    out = verify.verify_outcome(post, "관리비 얼마야?", long_evidence, draft)
    assert called == []
    assert out.answer == draft
