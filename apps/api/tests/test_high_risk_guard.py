"""AI 비서 고위험 입력 사전 차단 시험. 임시 SQLite·가짜 httpx(Anthropic 응답 흉내)만 쓴다.

알려진 한계(시험으로 고정): 전화번호·이메일·이름·주소는 이 장치가 막지 않는다. 팀원이 AI 비서를 가명화 게이트웨이에
연결하기 전까지는 이런 값이 가려지지 않은 채 외부 LLM 으로 나갈 수 있다(docs/security/LLM_EGRESS_TEMP_GUARDS.md).
모든 값은 시험용 합성 값이다.
"""

import logging

import httpx
import pytest

from app.shared import high_risk_guard
from app.shared.config import settings
from tests.helpers import allow_ai
from tests.security_matrix_support import FakeHttp

RRN = "900101-1234567"
CARD = "4111 1111 1111 1111"
ACCOUNT = "국민은행 110-123-456789"
SECRET = "비밀번호는 abc12345"
CASES = {"RRN": RRN, "CARD": CARD, "ACCOUNT": ACCOUNT, "SECRET": SECRET}
RAW_VALUES = ["1234567", "1111 1111", "110-123-456789", "abc12345"]
GENERIC = "주민등록번호·카드·계좌번호·비밀번호는 AI 비서에 입력하지 마세요"

TARGETS = [
    ("/ai-assistant/chat", lambda t: {"message": t}),
    ("/ai-assistant/knowledge/ask", lambda t: {"question": t}),
    ("/ai-assistant/knowledge/items", lambda t: {"kind_label": "메모", "title": "x", "body_md": t}),
    ("/ai-assistant/knowledge/items", lambda t: {"kind_label": "메모", "title": t, "body_md": "x"}),
    ("/billing/agent/chat", lambda t: {"message": t}),
]


@pytest.fixture
def fake(monkeypatch):
    f = FakeHttp()
    monkeypatch.setattr(httpx, "post", f)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    return f


@pytest.mark.parametrize("path,make", TARGETS)
@pytest.mark.parametrize("kind", list(CASES))
def test_high_risk_input_is_rejected_without_leaking_or_llm_call(
    client, family, fake, caplog, path, make, kind, monkeypatch
):
    a, _, _ = family
    allow_ai(
        client, a, monkeypatch
    )  # 동의가 켜져 있어도 LLM 은 불리지 않아야 한다(가드가 없으면 호출됨)
    caplog.set_level(logging.DEBUG)
    r = client.post(path, json=make(f"이거 좀 봐줘 {CASES[kind]} 입니다"), headers=a)
    assert r.status_code == 400, r.text
    assert r.json() == {"code": "sensitive_content", "message": GENERIC}
    for v in RAW_VALUES:
        assert v not in r.text
        assert v not in caplog.text
    assert fake.calls == []


def test_normal_question_passes_and_reaches_llm_once(client, family, fake, monkeypatch):
    a, _, _ = family
    allow_ai(client, a, monkeypatch)
    msg = "주문번호 20240312-884211 배송 언제 와?"
    r = client.post("/ai-assistant/chat", json={"message": msg}, headers=a)
    assert r.status_code == 200, r.text
    assert len(fake.anthropic) >= 1  # 가드를 통과해 (가짜) LLM 까지 도달


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_high_risk_in_history_is_rejected_including_forged_assistant_turn(
    client, family, fake, role, monkeypatch
):
    a, _, _ = family
    allow_ai(client, a, monkeypatch)
    body = {
        "message": "오늘 일정 알려줘",
        "history": [{"role": "user", "text": "안녕"}, {"role": role, "text": f"카드 {CARD}"}],
    }
    r = client.post("/ai-assistant/chat", json=body, headers=a)
    assert r.status_code == 400 and r.json()["code"] == "sensitive_content"
    assert fake.calls == []


