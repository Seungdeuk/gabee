"""정산·돌봄 탭 에이전트의 chat → confirm 흐름을 실제 PostgreSQL 과 실제 HTTP 로 끝까지 확인한다.

    cd apps/api && python -m scripts.e2e_tab_agents [--keep] [--database-url URL]

- 일회용 PostgreSQL 컨테이너(pgvector/pgvector:pg16, 127.0.0.1:55432)를 띄우고 `alembic upgrade head` 로 처음부터 만든다.
  개인 로컬 DB·팀 공용 DB·MVP DB 에는 연결하지 않는다. 끝나면 컨테이너를 지운다(--keep 이면 남긴다).
  --database-url 은 이미 떠 있는 **빈 임시** PostgreSQL 을 직접 쓰려고 할 때만 쓴다(localhost/127.0.0.1 만 허용).
- uvicorn 을 이 프로세스 안에서 실제 포트(127.0.0.1:8399)로 띄우고 httpx 로 호출한다.
- 모델 호출은 가짜(스크립트로 정한 도구 호출)로 바꿔서 ANTHROPIC_API_KEY 도 필요 없고 외부 전송도 없다.
  모델이 어떤 도구를 고르는지는 evals/tab_agents 가 따로 본다. 여기서는 서버·DB·권한·토큰의 연결을 본다.
- 데이터는 모두 가짜(지민·수진·남)다. 실패한 확인이 하나라도 있으면 종료 코드 1."""

import argparse
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

CONTAINER = "gabee-e2e-pg"
PG_PORT = 55432
HTTP_PORT = 8399
BASE = f"http://127.0.0.1:{HTTP_PORT}"
API_DIR = Path(__file__).resolve().parent.parent
DB_USER = DB_NAME = DB_PASSWORD = "gabee_e2e"
DEFAULT_URL = f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}@127.0.0.1:{PG_PORT}/{DB_NAME}"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def start_postgres() -> None:
    _docker("rm", "-f", CONTAINER, check=False)
    _docker(
        "run", "-d", "--name", CONTAINER,
        "-e", f"POSTGRES_USER={DB_USER}", "-e", f"POSTGRES_PASSWORD={DB_PASSWORD}",
        "-e", f"POSTGRES_DB={DB_NAME}",
        "-p", f"127.0.0.1:{PG_PORT}:5432",
        "pgvector/pgvector:pg16",
    )  # fmt: skip
    for _ in range(60):
        r = _docker("exec", CONTAINER, "pg_isready", "-U", DB_USER, "-d", DB_NAME, check=False)
        if r.returncode == 0:
            time.sleep(1)  # 초기화 중 한 번 내려갔다 올라오는 구간을 지난다
            if _docker("exec", CONTAINER, "pg_isready", "-U", DB_USER, check=False).returncode == 0:
                return
        time.sleep(1)
    raise SystemExit("PostgreSQL 컨테이너가 준비되지 않았어요")


def stop_postgres() -> None:
    _docker("rm", "-f", "-v", CONTAINER, check=False)


