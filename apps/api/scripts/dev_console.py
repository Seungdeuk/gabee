"""가계·돌봄 기능을 눈으로 확인하는 테스트용 서버. 운영 코드(app.main)는 건드리지 않는다.

    cd apps/api
    PYTHONPATH=. python scripts/dev_console.py [--port 8000] [--host 0.0.0.0]

실행할 때마다 `data/dev-console.db` 를 지우고 가짜 가족(엄마·지민·수진)과 예시 지출을 새로 만든다.
토큰이 `/console/session` 으로 그대로 나가므로 로컬 테스트 전용이다. 실제 데이터를 넣지 않는다.
"""

import argparse
import os
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent
DB_FILE = API_DIR / "data" / "dev-console.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_FILE.as_posix()}"
os.environ["ANTHROPIC_API_KEY"] = ""

import uvicorn  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.shared.db import engine  # noqa: E402

DEMO_USERS = (("엄마", "parent"), ("지민", "child"), ("수진", "child"))
DEMO_USER_INFO: list[dict] = []


def _seed() -> None:
    """가짜 가족과 예시 지출 몇 건을 만든다."""
    with TestClient(app) as c:
        tokens = []
        for name, role in DEMO_USERS:
            r = c.post("/family-group/users", json={"name": name, "role": role}).json()
            tokens.append({"id": r["user"]["id"], "name": name, "role": role, "token": r["token"]})
        owner = {"X-Gyeot-Token": tokens[0]["token"]}
        group = c.post(
            "/family-group/groups", json={"name": "우리 가족(예시)"}, headers=owner
        ).json()
        for t in tokens[1:]:
            # 익명 계정도 가입 요청 → 소유자(엄마) 승인을 거친다
            joined = c.post(
                "/family-group/groups/join",
                json={"code": group["invite_code"]},
                headers={"X-Gyeot-Token": t["token"]},
            )
            req_id = joined.json().get("id") if joined.status_code == 200 else None
            approved = (
                c.post(f"/family-group/groups/join-requests/{req_id}/approve", headers=owner)
                if req_id
                else None
            )
            if approved is None or approved.status_code != 200:
                raise SystemExit(
                    f"!!! 데모 시드 실패: {t['name']} 가입/승인 실패 "
                    f"(join={joined.status_code} {joined.text}, "
                    f"approve={approved.status_code if approved is not None else None})"
                )
        ids = {t["name"]: t["id"] for t in tokens}
        by_name = {t["name"]: t for t in tokens}
        month = c.get("/billing/settlement", headers=owner).json()["month"]
        for title, amount, payer, split in (
            ("병원비", 32000, "지민", None),
            ("약국", 18500, "수진", None),
            ("가족 외식", 100000, "엄마", None),
            ("간식", 7001, "지민", ["지민", "수진"]),
        ):
            c.post(
                "/billing/expenses",
                json={
                    "title": title,
                    "amount": amount,
                    "date": f"{month}-01",
                    "split_among": [ids[n] for n in split] if split else None,
                },
                headers={"X-Gyeot-Token": by_name[payer]["token"]},  # 낸 사람은 요청한 사람
            )
        DEMO_USER_INFO.extend(tokens)


@app.get("/console", include_in_schema=False)
def console_page() -> FileResponse:
    return FileResponse(Path(__file__).with_name("dev_console.html"))


@app.get("/console/mascot.png", include_in_schema=False)
def console_mascot() -> FileResponse:
    return FileResponse(API_DIR.parent / "mobile" / "assets" / "images" / "gabee-mascot.png")


@app.get("/console/session", include_in_schema=False)
def console_session() -> dict:
    return {"users": DEMO_USER_INFO}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    engine.dispose()
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    DB_FILE.unlink(missing_ok=True)
    _seed()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
