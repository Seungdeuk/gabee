"""AI 채팅과 사진 올리기."""

from tests.helpers import allow_ai


def set_assistant_limits(monkeypatch, cooldown=0, per_user=100, per_group=300) -> None:
    """어시스턴트 묶음 한도를 시험용 값으로 다시 등록한다(시험이 끝나면 묶음 표도 원래대로 돌아간다)."""
    from app.features.ai_assistant import limits
    from app.shared import ai_guard
    from app.shared.config import settings

    monkeypatch.setattr(ai_guard, "_BUCKETS", dict(ai_guard._BUCKETS))
    monkeypatch.setattr(settings, "ai_assistant_cooldown_seconds", cooldown)
    monkeypatch.setattr(settings, "ai_assistant_max_calls_per_user_per_day", per_user)
    monkeypatch.setattr(settings, "ai_assistant_max_calls_per_group_per_day", per_group)
    limits.register()


def test_ai_chat_falls_back_without_api_key(client, family):
    a, _, _ = family
    r = client.post("/ai-assistant/chat", json={"message": "오늘 일정 알려줘"}, headers=a).json()
    assert r["source"] == "fallback" and r["reply"]
    assert client.post("/ai-assistant/chat", json={"message": ""}, headers=a).status_code == 422


def test_photo_upload_rules(client, family):
    a, b, _ = family
    ok = client.post(
        "/ai-assistant/photos",
        files={"file": ("a.jpg", b"\xff\xd8\xff" + b"0" * 20, "image/jpeg")},
        headers=a,
    )
    assert ok.status_code == 201 and ok.json()["status"] == "received"
    assert (
        client.post(
            "/ai-assistant/photos", files={"file": ("a.gif", b"GIF89a", "image/gif")}, headers=a
        ).json()["code"]
        == "unsupported_type"
    )
    assert (
        client.post(
            "/ai-assistant/photos", files={"file": ("a.jpg", b"", "image/jpeg")}, headers=a
        ).json()["code"]
        == "empty_file"
    )
    assert [p["filename"] for p in client.get("/ai-assistant/photos", headers=b).json()] == [
        "a.jpg"
    ]


