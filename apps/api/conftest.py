import os
import shutil
import tempfile

# 앱을 불러오기 전에 설정해야 한다: 테스트는 임시 SQLite 파일만 쓰고 실제 AI 를 부르지 않는다.
_tmp = tempfile.mkdtemp(prefix="gabee-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["DATA_DIR"] = _tmp
os.environ["ANTHROPIC_API_KEY"] = ""
# 구독·통신비 서버 API 도 서비스에서 닫혀 있지만(SUBSCRIPTION_API_ENABLED), 구독 코드 시험은 켠 상태에서 본다. 닫힌 상태는 test_subscription_api_closed.py 가 본다.
os.environ["SUBSCRIPTION_API_ENABLED"] = "true"
os.environ["JWT_SECRET"] = "test-only-jwt-secret-not-for-production-0123456789"  # 테스트 전용 값
# 개발자 PC 에 NER 모델이 있어도 시험은 규칙 탐지만 쓴다(NER 시험은 각자 모드를 명시한다). 모델이 있는 PC 와 없는 CI 의 결과를 같게 한다.
os.environ["PRIVACY_NER_MODE"] = "off"
os.environ["PRIVACY_NER_MODEL_DIR"] = ""
# 개발자의 apps/api/.env 에 실제 SMTP 설정이 있어도 테스트가 진짜 메일을 보내지 않게 비운다(발송은 set_mailer 가짜로만).
for _name in ("MAIL_BACKEND", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
    os.environ[_name] = ""
# 개발자의 .env 에 업로드 Claude 읽기·가리기를 켜 두어도 시험은 가짜 OCR·규칙 가리기만 쓴다(켠 경로의 시험은 각자 settings 를 바꾼다).
os.environ["INGEST_LLM_OCR"] = "false"
os.environ["INGEST_LLM_MASK"] = "false"
os.environ["PHOTO_JUDGE_LLM"] = (
    "false"  # 가족방 사진 판별도 시험에서는 외부 AI 를 쓰지 않는다(켠 경로의 시험은 각자 settings 를 바꾼다)
)
# 개발자의 .env 에 분류 보조(Jev) 키가 있어도 시험 문서가 외부로 나가지 않게 비운다.
os.environ["TYPESAFE_API_KEY"] = ""
os.environ["INGEST_REMINDERS"] = (
    "false"  # 챙길 일 뽑기도 기본은 끈다(켠 경로의 시험은 각자 settings 를 바꾼다)
)
os.environ["INGEST_RETRY_WAIT_SECONDS"] = (
    "0"  # 자동 재시도(실패 파일)가 시험을 기다리게 하지 않는다
)

from contextlib import contextmanager  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event  # noqa: E402

from app.features.family_group.models import Group  # noqa: E402
from app.main import app  # noqa: E402
from app.shared.db import Base, engine  # noqa: E402
from tests import sqlite_pragmas  # noqa: E402
from tests.helpers import join_family, signup  # noqa: E402

# 임시 SQLite 파일에만 속도 설정(PRAGMA)을 적용한다. 조건과 근거는 tests/sqlite_pragmas.py, 시험은 tests/test_sqlite_test_pragmas.py.
sqlite_pragmas.apply(engine, _tmp)


def pytest_sessionfinish(session, exitstatus):
    """시험이 끝나면 임시 DB·데이터 폴더를 지운다(Temp 에 gabee-test-* 가 실행마다 쌓이지 않게)."""
    engine.dispose()  # Windows 는 열려 있는 SQLite 파일을 지울 수 없다
    shutil.rmtree(_tmp, ignore_errors=True)


@contextmanager
def _approval_required_scope():
    """이 범위에서 만든 가족은 초대 코드로 들어와도 관리자 승인을 기다린다.

    서버 기본값은 자동 승인(`groups.auto_approve_invites=True`)이라, '승인 대기 → 관리자 승인' 흐름을 보는 시험은
    가족을 만들 때 자동 승인을 끈 상태로 시작해야 한다. 기본값에 기대지 않게 가족을 저장하기 직전에 값을 고정한다."""

    def _off(mapper, connection, group):
        group.auto_approve_invites = False

    event.listen(Group, "before_insert", _off)
    try:
        yield
    finally:
        event.remove(Group, "before_insert", _off)


@pytest.fixture
def approval_required():
    with _approval_required_scope():
        yield


@pytest.fixture(scope="module")
def approval_required_module():
    """module 범위 픽스처(`world` 같은 것)가 만드는 가족에도 적용할 때 쓴다."""
    with _approval_required_scope():
        yield


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


@pytest.fixture(autouse=True)
def _no_background_library_registration(monkeypatch):
    """가족방 문서의 문서함 자동 등록은 실제 스레드에서 돌지 않게 한다(다른 시험의 DB·행 수에 끼어들지 않게). 그 동작을 보는 시험은 각자 `library._submit` 을 바꾼다."""
    from app.features.ai_assistant import library

    monkeypatch.setattr(library, "_submit", lambda fn, *args: None)
