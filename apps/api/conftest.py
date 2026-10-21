import os
import tempfile

# 앱을 불러오기 전에 설정해야 한다: 테스트는 임시 SQLite 파일만 쓰고 실제 AI 를 부르지 않는다.
_tmp = tempfile.mkdtemp(prefix="gabee-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["DATA_DIR"] = _tmp
os.environ["ANTHROPIC_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.shared.db import Base, engine  # noqa: E402
from tests.helpers import signup  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:  # lifespan 이 테이블을 만든다
        yield c
    Base.metadata.drop_all(engine)


@pytest.fixture
def family(client):
    """가족 그룹 하나와 구성원 두 명(지민, 수진). (지민 헤더, 수진 헤더, 그룹) 을 돌려준다."""
    a = signup(client, "지민")
    group = client.post("/family-group/groups", json={"name": "우리 가족"}, headers=a).json()
    b = signup(client, "수진")
    assert (
        client.post(
            "/family-group/groups/join", json={"code": group["invite_code"]}, headers=b
        ).status_code
        == 200
    )
    return a, b, group