def fake_llm(body: dict) -> dict:
    """스크립트로 정한 모델: 사용자가 '등록'을 말하면 지출 제안, '식단 기록'이면 식사 제안, 도구 결과를 받으면 마무리 문장."""
    last = body["messages"][-1]
    if isinstance(last["content"], list):  # tool_result 를 받은 뒤
        return {"content": [{"type": "text", "text": "제안을 만들었어요. 확인을 눌러 주세요."}]}
    names = {t["name"] for t in body["tools"]}
    text = last["content"]
    if "propose_add_expense" in names and "등록" in text:
        call = ("propose_add_expense", {"title": "치과", "amount": 50000, "date": "2026-10-12"})
    elif "propose_record_meal" in names and "식단 기록" in text:
        call = ("propose_record_meal", {"date": "2026-10-12", "meal": "lunch", "menu": "된장찌개"})
    else:
        return {"content": [{"type": "text", "text": "알겠어요."}]}
    return {
        "content": [{"type": "tool_use", "id": "tu1", "name": call[0], "input": call[1]}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


class Report:
    def __init__(self) -> None:
        self.failed = 0

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
        self.failed += 0 if ok else 1


def run_flow(report: Report) -> None:
    import httpx

    from tests.helpers import join_family, signup

    check = report.check
    with httpx.Client(base_url=BASE, timeout=30) as c:
        check("health", c.get("/health").status_code == 200)
        a = signup(c, "지민")
        group = c.post("/family-group/groups", json={"name": "e2e 가족"}, headers=a).json()
        b = signup(c, "수진")
        join_family(c, a, group["invite_code"], b)
        outsider = signup(c, "남")
        c.post("/family-group/groups", json={"name": "다른 가족"}, headers=outsider)

        r = c.post("/billing/agent/chat", json={"message": "치과 50000원 지출 등록해줘"}, headers=a)
        check("AI 동의가 꺼져 있으면 403 ai_not_enabled", r.status_code == 403, r.text)
        r = c.put("/family-chat/ai/settings", json={"enabled": True}, headers=a)
        check("가족 AI 켜기", r.status_code == 200, r.text)

        # --- 정산: 제안 → 확인 → 저장
        r = c.post("/billing/agent/chat", json={"message": "치과 50000원 지출 등록해줘"}, headers=a)
        body = r.json() if r.status_code == 200 else {}
        proposals = body.get("proposals") or []
        check("정산 chat 200 + 제안 1건", r.status_code == 200 and len(proposals) == 1, r.text)
        expenses = c.get("/billing/expenses", params={"month": "2026-10"}, headers=a).json()
        check("제안만으로는 저장되지 않음", expenses == [], str(expenses))
        if not proposals:
            return
        token = proposals[0]["token"]

        r = c.post("/billing/agent/confirm", json={"token": token}, headers=b)
        check("다른 사람(수진)의 확인은 거절 400", r.status_code == 400, r.text)
        r = c.post("/billing/agent/confirm", json={"token": token[:-3] + "xyz"}, headers=a)
        check("위조한 토큰 거절 400", r.status_code == 400, r.text)
        r = c.post("/billing/agent/confirm", json={"token": token}, headers=outsider)
        check("다른 가족의 확인은 거절 400", r.status_code == 400, r.text)

        r = c.post("/billing/agent/confirm", json={"token": token}, headers=a)
        check("본인 확인 200 ok", r.status_code == 200 and r.json().get("ok") is True, r.text)
        expenses = c.get("/billing/expenses", params={"month": "2026-10"}, headers=a).json()
        check(
            "확인 뒤 지출 1건 저장(낸 사람=확인한 사용자)",
            len(expenses) == 1
            and expenses[0]["amount"] == 50000
            and expenses[0]["title"] == "치과",
            str(expenses),
        )
        r = c.post("/billing/agent/confirm", json={"token": token}, headers=a)
        check("같은 토큰 재사용 409 proposal_used", r.status_code == 409, r.text)
        expenses = c.get("/billing/expenses", params={"month": "2026-10"}, headers=a).json()
        check("재사용해도 지출은 늘지 않음", len(expenses) == 1, str(expenses))

        # --- 조회 도구 없이 제안 안 만드는 일반 질문
        r = c.post("/billing/agent/chat", json={"message": "안녕"}, headers=a)
        check(
            "일반 대화는 제안 없음",
            r.status_code == 200 and r.json().get("proposals") == [],
            r.text,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--keep", action="store_true", help="끝나도 PostgreSQL 컨테이너를 지우지 않는다"
    )
    parser.add_argument("--database-url", help="이미 떠 있는 빈 임시 PostgreSQL(localhost 만)")
    args = parser.parse_args()
    url = args.database_url or DEFAULT_URL
    if not any(h in url for h in ("@localhost", "@127.0.0.1")):
        print("임시 로컬 PostgreSQL 만 쓸 수 있어요(localhost/127.0.0.1).")
        return 2
    if socket.socket().connect_ex(("127.0.0.1", HTTP_PORT)) == 0:
        print(f"포트 {HTTP_PORT} 가 이미 사용 중이에요.")
        return 2

    os.environ["DATABASE_URL"] = url
    os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)  # PostgreSQL 에서는 서명 키가 있어야 한다
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="gabee-e2e-")
    os.environ.pop("ANTHROPIC_API_KEY", None)  # 키가 있어도 쓰지 않게 한다(모델은 가짜)
    os.chdir(API_DIR)
    sys.path.insert(0, str(API_DIR))

    own_container = not args.database_url
    report = Report()
    try:
        if own_container:
            print("PostgreSQL 컨테이너 시작…")
            start_postgres()
        print("alembic upgrade head…")
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)

        import uvicorn

        from app.main import app
        from app.shared.config import settings
        from app.shared.llm import agent

        settings.anthropic_api_key = "e2e-fake"  # 가짜 모델을 쓰도록 키 확인만 통과시킨다
        settings.ai_request_cooldown_seconds = 0
        agent._post = fake_llm  # run_agent 기본 post: 실제 API 호출 대신 가짜 모델

        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=HTTP_PORT, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.1)
        else:
            print("서버가 시작되지 않았어요.")
            return 1
        try:
            run_flow(report)
        finally:
            server.should_exit = True
            thread.join(timeout=10)
    finally:
        if own_container and not args.keep:
            stop_postgres()
    print(f"\n{'통과' if report.failed == 0 else f'실패 {report.failed}건'}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