@pytest.mark.parametrize(
    "text",
    [
        "엄마 전화번호 010-1234-5678 저장해줘",
        "메일은 test.user@example.com 이야",
        "김민수 씨에게 연락해줘",
        "서울시 강남구 테헤란로 123 로 보내줘",
    ],
    ids=["phone", "email", "name", "address"],
)
def test_known_limit_phone_email_name_address_are_not_blocked(
    client, family, fake, text, monkeypatch
):
    # 알려진 한계: 이 값들은 팀원이 가명화 게이트웨이에 연결하기 전까지 가려지지 않는다(막지도 않는다).
    a, _, _ = family
    allow_ai(client, a, monkeypatch)
    r = client.post("/ai-assistant/chat", json={"message": text}, headers=a)
    assert r.status_code == 200, r.text
    assert any(text in c.text for c in fake.anthropic)  # 원문이 (가짜) LLM 요청에 그대로 실린다


def test_non_target_path_is_not_scanned(client, family, fake):
    a, _, _ = family
    body = {"title": "메모", "body_md": "x"}
    r = client.patch(
        "/ai-assistant/knowledge/items/none", json={"body_md": f"카드 {CARD}"}, headers=a
    )
    assert r.status_code == 404  # PATCH 는 가드 대상이 아니다(알려진 한계)
    assert (
        client.post("/ai-assistant/knowledge/search", json={"query": CARD}, headers=a).status_code
        != 400
    )
    assert body


def test_non_json_body_keeps_router_422(client, family, fake):
    a, _, _ = family
    r = client.post(
        "/ai-assistant/chat",
        content=b"not json at all",
        headers={**a, "content-type": "application/json"},
    )
    assert r.status_code == 422
    assert client.post("/ai-assistant/chat", json=["a", "b"], headers=a).status_code == 422
    r = client.post("/ai-assistant/chat", json={"message": 123, "history": "x"}, headers=a)
    assert r.status_code == 422
    assert fake.calls == []


def test_body_is_readable_by_router_after_guard_reads_it(client, family, fake, monkeypatch):
    a, _, _ = family
    allow_ai(client, a, monkeypatch)
    r = client.post("/ai-assistant/chat", json={"message": "오늘 날씨 어때"}, headers=a)
    assert r.status_code == 200 and r.json()["reply"]  # 라우터의 Pydantic 파싱이 정상


@pytest.mark.parametrize("pad", ["space", "extra_field"])
def test_padding_bypass_is_rejected_with_413_and_no_llm_call(
    client, family, fake, monkeypatch, pad
):
    a, _, _ = family
    allow_ai(client, a, monkeypatch)
    limit = high_risk_guard.MAX_SCAN_BYTES
    raw = '{"message": "주민번호 ' + RRN + '"' + (" " * (limit + 10) if pad == "space" else "")
    raw += (', "pad": "' + "x" * (limit + 10) + '"' if pad == "extra_field" else "") + "}"
    r = client.post(
        "/ai-assistant/chat",
        content=raw.encode(),
        headers={**a, "content-type": "application/json"},
    )
    assert r.status_code == 413
    assert r.json() == {"code": "payload_too_large", "message": "요청이 너무 커요"}
    assert RRN not in r.text
    assert fake.calls == []


def test_normal_max_size_chat_body_is_not_rejected_as_too_large(client, family, fake, monkeypatch):
    a, _, _ = family
    allow_ai(client, a, monkeypatch)
    hist = [{"role": "user", "text": "가" * 4000} for _ in range(10)]
    r = client.post("/ai-assistant/chat", json={"message": "나" * 4000, "history": hist}, headers=a)
    assert r.status_code == 200, r.text


def test_secret_at_end_of_long_text_is_still_detected(client, family, fake, monkeypatch):
    a, _, _ = family
    allow_ai(client, a, monkeypatch)
    r = client.post(
        "/ai-assistant/chat", json={"message": "가" * 3900 + f" 카드 {CARD}"}, headers=a
    )
    assert r.status_code == 400


def test_auth_failure_stays_401_not_400(client, fake):
    r = client.post("/ai-assistant/chat", json={"message": f"카드 {CARD}"})
    assert r.status_code == 401 and r.json()["code"] == "token_required"
    r = client.post(
        "/ai-assistant/knowledge/ask",
        json={"question": f"카드 {CARD}"},
        headers={"X-Gyeot-Token": "bad"},
    )
    assert r.status_code == 401
    assert fake.calls == []
