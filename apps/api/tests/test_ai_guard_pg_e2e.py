"""AI 관문(app/shared/ai_guard.py)의 동시성을 PostgreSQL 16(최신 Alembic head)에서 검증한다 — 동시 실행 칸(기본키), 하루 한도, 캐시 고유 제약, 죽은 진행 표시.

Docker 가 필요하므로 GABEE_PG16_E2E=1 일 때만 실행한다. 임시 컨테이너만 쓰며 공용 DB·개인 DB·MVP DB 에는 접속하지 않는다.
Anthropic 은 부르지 않는다: app.shared.llm.client.complete_json 을 가짜로 바꾸고 호출 횟수를 스레드 안전하게 센다.
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.shared.config import settings
from app.shared.llm import client as llm
from tests import test_signup_pg_e2e as _base
from tests.test_schema_gate_pg_e2e import admin

rows = _base.rows
pg16 = _base.pg16  # 픽스처를 이 모듈에서도 쓰기 위해 이름을 다시 연결한다
pg_client = _base.pg_client

pytestmark = pytest.mark.skipif(
    os.environ.get("GABEE_PG16_E2E") != "1", reason="GABEE_PG16_E2E=1 일 때만 실행(Docker 필요)"
)

P = "/family-group"
AI = "/family-chat/ai"
PASSWORD = "Sunny-day-2026"
SECRET = "비밀대화원문표식"  # 메시지에만 들어가며 사용 기록·캐시에는 없어야 한다
FAKE_KEY = "test-key-not-real"


class FakeLLM:
    """complete_json 대용. 호출 수를 락으로 세고, delay 초 동안 느린 호출을 흉내 낸다."""

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self, prompt, schema, system=None, max_tokens=None):
        with self._lock:
            self.calls += 1
        time.sleep(self.delay)
        data = {
            "summary": "가족이 주말 계획을 이야기했어요.",
            "important_messages": [],
            "schedule_candidates": [],
            "todo_candidates": [],
        }
        return llm.JsonResult(data=data, input_tokens=100, output_tokens=20, model="fake-model")


@pytest.fixture
def fake(monkeypatch):
    def install(delay: float = 0.0) -> FakeLLM:
        f = FakeLLM(delay)
        monkeypatch.setattr(llm, "complete_json", f)
        return f

    monkeypatch.setattr(settings, "anthropic_api_key", FAKE_KEY)
    monkeypatch.setattr(settings, "ai_request_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "ai_max_concurrent_requests_per_group", 1)
    monkeypatch.setattr(settings, "ai_result_cache_ttl_seconds", 600)
    monkeypatch.setattr(settings, "ai_max_calls_per_user_per_day", 100)
    monkeypatch.setattr(settings, "ai_max_calls_per_group_per_day", 100)
    return install


def account(client, login_id):
    r = client.post(
        f"{P}/auth/signup",
        json={
            "login_id": login_id,
            "password": PASSWORD,
            "email": f"{login_id}@example.com",
            "name": login_id,
        },
    )
    assert r.status_code == 201, r.text
    token = client.post(
        f"{P}/auth/login", json={"login_id": login_id, "password": PASSWORD}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, r.json()["user"]["id"]


def post_message(client, headers, text):
    r = client.post("/family-chat/messages", json={"text": text}, headers=headers)
    assert r.status_code == 201, r.text


def family(client, tag="a", messages=4):
    """소유자·구성원 1명짜리 가족. AI 동의를 켜고 대화 messages 개를 남긴다."""
    owner, owner_id = account(client, f"own_{tag}")
    group = client.post(f"{P}/groups", json={"name": f"가족 {tag}"}, headers=owner).json()
    guest, guest_id = account(client, f"gst_{tag}")
    req = client.post(f"{P}/groups/join", json={"code": group["invite_code"]}, headers=guest).json()
    assert (
        client.post(f"{P}/groups/join-requests/{req['id']}/approve", headers=owner).status_code
        == 200
    )
    assert client.put(f"{AI}/settings", json={"enabled": True}, headers=owner).status_code == 200
    for i in range(messages):
        post_message(client, owner if i % 2 == 0 else guest, f"{SECRET} {tag} {i}")
    return owner, owner_id, guest, guest_id, group


def analyze(client, headers):
    r = client.post(f"{AI}/analysis", json={"limit": 100}, headers=headers)
    return r.status_code, r.json()


def parallel(fn, n):
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(fn, range(n)))


def test_eight_simultaneous_identical_requests_call_the_model_once(pg_client, fake):
    client, pg = pg_client
    f = fake(delay=1.0)
    owner, _, guest, _, _ = family(client)

    results = parallel(lambda i: analyze(client, owner if i % 2 == 0 else guest), 8)
    codes = [code for code, _ in results]
    assert all(code in (200, 409) for code in codes), results  # 500 이 없어야 한다
    assert 200 in codes
    assert all(body["code"] == "ai_busy" for code, body in results if code == 409), results
    assert f.calls == 1
    assert rows(pg, "SELECT count(*) FROM ai_inflight") == [(0,)]  # 진행 표시가 남지 않는다
    assert rows(pg, "SELECT coalesce(sum(api_calls), 0) FROM ai_usage_logs") == [(1,)]


def test_two_groups_do_not_block_each_other_and_stay_isolated(pg_client, fake):
    client, pg = pg_client
    f = fake(delay=1.0)
    owner_a, _, _, _, group_a = family(client, "a")
    owner_b, _, _, _, group_b = family(client, "b")

    results = parallel(lambda i: analyze(client, (owner_a, owner_b)[i]), 2)
    assert [code for code, _ in results] == [200, 200], results
    assert f.calls == 2  # 그룹마다 한 번씩
    for gid in (group_a["id"], group_b["id"]):
        assert rows(
            pg, "SELECT coalesce(sum(api_calls), 0) FROM ai_usage_logs WHERE group_id = %s", gid
        ) == [(1,)]
        assert rows(pg, "SELECT count(*) FROM ai_result_cache WHERE group_id = %s", gid) == [(1,)]
    assert rows(pg, "SELECT count(*) FROM ai_inflight") == [(0,)]


def test_two_slots_are_split_safely_by_the_primary_key(pg_client, fake, monkeypatch):
    client, pg = pg_client
    monkeypatch.setattr(settings, "ai_max_concurrent_requests_per_group", 2)
    f = fake(delay=1.5)
    owner, _, guest, _, _ = family(client)

    results = parallel(lambda i: analyze(client, (owner, guest, owner)[i]), 3)
    codes = sorted(code for code, _ in results)
    assert codes == [200, 200, 409], results  # 칸이 둘이므로 최대 2개만 호출한다
    assert f.calls == 2
    assert rows(pg, "SELECT count(*) FROM ai_inflight") == [(0,)]
    assert rows(pg, "SELECT coalesce(sum(api_calls), 0) FROM ai_usage_logs") == [(2,)]


def test_daily_user_limit_allows_exactly_three_calls(pg_client, fake, monkeypatch):
    client, pg = pg_client
    monkeypatch.setattr(settings, "ai_max_calls_per_user_per_day", 3)
    f = fake()
    owner, owner_id, _, _, _ = family(client)

    outcomes = []
    for i in range(5):
        post_message(client, owner, f"{SECRET} 추가 {i}")  # 분석 범위가 바뀌어 캐시를 피한다
        outcomes.append(analyze(client, owner))
    assert [code for code, _ in outcomes] == [200, 200, 200, 429, 429], outcomes
    assert all(body["code"] == "ai_daily_limit_user" for code, body in outcomes if code == 429)
    assert f.calls == 3
    assert rows(
        pg, "SELECT coalesce(sum(api_calls), 0) FROM ai_usage_logs WHERE user_id = %s", owner_id
    ) == [(3,)]


def test_concurrent_cache_saves_leave_exactly_one_row(pg_client, fake, monkeypatch):
    client, pg = pg_client
    monkeypatch.setattr(settings, "ai_max_concurrent_requests_per_group", 2)
    f = fake(delay=1.0)  # 두 요청이 같은 시각에 같은 결과를 저장하려고 겨룬다
    owner, _, guest, _, group = family(client)

    results = parallel(lambda i: analyze(client, (owner, guest)[i]), 2)
    assert [code for code, _ in results] == [200, 200], results
    assert f.calls == 2
    assert rows(
        pg,
        "SELECT count(*) FROM ai_result_cache WHERE group_id = %s AND feature = 'analysis'",
        group["id"],
    ) == [(1,)]
    assert rows(
        pg,
        "SELECT count(*) FROM (SELECT 1 FROM ai_result_cache "
        "GROUP BY group_id, feature, cache_key HAVING count(*) > 1) d",
    ) == [(0,)]
    # 저장된 캐시로 다음 요청은 호출 없이 응답한다
    code, body = analyze(client, owner)
    assert code == 200 and body["meta"]["cached"] is True and f.calls == 2


def test_stale_inflight_marker_is_cleaned_and_fresh_one_blocks(pg_client, fake):
    client, pg = pg_client
    f = fake()
    owner, owner_id, _, _, group = family(client)

    def mark(age_seconds):
        with admin(pg) as c:
            c.execute("DELETE FROM ai_inflight")
            c.execute(
                "INSERT INTO ai_inflight (group_id, slot, token, user_id, feature, started_at) "
                "VALUES (%s, 0, 'stale-test-token', %s, 'analysis', now() - make_interval(secs => %s))",
                (group["id"], owner_id, age_seconds),
            )

    mark(5)  # 방금 시작된 진행 표시 — 살아 있다고 보고 막는다
    code, body = analyze(client, owner)
    assert (code, body["code"]) == (409, "ai_busy")
    assert f.calls == 0

    mark(settings.ai_inflight_stale_seconds + 600)  # 죽은 진행 표시 — 치우고 진행한다
    code, _ = analyze(client, owner)
    assert code == 200
    assert f.calls == 1
    assert rows(pg, "SELECT count(*) FROM ai_inflight") == [(0,)]


def test_usage_and_cache_tables_hold_no_conversation_text(pg_client, fake, monkeypatch):
    client, pg = pg_client
    fake()
    owner, _, guest, _, _ = family(client)
    assert analyze(client, owner)[0] == 200
    assert analyze(client, guest)[0] == 200  # 캐시 적중 기록도 남긴다
    assert rows(pg, "SELECT count(*) FROM ai_usage_logs") == [(2,)]
    assert rows(pg, "SELECT count(*) FROM ai_result_cache") == [(1,)]

    columns = rows(
        pg,
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND left(table_name, 3) = 'ai_' "
        "AND data_type IN ('text', 'character varying', 'json', 'jsonb')",
    )
    assert columns  # 검사 대상 칼럼이 실제로 있다
    for table, column in columns:
        sql = f'SELECT count(*) FROM "{table}" WHERE "{column}"::text LIKE %s OR "{column}"::text LIKE %s'
        assert rows(pg, sql, f"%{SECRET}%", f"%{FAKE_KEY}%") == [(0,)], (table, column)
