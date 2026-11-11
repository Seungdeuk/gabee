"""AI 비서 고위험 입력 사전 차단 시험. 임시 SQLite·가짜 httpx(Anthropic 응답 흉내)만 쓴다.

메인 AI 채팅(/ai-assistant/chat, /knowledge/ask)은 2026-11-04 결정으로 막지 않는다(외부 전송은 공지로 처리, 채팅은 서버 DB에
저장되지 않는다). 이 장치는 서버 DB에 저장되는 문서 직접 입력(/knowledge/items)과 탭 에이전트 채팅(가계)에만 남는다.
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


@pytest.mark.parametrize(
    "path,field", [("/ai-assistant/chat", "message"), ("/ai-assistant/knowledge/ask", "question")]
)
@pytest.mark.parametrize("kind", list(CASES))
def test_main_chat_accepts_high_risk_input_and_sends_it_to_the_model(
    client, family, fake, path, field, kind, monkeypatch
):
    """메인 AI 채팅은 막지 않는다. 입력은 가리지 않고 모델로 간다(저장은 하지 않는다)."""
    a, _, _ = family
    allow_ai(client, a, monkeypatch)
    r = client.post(path, json={field: f"이거 좀 봐줘 {CASES[kind]} 입니다"}, headers=a)
    assert r.status_code == 200, r.text
    assert any(CASES[kind] in c.text for c in fake.anthropic)


def test_main_chat_history_with_high_risk_is_accepted(client, family, fake, monkeypatch):
    a, _, _ = family
    allow_ai(client, a, monkeypatch)
    body = {
        "message": "오늘 일정 알려줘",
        "history": [{"role": "user", "text": "안녕"}, {"role": "user", "text": f"카드 {CARD}"}],
    }
    assert client.post("/ai-assistant/chat", json=body, headers=a).status_code == 200


def test_non_target_path_is_not_scanned(client, family, fake):
    a, _, _ = family
    r = client.patch(
        "/ai-assistant/knowledge/items/none", json={"body_md": f"카드 {CARD}"}, headers=a
    )
    assert r.status_code == 404  # PATCH 는 가드 대상이 아니다(알려진 한계)
    assert (
        client.post("/ai-assistant/knowledge/search", json={"query": CARD}, headers=a).status_code
        != 400
    )


def test_non_json_body_keeps_router_422(client, family, fake):
    a, _, _ = family
    r = client.post(
        "/billing/agent/chat",
        content=b"not json at all",
        headers={**a, "content-type": "application/json"},
    )
    assert r.status_code == 422
    assert fake.calls == []


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
        "/billing/agent/chat",
        content=raw.encode(),
        headers={**a, "content-type": "application/json"},
    )
    assert r.status_code == 413
    assert r.json() == {"code": "payload_too_large", "message": "요청이 너무 커요"}
    assert RRN not in r.text
    assert fake.calls == []


def test_secret_at_end_of_long_text_is_still_detected(client, family, fake, monkeypatch):
    a, _, _ = family
    allow_ai(client, a, monkeypatch)
    r = client.post(
        "/billing/agent/chat", json={"message": "가" * 3900 + f" 카드 {CARD}"}, headers=a
    )
    assert r.status_code == 400


def test_auth_failure_stays_401_not_400(client, fake):
    r = client.post("/billing/agent/chat", json={"message": f"카드 {CARD}"})
    assert r.status_code == 401 and r.json()["code"] == "token_required"
    assert fake.calls == []