def test_chat_uses_family_records_and_returns_sources(client, family, monkeypatch):
    from app.features.ai_assistant.knowledge import rag_chat
    from app.shared.config import settings

    a, _, _ = family
    client.post(
        "/ai-assistant/knowledge/items",
        json={
            "kind_label": "전기요금 고지서",
            "title": "10월 전기요금",
            "body_md": "# 10월 전기요금\n분류: 전기요금 고지서\n- 청구금액 48,200원",
        },
        headers=a,
    )
    steps = []

    def fake_post(body):
        steps.append(1)
        if len(steps) == 1:
            call = {
                "type": "tool_use",
                "id": "t",
                "name": "search_knowledge",
                "input": {"query": "전기요금"},
            }
            return {"content": [call]}
        return {"content": [{"type": "text", "text": "「10월 전기요금」은 48,200원이에요."}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    allow_ai(client, a, monkeypatch)
    r = client.post("/ai-assistant/chat", json={"message": "전기요금 얼마야"}, headers=a).json()
    assert r["source"] == "ai" and "48,200원" in r["reply"]
    assert [(s["n"], s["title"]) for s in r["sources"]] == [(1, "10월 전기요금")]


def test_chat_without_a_family_group_still_answers(client):
    from tests.helpers import signup

    lone = signup(client, "혼자")
    r = client.post("/ai-assistant/chat", json={"message": "안녕"}, headers=lone).json()
    assert r["source"] == "fallback" and r["reply"] and r["sources"] == []


def test_chat_history_is_sent_in_order_and_limit_is_enforced(client, family, monkeypatch):
    from app.features.ai_assistant.knowledge import rag_chat
    from app.shared.config import settings

    a, _, _ = family
    seen = []

    def fake_post(body):
        seen.append(body["messages"])
        return {"content": [{"type": "text", "text": "네, 알겠어요."}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    allow_ai(client, a, monkeypatch)
    set_assistant_limits(monkeypatch, per_user=2)
    history = [
        {"role": "assistant", "text": "안녕하세요"},  # user 로 시작하지 않는 앞부분은 버린다
        {"role": "user", "text": "전기요금 알려줘"},
        {"role": "assistant", "text": "48,200원이에요"},
    ]
    body = {"message": "그럼 수도는?", "history": history}
    assert client.post("/ai-assistant/chat", json=body, headers=a).status_code == 200
    assert [(m["role"], m["content"]) for m in seen[0]] == [
        ("user", "전기요금 알려줘"),
        ("assistant", "48,200원이에요"),
        ("user", "그럼 수도는?"),
    ]
    assert (
        client.post("/ai-assistant/chat", json={"message": "한 번 더"}, headers=a).status_code
        == 200
    )
    third = client.post("/ai-assistant/chat", json={"message": "또?"}, headers=a)
    assert third.status_code == 429 and third.json()["code"] == "ai_daily_limit_user"
    too_long = {"message": "a", "history": [{"role": "user", "text": "x"}] * 11}
    assert client.post("/ai-assistant/chat", json=too_long, headers=a).status_code == 422


def test_photos_scoped_to_group(client, family, other_family):
    a, _, _ = family
    client.post(
        "/ai-assistant/photos",
        files={"file": ("a.jpg", b"\xff\xd8\xff" + b"0" * 20, "image/jpeg")},
        headers=a,
    )
    assert client.get("/ai-assistant/photos", headers=other_family).json() == []


def test_chat_citation_numbers_match_the_source_chips(client, family, monkeypatch):
    """LLM 이 검색 결과의 ref 로 [n] 을 달면, 그 번호가 앱 출처 칩의 번호와 같다."""
    import json

    from app.features.ai_assistant.knowledge import rag_chat
    from app.shared.config import settings

    a, _, _ = family
    for kind, title in [("전기요금 고지서", "10월 전기요금"), ("수도요금 고지서", "10월 수도요금")]:
        body = f"# {title}\n분류: {kind}\n- 금액 있음"
        client.post(
            "/ai-assistant/knowledge/items",
            json={"kind_label": kind, "title": title, "body_md": body},
            headers=a,
        )
    steps = []

    def fake_post(body):
        steps.append(1)
        if len(steps) == 1:
            call = {
                "type": "tool_use",
                "id": "t",
                "name": "search_knowledge",
                "input": {"query": "요금"},
            }
            return {"content": [call]}
        found = json.loads(body["messages"][-1]["content"][0]["content"])["results"]
        ref = next(r["ref"] for r in found if r["title"] == "10월 수도요금")
        return {
            "content": [{"type": "text", "text": f"수도요금이 있어요 [{ref}]"}]
        }  # 제목 없이 번호만

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    allow_ai(client, a, monkeypatch)
    r = client.post("/ai-assistant/chat", json={"message": "수도"}, headers=a).json()
    assert [s["title"] for s in r["sources"]] == ["10월 수도요금"]
    assert f"[{r['sources'][0]['n']}]" in r["reply"]


# ---------- AI 동의·한도 관문(ai_guard) ----------
class CountingPost:
    """rag_chat._post 대신 쓰는 가짜. 호출 수와 보낸 본문을 센다(도구 한 번 → 글 답 한 번 = 2회)."""

    def __init__(self, tool_query: str | None = None):
        self.bodies: list[dict] = []
        self.tool_query = tool_query

    def __call__(self, body):
        self.bodies.append(body)
        usage = {"input_tokens": 100, "output_tokens": 20}
        if self.tool_query and len(self.bodies) == 1:
            call = {
                "type": "tool_use",
                "id": "t",
                "name": "search_knowledge",
                "input": {"query": self.tool_query},
            }
            return {"content": [call], "usage": usage, "model": "fake-model"}
        return {
            "content": [{"type": "text", "text": "확인했어요."}],
            "usage": usage,
            "model": "fake-model",
        }


def _fake_ai(monkeypatch, tool_query=None) -> CountingPost:
    import httpx

    from app.features.ai_assistant.knowledge import rag_chat
    from app.shared.config import settings

    post = CountingPost(tool_query)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", post)

    def no_http(*a, **k):
        raise AssertionError("httpx.post 가 직접 불렸다")

    monkeypatch.setattr(httpx, "post", no_http)
    return post


def _usage_rows(feature):
    from sqlalchemy import select

    from app.shared.ai_usage import AiUsageLog
    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        return list(
            db.scalars(
                select(AiUsageLog).where(AiUsageLog.feature == feature).order_by(AiUsageLog.id)
            )
        )


ENTRIES = (
    ("/ai-assistant/chat", {"message": "전기요금 얼마야"}, "assistant_chat"),
    ("/ai-assistant/knowledge/ask", {"question": "전기요금 얼마야"}, "knowledge_ask"),
)


def test_ai_consent_off_blocks_both_entries_without_any_call(client, family, monkeypatch):
    a, _, _ = family
    post = _fake_ai(monkeypatch)
    for path, body, feature in ENTRIES:
        r = client.post(path, json=body, headers=a)
        assert r.status_code == 403 and r.json()["code"] == "ai_not_enabled", path
        assert _usage_rows(feature) == []
    assert post.bodies == []  # Anthropic 으로 한 번도 나가지 않았다


def test_ai_consent_on_answers_and_records_real_call_count(client, family, monkeypatch):
    a, _, _ = family
    client.post(
        "/ai-assistant/knowledge/items",
        json={
            "kind_label": "전기요금 고지서",
            "title": "10월 전기요금",
            "body_md": "청구 48,200원",
        },
        headers=a,
    )
    post = _fake_ai(monkeypatch, tool_query="전기요금")
    allow_ai(client, a, monkeypatch)
    for path, body, feature in ENTRIES:
        post.bodies.clear()
        r = client.post(path, json=body, headers=a)
        assert r.status_code == 200, (path, r.text)
        assert len(post.bodies) == 2  # 도구 호출 한 번 + 최종 답 한 번
        (row,) = _usage_rows(feature)
        assert row.status == "ok" and row.api_calls == 2 and row.cache_hit is False
        assert row.input_tokens == 200 and row.output_tokens == 40 and row.model == "fake-model"
    # 대화 원문은 결과 캐시에 남기지 않는다
    from sqlalchemy import select

    from app.shared.ai_usage import AiResultCache
    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        assert db.scalars(select(AiResultCache)).first() is None


def test_ai_daily_limit_applies_to_chat_and_ask_together(client, family, monkeypatch):

    a, _, _ = family
    post = _fake_ai(monkeypatch)
    allow_ai(client, a, monkeypatch)
    set_assistant_limits(monkeypatch, per_user=2)
    assert client.post(*ENTRIES[0][:1], json=ENTRIES[0][1], headers=a).status_code == 200
    assert client.post(*ENTRIES[1][:1], json=ENTRIES[1][1], headers=a).status_code == 200
    for path, body, _ in ENTRIES:
        r = client.post(path, json=body, headers=a)
        assert r.status_code == 429 and r.json()["code"] == "ai_daily_limit_user", path
    assert len(post.bodies) == 2


def test_daily_limit_rejection_is_logged_once_without_using_the_limit(client, family, monkeypatch):
    a, _, _ = family
    _fake_ai(monkeypatch)
    allow_ai(client, a, monkeypatch)
    set_assistant_limits(monkeypatch, per_user=1)
    path, body, feature = ENTRIES[0]
    assert client.post(path, json=body, headers=a).status_code == 200
    for _ in range(3):  # 계속 눌러도
        assert client.post(path, json=body, headers=a).status_code == 429
    rows = _usage_rows(feature)
    assert [(r.status, r.api_calls, r.error_code) for r in rows] == [
        ("ok", 1, None),
        ("rejected", 0, "ai_daily_limit_user"),  # 짧은 시간 안에는 한 줄만 남는다
    ]


def test_ai_cooldown_applies_to_chat(client, family, monkeypatch):

    a, _, _ = family
    post = _fake_ai(monkeypatch)
    allow_ai(client, a, monkeypatch)
    set_assistant_limits(monkeypatch, cooldown=60)
    assert client.post("/ai-assistant/chat", json={"message": "하나"}, headers=a).status_code == 200
    r = client.post("/ai-assistant/chat", json={"message": "둘"}, headers=a)
    assert r.status_code == 429 and r.json()["code"] == "ai_cooldown"
    assert len(post.bodies) == 1


def test_chat_without_a_group_never_calls_the_external_ai(client, monkeypatch):
    from tests.helpers import signup

    lone = signup(client, "혼자")
    post = _fake_ai(monkeypatch)
    for _ in range(3):
        r = client.post("/ai-assistant/chat", json={"message": "안녕"}, headers=lone)
        assert r.status_code == 200
        body = r.json()
        assert body["source"] == "fallback" and "가족 그룹" in body["reply"]
        assert body["sources"] == []
    assert post.bodies == []


def test_chat_include_sensitive_defaults_to_on():
    # 2026-10-26 사용자 결정: 가린 글만 채팅 근거로 쓰는 것이 기본이고, 끄려면 CHAT_INCLUDE_SENSITIVE=false.
    # (분리 설계 — 서버 허용 / 개인 선택 — 는 채팅 담당과 따로 정한다)
    from app.shared.config import Settings

    assert Settings.model_fields["chat_include_sensitive"].default is True


def test_chat_include_sensitive_off_keeps_sensitive_records_out(client, family, monkeypatch):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "chat_include_sensitive", False)
    a, _, _ = family
    for title, kind, sens, text in [
        ("처방전", "처방전", "sensitive", "조제약 소염진통제"),
        ("10월 전기요금", "전기요금 고지서", "normal", "소염진통제와 무관한 청구 48,200원"),
    ]:
        r = client.post(
            "/ai-assistant/knowledge/items",
            json={"kind_label": kind, "title": title, "body_md": text, "sensitivity": sens},
            headers=a,
        )
        assert r.status_code == 201, r.text
    post = _fake_ai(monkeypatch, tool_query="소염진통제")
    allow_ai(client, a, monkeypatch)
    # 설정이 꺼져 있을 때 민감 기록이 Claude 로 가지 않는다
    assert client.post("/ai-assistant/chat", json={"message": "약"}, headers=a).status_code == 200
    sent = str(post.bodies)
    assert "조제약" not in sent and "처방전" not in sent.split("tool_result")[-1]


def test_other_family_records_never_reach_the_ai_or_the_answer(
    client, family, other_family, monkeypatch
):
    a, _, _ = family
    client.post(
        "/ai-assistant/knowledge/items",
        json={
            "kind_label": "전기요금 고지서",
            "title": "남의집 전기요금",
            "body_md": "VICTIM-9999",
        },
        headers=other_family,
    )
    client.post(
        "/ai-assistant/knowledge/items",
        json={"kind_label": "전기요금 고지서", "title": "우리집 전기요금", "body_md": "청구 111원"},
        headers=a,
    )
    post = _fake_ai(monkeypatch, tool_query="전기요금")
    allow_ai(client, a, monkeypatch)
    r = client.post("/ai-assistant/chat", json={"message": "전기요금"}, headers=a)
    assert r.status_code == 200
    sent = str(post.bodies)
    assert "우리집 전기요금" in sent  # 도구 결과에는 우리 가족 기록이 있다
    assert "남의집" not in sent and "VICTIM-9999" not in sent
    assert "남의집" not in r.text


def test_external_call_failure_is_503_and_logged_as_error_on_both_entries(
    client, family, monkeypatch
):
    import httpx

    from app.features.ai_assistant.knowledge import rag_chat

    a, _, _ = family
    _fake_ai(monkeypatch)
    allow_ai(client, a, monkeypatch)
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    errors = [
        httpx.ConnectError("boom"),
        httpx.HTTPStatusError(
            "429", request=request, response=httpx.Response(429, request=request)
        ),
    ]
    attempts = []

    def failing(body):
        attempts.append(1)
        raise errors[(len(attempts) - 1) % 2]

    monkeypatch.setattr(rag_chat, "_post", failing)
    for path, body, feature in ENTRIES:
        for _ in range(2):
            r = client.post(path, json=body, headers=a)
            assert r.status_code == 503 and r.json()["code"] == "llm_failed", path
        rows = _usage_rows(feature)
        assert [x.status for x in rows] == ["error", "error"]
        assert all(x.api_calls == 1 and x.error_code == "llm_failed" for x in rows)
    assert len(attempts) == 4  # 실패해도 다시 시도하지 않는다


def test_chat_is_busy_while_another_ai_request_holds_the_family_slot(client, family, monkeypatch):
    from datetime import UTC, datetime

    from app.shared.ai_usage import AiInflight
    from app.shared.db import SessionLocal

    a, _, group = family
    post = _fake_ai(monkeypatch)
    allow_ai(client, a, monkeypatch)
    with SessionLocal() as db:
        db.add(
            AiInflight(
                group_id=group["id"],
                slot=0,
                token="other",
                user_id="someone",
                feature="analysis",
                started_at=datetime.now(UTC),
            )
        )
        db.commit()
    r = client.post("/ai-assistant/chat", json={"message": "안녕"}, headers=a)
    assert r.status_code == 409 and r.json()["code"] == "ai_busy"
    assert post.bodies == []


def test_cooldown_applies_to_knowledge_ask(client, family, monkeypatch):

    a, _, _ = family
    post = _fake_ai(monkeypatch)
    allow_ai(client, a, monkeypatch)
    set_assistant_limits(monkeypatch, cooldown=60)
    path, body, _ = ENTRIES[1]
    assert client.post(path, json=body, headers=a).status_code == 200
    r = client.post(path, json=body, headers=a)
    assert r.status_code == 429 and r.json()["code"] == "ai_cooldown"
    assert len(post.bodies) == 1


def test_assistant_limits_are_separate_from_family_chat_ai_limits(client, family, monkeypatch):
    """어시스턴트는 쿨다운 없이 100회/일, 가족 채팅 AI 는 여전히 쿨다운·10회/일 — 서로 세지 않는다."""
    from app.features.ai_assistant import limits
    from app.shared import ai_guard
    from app.shared.config import settings

    a, _, _ = family
    assert (
        settings.ai_assistant_cooldown_seconds,
        settings.ai_assistant_max_calls_per_user_per_day,
        settings.ai_assistant_max_calls_per_group_per_day,
    ) == (0, 100, 300)
    assert (
        settings.ai_request_cooldown_seconds,
        settings.ai_max_calls_per_user_per_day,
        settings.ai_max_calls_per_group_per_day,
    ) == (30, 10, 30)
    limits.register()
    assert ai_guard.Limits(0, 100, 300) in [b[0] for b in ai_guard._BUCKETS.values()]
    post = _fake_ai(monkeypatch)
    allow_ai(client, a, monkeypatch)
    monkeypatch.setattr(settings, "ai_request_cooldown_seconds", 30)  # 가족 채팅 AI 쿨다운은 그대로
    for i in range(12):  # 쿨다운 없이 연속으로, 기본 한도 10 을 넘겨도 통과
        r = client.post("/ai-assistant/chat", json={"message": f"질문 {i}"}, headers=a)
        assert r.status_code == 200, (i, r.text)
    assert len(post.bodies) == 12
    # 어시스턴트 호출은 가족 채팅 AI 의 쿨다운·하루 한도 계산(기본 묶음)에 들어가지 않는다
    from datetime import UTC, datetime

    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        me = client.get("/family-group/me", headers=a).json()["id"]
        group_id = client.get("/family-group/groups/me", headers=a).json()["id"]
        assert ai_guard.usage_today(db, me, group_id) == (0, 0)
        ai_guard._check_cooldown(
            db, me, datetime.now(UTC), "analysis"
        )  # 기본 쿨다운 30초에도 걸리지 않는다


def test_assistant_daily_group_limit_code(client, family, monkeypatch):
    a, _, _ = family
    post = _fake_ai(monkeypatch)
    allow_ai(client, a, monkeypatch)
    set_assistant_limits(monkeypatch, per_user=100, per_group=1)
    assert client.post("/ai-assistant/chat", json={"message": "하나"}, headers=a).status_code == 200
    r = client.post("/ai-assistant/chat", json={"message": "둘"}, headers=a)
    assert r.status_code == 429 and r.json()["code"] == "ai_daily_limit_group"
    assert len(post.bodies) == 1
