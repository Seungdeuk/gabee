"""통합관리자 챗봇: 관리자만, 키 없음, 실패. 시험에서는 실제 AI 를 부르지 않는다."""

import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.features.admin_knowledge import live, service
from app.features.ops_admin import admin_facts as ops_facts
from app.features.service_admin import admin_facts as service_admin_facts
from app.shared import admin_facts
from app.shared.config import settings
from app.shared.db import SessionLocal

PASSWORD = "Sunny-day-2026"
ASK = "/admin/knowledge/ask"


def _login(client) -> tuple[dict, str]:
    body = {
        "login_id": "jimin_kim",
        "password": PASSWORD,
        "email": "jimin_kim@example.com",
        "name": "김지민",
    }
    assert client.post("/family-group/auth/signup", json=body).status_code == 201
    r = client.post(
        "/family-group/auth/login", json={"login_id": "jimin_kim", "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]["id"]


@pytest.fixture
def admin(client, monkeypatch) -> dict:
    headers, user_id = _login(client)
    monkeypatch.setattr(settings, "admin_user_ids", user_id)
    return headers


def _fake_llm(monkeypatch, reply="아니요. 알림은 가지 않습니다."):
    """첫 호출은 도구를 모두 부르고(나가는 글을 다 검사하려고), 다음 호출에서 답한다."""
    seen = {"calls": 0}

    def post(body):
        if isinstance(reply, Exception):
            raise reply
        seen["calls"] += 1
        seen["system"] = body["system"]
        seen["tools"] = [t["name"] for t in body["tools"]]
        seen["prompt"] = json.dumps(body["messages"], ensure_ascii=False)
        if seen["calls"] == 1:
            calls = [
                {"type": "tool_use", "id": f"t{i}", "name": t["name"], "input": {}}
                for i, t in enumerate(body["tools"])
            ]
            return {"content": calls}
        return {"content": [{"type": "text", "text": reply}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(service, "_post", post)
    return seen


def _read_all(db) -> str:
    return "\n".join(t.invoke({}) for t in live.tools(db))


def test_needs_login_and_admin_list(client, monkeypatch):
    assert client.post(ASK, json={"q": "공지"}).status_code == 401
    headers, _ = _login(client)
    monkeypatch.setattr(settings, "admin_user_ids", "")
    r = client.post(ASK, json={"q": "공지"}, headers=headers)
    assert r.status_code == 403 and r.json()["code"] == "operator_required"


def test_sends_question_with_faq_to_claude(client, admin, monkeypatch):
    seen = _fake_llm(monkeypatch)
    r = client.post(ASK, json={"q": "공지 올리면 알림이 가?"}, headers=admin)
    assert r.status_code == 200 and r.json() == {"answer": "아니요. 알림은 가지 않습니다."}
    assert "공지 올리면 알림이 가?" in seen["prompt"]
    assert "전체 회원:" in seen["prompt"]  # 도구 결과가 Claude 에게 간다
    assert "공지 올리면 사용자에게 알림이 가?" in seen["system"]  # faq.md 를 함께 준다
    assert "일상 질문" in seen["system"]


def test_without_key_says_so(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    r = client.post(ASK, json={"q": "공지 알림"}, headers=admin)
    assert r.status_code == 503 and r.json()["code"] == "ai_key_missing"


def test_call_failure_is_503(client, admin, monkeypatch):
    _fake_llm(monkeypatch, service.llm.LLMUnavailable("실패"))
    r = client.post(ASK, json={"q": "공지 알림"}, headers=admin)
    assert r.status_code == 503 and r.json()["code"] == "llm_failed"


def test_numbers_match_the_admin_screen(client, admin):
    screen = client.get("/admin/service/groups", headers=admin).json()
    members = client.get("/admin/service/members", headers=admin).json()
    with SessionLocal() as db:
        text = _read_all(db)
    assert f"가족 그룹: {screen['total']}개" in text
    assert f"구성원이 1명뿐인 가족: {screen['single_member']}곳" in text
    assert f"전체 회원: {members['total']}명" in text


def test_personal_data_is_not_sent_to_claude(client, admin, monkeypatch):
    seen = _fake_llm(monkeypatch)
    client.post("/family-group/groups", json={"name": "비밀스러운가족"}, headers=admin)
    me = client.get("/admin/service/me", headers=admin).json()
    r = client.post(ASK, json={"q": "가족 몇 개야?"}, headers=admin)
    assert r.status_code == 200
    for secret in ("비밀스러운가족", "김지민", "jimin_kim", "@example.com", me["id"]):
        assert secret not in seen["prompt"]


def test_error_message_and_trace_id_are_not_sent(monkeypatch):
    item = SimpleNamespace(
        event_type="KeyError",
        method="GET",
        route="/notices",
        status=500,
        occurrences=3,
        kind="server_error",
        message="비밀 메시지",
        last_trace_id="trace123",
    )
    out = SimpleNamespace(errors_enabled=True, items=[item])
    monkeypatch.setattr(ops_facts.query_service, "errors", lambda *a: out)
    lines = ops_facts.errors(None)
    assert "KeyError" in lines[0] and "/notices" in lines[0] and "3회" in lines[0]
    assert "비밀 메시지" not in lines[0] and "trace123" not in lines[0]


def test_collection_off_is_not_reported_as_zero(client, admin):
    with SessionLocal() as db:
        text = _read_all(db)
    assert "수집이 꺼져 있어" in text
    assert "5xx 오류: 0건" not in text


def test_one_failed_section_does_not_stop_the_rest(client, admin, monkeypatch):
    def boom(db):
        raise RuntimeError("표 없음")

    members = admin_facts._FACTS["members"]
    monkeypatch.setitem(admin_facts._FACTS, "members", replace(members, read=boom))
    with SessionLocal() as db:
        text = _read_all(db)
    assert "확인할 수 없음" in text and "가족 그룹:" in text


def test_tools_are_the_registered_list():
    """챗봇은 다른 기능을 직접 부르지 않고 명단의 도구만 쓴다."""
    text = open(live.__file__, encoding="utf-8").read()
    assert "app.features." not in text
    names = [f.name for f in admin_facts.all_facts()]
    assert names == [
        "members",
        "members_daily",
        "groups",
        "support",
        "ai_usage",
        "server_requests",
        "server_errors",
        "data_analysis",
    ]
    for fact in admin_facts.all_facts():
        assert re.fullmatch(r"[a-z_]+", fact.name) and fact.description


def test_claude_gets_tools_and_the_answer_comes_after_them(client, admin, monkeypatch):
    seen = _fake_llm(monkeypatch, "지난주보다 줄었어요.")
    r = client.post(ASK, json={"q": "왜 줄었어?"}, headers=admin)
    assert r.status_code == 200 and r.json() == {"answer": "지난주보다 줄었어요."}
    assert seen["calls"] == 2 and "ai_usage" in seen["tools"]


def test_endless_tool_calls_stop_at_the_limit(client, admin, monkeypatch):
    count = {"n": 0}

    def post(body):
        count["n"] += 1
        return {"content": [{"type": "tool_use", "id": "t", "name": "members", "input": {}}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(service, "_post", post)
    r = client.post(ASK, json={"q": "회원 몇 명이야?"}, headers=admin)
    assert r.status_code == 503 and r.json()["code"] == "llm_failed"
    assert count["n"] == service.ASK_MAX_STEPS


def test_analytics_numbers_match_the_screen_and_hide_family_names(client, admin, monkeypatch):
    seen = _fake_llm(monkeypatch)
    client.post("/family-group/groups", json={"name": "비밀스러운가족"}, headers=admin)
    screen = client.get("/admin/service/analytics", headers=admin).json()
    first = screen["retention"][0]
    r = client.post(ASK, json={"q": "코호트 알려줘"}, headers=admin)
    assert r.status_code == 200
    assert f"재방문 코호트 {first['week_start']} 주: 가입 {first['size']}명" in seen["prompt"]
    for secret in ("비밀스러운가족", "김지민", "jimin_kim"):
        assert secret not in seen["prompt"]


def test_daily_numbers_match_the_member_cards(client, admin):
    screen = client.get("/admin/service/members", headers=admin).json()
    with SessionLocal() as db:
        lines = service_admin_facts.daily_members(db)
    today = (datetime.now(UTC) + timedelta(hours=settings.ai_day_utc_offset_hours)).date()
    assert len(lines) == len(screen["daily_joined"])
    assert lines[-1].startswith(f"일별 회원 {today}: 가입 {screen['daily_joined'][-1]}명")
    assert f"전체 회원 {screen['daily_total'][-1]}명" in lines[-1]


def test_runs_on_langgraph_with_langchain_tools(client, admin):
    """도구는 랭체인 도구이고, 반복은 랭그래프의 model ↔ tools 두 노드다."""
    from langchain_core.tools import BaseTool

    from app.features.admin_knowledge import graph

    with SessionLocal() as db:
        assert all(isinstance(t, BaseTool) for t in live.tools(db))
    assert {"model", "tools"} <= set(graph.GRAPH.get_graph().nodes)


def _kst_today():
    return (datetime.now(UTC) + timedelta(hours=settings.ai_day_utc_offset_hours)).date()


def test_daily_tools_take_a_date_range(client, admin):
    """날짜 도구는 start·end 입력칸이 있고, 다른 도구는 입력이 없다."""
    from app.features.admin_knowledge import graph

    with SessionLocal() as db:
        props = {t.name: graph.spec(t)["input_schema"]["properties"] for t in live.tools(db)}
    assert set(props["members_daily"]) == {"start", "end"}
    assert set(props["ai_usage"]) == {"start", "end"}
    assert props["members"] == {} and props["groups"] == {}


def test_members_daily_returns_only_the_asked_days(client, admin):
    today = _kst_today()
    first = today - timedelta(days=2)
    screen = client.get("/admin/service/members", headers=admin).json()
    with SessionLocal() as db:
        lines = service_admin_facts.daily_members(db, start=str(first), end=str(today))
    assert lines[0] == f"회원 {first} ~ {today} 가입 합계: {sum(screen['daily_joined'][-3:])}명"
    assert [line.split(":")[0] for line in lines[1:]] == [
        f"일별 회원 {first + timedelta(days=i)}" for i in range(3)
    ]
    assert lines[-1].startswith(f"일별 회원 {today}: 가입 {screen['daily_joined'][-1]}명")


def test_members_daily_can_go_further_back_than_the_screen(client, admin):
    """화면은 30일까지지만 챗봇은 기간을 주면 더 옛날 날짜도 센다."""
    today = _kst_today()
    first, last = today - timedelta(days=60), today - timedelta(days=40)
    with SessionLocal() as db:
        lines = service_admin_facts.daily_members(db, start=str(first), end=str(last))
    assert len(lines) == 1 + 21 and lines[1].startswith(f"일별 회원 {first}:")


def test_ai_usage_range_matches_the_screen(client, admin):
    today = _kst_today()
    first = today - timedelta(days=6)
    screen = client.get("/admin/service/ai-usage", headers=admin).json()
    with SessionLocal() as db:
        lines = service_admin_facts.ai(db, start=str(first), end=str(today))
    assert lines[0] == f"AI 요청 {first} ~ {today} 합계: {sum(screen['daily'][-7:])}회"
    assert len(lines) == 1 + 7


@pytest.mark.parametrize(
    ("start", "end", "says"),
    [
        ("2026/10/03", None, "YYYY-MM-DD"),
        ("2026-10-10", "2026-10-03", "시작 날짜가 끝 날짜보다 늦어요"),
        (None, "2999-01-01", "보다 뒤의 날짜는 셀 수 없어요"),
        ("2026-01-01", "2026-06-30", f"최대 {admin_facts.MAX_RANGE_DAYS}일"),
    ],
)
def test_bad_date_range_is_explained_not_counted(client, admin, start, end, says):
    """Claude 가 채운 날짜도 서버가 다시 검사하고, 잘못되면 숫자 대신 안내를 돌려준다."""
    with SessionLocal() as db:
        for read in (service_admin_facts.daily_members, service_admin_facts.ai):
            lines = read(db, start=start, end=end)
            assert len(lines) == 1 and says in lines[0]


def test_claude_can_ask_for_a_period(client, admin, monkeypatch):
    """Claude 가 도구 입력에 기간을 넣으면 그 기간 숫자가 Claude 에게 간다."""
    today = _kst_today()
    first = today - timedelta(days=1)
    seen = {"calls": 0}

    def post(body):
        seen["calls"] += 1
        if seen["calls"] == 1:
            call = {"start": str(first), "end": str(today)}
            return {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "members_daily", "input": call}
                ]
            }
        seen["prompt"] = json.dumps(body["messages"], ensure_ascii=False)
        return {"content": [{"type": "text", "text": "이틀 동안 1명 가입했어요."}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(service, "_post", post)
    r = client.post(ASK, json={"q": "어제부터 오늘까지 가입자"}, headers=admin)
    assert r.status_code == 200, r.text
    assert f"회원 {first} ~ {today} 가입 합계" in seen["prompt"]
    assert f"일별 회원 {today - timedelta(days=2)}" not in seen["prompt"]


def test_faq_says_daily_views_exist():
    assert "일 단위로도 볼 수 있습니다" in service.FAQ


def test_langsmith_is_off_by_default(monkeypatch):
    """켜기 스위치가 꺼져 있으면 키가 있어도 기록 장치를 붙이지 않는다."""
    from app.features.admin_knowledge import graph

    monkeypatch.setattr(settings, "admin_langsmith_enabled", False)
    monkeypatch.setattr(settings, "admin_langsmith_api_key", "ls-test-key")
    assert graph._callbacks() == []
    monkeypatch.setattr(settings, "admin_langsmith_enabled", True)
    monkeypatch.setattr(settings, "admin_langsmith_api_key", "")
    assert graph._callbacks() == []


def test_langsmith_tracer_goes_to_the_admin_project(monkeypatch):
    from langchain_core.tracers.langchain import LangChainTracer

    from app.features.admin_knowledge import graph

    monkeypatch.setattr(settings, "admin_langsmith_enabled", True)
    monkeypatch.setattr(settings, "admin_langsmith_api_key", "ls-test-key")
    monkeypatch.setattr(settings, "admin_langsmith_project", "gabee-admin-test")
    (tracer,) = graph._callbacks()
    assert isinstance(tracer, LangChainTracer) and tracer.project_name == "gabee-admin-test"


def test_trace_covers_the_model_and_tool_calls(client, admin, monkeypatch):
    """기록 장치가 붙으면 그래프 실행, 모델 호출, 도구 호출이 모두 잡힌다(실제 랭스미스로는 보내지 않는다)."""
    from langchain_core.callbacks import BaseCallbackHandler

    from app.features.admin_knowledge import graph

    class Recorder(BaseCallbackHandler):
        def __init__(self):
            self.chains, self.models, self.tools = [], 0, []

        def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kw):
            if parent_run_id is None:
                self.chains.append(kw.get("name"))

        def on_chat_model_start(self, serialized, messages, **kw):
            self.models += 1

        def on_tool_start(self, serialized, input_str, **kw):
            self.tools.append(serialized.get("name"))

    rec = Recorder()
    monkeypatch.setattr(graph, "_callbacks", lambda: [rec])
    _fake_llm(monkeypatch, "기록됐어요.")
    r = client.post(ASK, json={"q": "회원 몇 명이야?"}, headers=admin)
    assert r.status_code == 200
    assert rec.chains == [graph.RUN_NAME]
    assert rec.models == 2 and "members" in rec.tools


def test_stream_chat_reports_steps_in_order(client):
    """단계 소식: 질문 이해 → 도구마다 화면용 이름 → 답 작성. 내부 도구 이름·숫자·답은 소식에 없다."""
    from langchain_core.messages import HumanMessage

    from app.features.admin_knowledge import graph
    from app.shared.llm.chat_model import PostChatModel

    calls = {"n": 0}

    def post(body):
        calls["n"] += 1
        if calls["n"] == 1:
            uses = [
                {"type": "tool_use", "id": "a", "name": "members", "input": {}},
                {"type": "tool_use", "id": "b", "name": "no_such_tool", "input": {}},
            ]
            return {"content": uses}
        return {"content": [{"type": "text", "text": "회원은 **1명**이에요."}]}

    with SessionLocal() as db:
        tool_list = live.tools(db)
        model = PostChatModel(
            post=post,
            llm_model="test",
            max_tokens=100,
            system="",
            tools=[graph.spec(t) for t in tool_list],
        )
        run = graph.Run(model=model, tools={t.name: t for t in tool_list}, max_steps=4)
        events = list(graph.stream_chat(run, [HumanMessage(content="회원 몇 명이야?")]))

    assert events == [
        {"step": "understand"},
        {"step": "tool", "label": "회원 수 확인"},  # 없는 도구(no_such_tool)는 알리지 않는다
        {"step": "write"},
    ]
    assert run.answer == "회원은 **1명**이에요."
    assert "members" not in json.dumps(events, ensure_ascii=False)


def test_every_tool_has_a_screen_label():
    """도구를 새로 올릴 때 화면용 이름을 빠뜨리면 내부 이름이 화면에 보인다."""
    for fact in admin_facts.all_facts():
        assert fact.label != fact.name, f"{fact.name} 에 label 이 없어요"


STREAM = "/admin/knowledge/ask/stream"


def _events(r) -> list[dict]:
    """SSE 본문을 소식 목록으로 바꾼다."""
    assert r.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def test_stream_needs_login_and_admin_list(client):
    assert client.post(STREAM, json={"q": "공지"}).status_code == 401
    headers, _ = _login(client)
    assert client.post(STREAM, json={"q": "공지"}, headers=headers).status_code == 403


def test_stream_sends_steps_then_the_answer(client, admin, monkeypatch):
    seen = _fake_llm(monkeypatch, "전체 회원은 **1명**이에요.")
    r = client.post(STREAM, json={"q": "회원 몇 명이야? 연락처 010-1234-5678"}, headers=admin)
    assert r.status_code == 200
    events = _events(r)
    steps = [e["step"] for e in events]
    assert steps[:3] == ["received", "masked", "understand"]
    assert steps[-2:] == ["write", "answer"]
    labels = [e["label"] for e in events if e["step"] == "tool"]
    assert "회원 수 확인" in labels and "서버 오류 확인" in labels
    assert events[-1]["answer"] == "전체 회원은 **1명**이에요."
    # 스트림 중에도 DB 연결이 살아 있어 숫자를 읽었다(못 읽으면 "확인할 수 없음")
    assert "전체 회원 1명" in seen["prompt"] and live.UNKNOWN not in seen["prompt"]
    # Claude 에게는 가린 질문이 가고, 브라우저로 가는 소식에는 질문·도구 숫자·내부 도구 이름이 없다
    assert "1234-5678" not in seen["prompt"]
    body = r.text
    for secret in ("010-1234-5678", "연락처", "전체 회원 1명", '"members"', "jimin_kim"):
        assert secret not in body.replace(events[-1]["answer"], "")


def test_stream_same_answer_as_ask(client, admin, monkeypatch):
    _fake_llm(monkeypatch, "같은 답이에요.")
    plain = client.post(ASK, json={"q": "회원 몇 명이야?"}, headers=admin).json()["answer"]
    _fake_llm(monkeypatch, "같은 답이에요.")
    streamed = _events(client.post(STREAM, json={"q": "회원 몇 명이야?"}, headers=admin))
    assert streamed[-1] == {"step": "answer", "answer": plain}


def test_stream_failure_ends_with_an_error_event(client, admin, monkeypatch):
    import httpx

    _fake_llm(monkeypatch, httpx.ConnectError("down"))
    r = client.post(STREAM, json={"q": "회원 몇 명이야?"}, headers=admin)
    assert r.status_code == 200  # 소식을 보내기 시작한 뒤라 상태 코드는 이미 200 이다
    events = _events(r)
    assert [e["step"] for e in events] == ["received", "masked", "understand", "error"]
    assert events[-1]["code"] == "llm_failed" and "down" not in r.text


def test_stream_without_key_is_503_before_any_event(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    r = client.post(STREAM, json={"q": "회원 몇 명이야?"}, headers=admin)
    assert r.status_code == 503 and r.json()["code"] == "ai_key_missing"


def test_faq_tells_where_the_support_tab_is(client, admin, monkeypatch):
    """ "문의는 어느 탭이야?" 에 답할 자료(메뉴 묶음·탭 이름)가 지시에 들어간다."""
    seen = _fake_llm(monkeypatch)
    assert client.post(ASK, json={"q": "문의는 무슨 탭이야?"}, headers=admin).status_code == 200
    assert "## 문의는 어느 탭이야?" in seen["system"]
    assert '"운영 업무" 묶음의 "문의 및 신고" 탭' in seen["system"]
