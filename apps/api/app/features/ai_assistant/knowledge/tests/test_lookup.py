"""@가비 문서 찾기: LLM 0건, 가족 그룹 격리."""

import pytest

from app.features.ai_assistant.knowledge import service
from app.shared import ai_guard
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm

K = "/ai-assistant/knowledge"
BILL = """# 2026년 10월 전기요금 고지서
분류: 전기요금 고지서
- 사용량 312 kWh
- 청구금액 48,200원
- 납기일 2026-10-25"""
WATER = """# 10월 상하수도 요금 고지서
분류: 수도요금 고지서
- 상하수도 요금 23,400원 (할인 100% 적용_예외)"""
OTHER = """# 다른 집 전기요금
분류: 전기요금 고지서
- 청구금액 99,999원"""


class FakeLLM:
    def __init__(self):
        self.calls = 0
        self.prompts = []

    def complete_json(self, prompt, schema, system=None, max_tokens=None, timeout=40.0):
        self.calls += 1
        self.prompts.append(prompt)
        if "summary" in schema["properties"]:
            data = {"summary": "전기요금 안내예요.", "key_points": ["48,200원", " "]}
        else:
            data = {"answer": "48,200원이에요 [1]"}
        return llm.JsonResult(data=data, input_tokens=10, output_tokens=5, model="fake")


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", f.complete_json)
    monkeypatch.setattr(settings, "ai_request_cooldown_seconds", 0)
    return f


def _add(client, headers, title, body, kind="전기요금 고지서"):
    r = client.post(
        f"{K}/items",
        json={"kind_label": kind, "title": title, "body_md": body, "occurred_on": "2026-10-01"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _enable(group_id, user_id="u"):
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group_id, user_id, True)


@pytest.fixture
def docs(client, family, other_family):
    a, b, group = family
    bill = _add(client, a, "10월 전기요금", BILL)
    water = _add(client, a, "10월 수도요금", WATER, "수도요금 고지서")
    theirs = _add(client, other_family, "다른 집 전기요금", OTHER)
    return a, group, bill, water, theirs, other_family


def _find(client, headers, query, **extra):
    r = client.post(f"{K}/find", json={"query": query, **extra}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_find_typing_twenty_times_never_calls_llm(client, docs, fake, monkeypatch):
    a, *_ = docs
    searched = []
    monkeypatch.setattr(service, "search", lambda *x, **k: searched.append(1) or [])
    query = "전기요금 고지"
    for n in range(20):
        _find(client, a, query[: n % len(query) + 1])
    assert fake.calls == 0
    assert searched == []  # semantic=false 면 pgvector 도 부르지 않는다


def test_find_keyword_first_and_semantic_only_when_asked(client, docs, fake, monkeypatch):
    a, *_ = docs
    searched = []
    monkeypatch.setattr(service, "search", lambda *x, **k: searched.append(1) or [])
    r = _find(client, a, "전기요금", semantic=True)
    assert r["method"] == "keyword" and r["hits"] and searched == []
    assert _find(client, a, "KWH")["hits"]  # 대소문자 무시
    # LIKE 특수문자는 이스케이프된다: % 와 _ 는 글자 그대로만 맞는다
    assert _find(client, a, "100%")["hits"]
    assert _find(client, a, "적용_예")["hits"]
    assert not _find(client, a, "적용x예")["hits"]
    assert not _find(client, a, "9%9")["hits"]
    assert _find(client, a, "없는말씀") == {"method": "keyword", "hits": []}
    assert searched == []
    r = _find(client, a, "없는말씀", semantic=True)
    assert r["method"] == "semantic" and searched == [1]
    assert fake.calls == 0


def test_find_validation(client, docs):
    a, *_ = docs
    for q in ("", "가" * 201, "   "):
        assert client.post(f"{K}/find", json={"query": q}, headers=a).status_code == 422


def test_find_isolated_by_group(client, docs):
    a, group, bill, water, theirs, outsider = docs
    ids = {h["item_id"] for h in _find(client, a, "전기요금")["hits"]}
    assert ids == {bill["id"]}
    assert _find(client, a, "99,999")["hits"] == []
    assert _find(client, outsider, "99,999")["hits"]


def test_original_view_has_no_llm(client, docs, fake):
    a, group, bill, *_ = docs
    assert client.get(f"{K}/items/{bill['id']}", headers=a).status_code == 200
    assert client.get(f"{K}/items", headers=a).status_code == 200
    assert fake.calls == 0
