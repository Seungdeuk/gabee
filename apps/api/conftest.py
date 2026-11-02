import os
import tempfile

# 앱을 불러오기 전에 설정해야 한다: 테스트는 임시 SQLite 파일만 쓰고 실제 AI 를 부르지 않는다.
_tmp = tempfile.mkdtemp(prefix="gabee-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["DATA_DIR"] = _tmp
os.environ["ANTHROPIC_API_KEY"] = ""
# 돌봄 서버 API 는 서비스에서 닫혀 있지만(CARE_API_ENABLED), 돌봄 코드 시험은 켠 상태에서 본다. 닫힌 상태는 test_care_api_closed.py 가 본다.
os.environ["CARE_API_ENABLED"] = "true"
os.environ["JWT_SECRET"] = "test-only-jwt-secret-not-for-production-0123456789"  # 테스트 전용 값
# 개발자 PC 에 NER 모델이 있어도 시험은 규칙 탐지만 쓴다(NER 시험은 각자 모드를 명시한다). 모델이 있는 PC 와 없는 CI 의 결과를 같게 한다.
os.environ["PRIVACY_NER_MODE"] = "off"
os.environ["PRIVACY_NER_MODEL_DIR"] = ""
# 개발자의 apps/api/.env 에 실제 SMTP 설정이 있어도 테스트가 진짜 메일을 보내지 않게 비운다(발송은 set_mailer 가짜로만).
for _name in ("MAIL_BACKEND", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
    os.environ[_name] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.shared.db import Base, engine  # noqa: E402
from tests.helpers import join_family, signup  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_login_limiter():
    from app.features.family_group.service import login_limiter, mail_limiter
    from app.shared import mailer

    login_limiter.reset()
    mail_limiter.reset()
    yield
    login_limiter.reset()
    mail_limiter.reset()
    mailer.set_mailer(None)


@pytest.fixture
def full_care_samples(monkeypatch):
    """돌봄 추천 규칙(물·산책·컨디션)과 수치·컨디션 기록 방식을 시험할 때 쓴다: 예전 기본 항목 7개를 처음 열 때 만든다.
    서비스의 기본값은 식사 3개 + 영양제라서(`care/config.py` 의 SAMPLE_ITEMS), 그 항목이 필요한 시험이 이 세트를 명시한다."""
    from app.features.care import config as care_config

    monkeypatch.setattr(care_config, "SAMPLE_ITEMS", care_config.FULL_SAMPLE_ITEMS)


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
    join_family(client, a, group["invite_code"], b)  # 익명 계정도 가입 요청 → 소유자 승인
    return a, b, group


@pytest.fixture
def other_family(client):
    """family 와 전혀 무관한 다른 가족(구성원 한 명: 남). 교차-그룹 격리 테스트용."""
    outsider = signup(client, "남")
    client.post("/family-group/groups", json={"name": "다른 가족"}, headers=outsider)
    return outsider
