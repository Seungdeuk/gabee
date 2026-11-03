"""구독·통신비 서버 API 스위치(SUBSCRIPTION_API_ENABLED): 꺼져 있으면 /billing/subscriptions* 를 403 subscription_disabled 로 막고, 일정 추천도 결제일을 읽지 않는다.

구독 코드 시험은 conftest 가 켠 상태(SUBSCRIPTION_API_ENABLED=true)에서 본다. 이 파일은 닫힌 상태를 본다.
"""

from datetime import date

import pytest

from app.features.schedule.agent import suggest_sources
from app.shared.config import settings
from app.shared.db import SessionLocal


def test_default_is_closed_in_settings():
    # conftest 가 시험용으로 환경 변수를 켜 두므로, 서비스 기본값은 설정 클래스의 필드 기본값으로 확인한다.
    assert type(settings).model_fields["subscription_api_enabled"].default is False


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/billing/subscriptions", None),
        ("get", "/billing/subscriptions/catalog", None),
        ("post", "/billing/subscriptions", {"kind": "ott", "name": "넷플릭스"}),
        ("get", "/billing/subscriptions/upcoming", None),
        ("get", "/billing/subscriptions/monthly", None),
        ("post", "/billing/subscriptions/monthly", {"month": "2026-10"}),
        ("patch", "/billing/subscriptions/x", {"name": "다른 이름"}),
        ("delete", "/billing/subscriptions/x", None),
    ],
)
def test_closed_blocks_every_subscription_endpoint(client, family, monkeypatch, method, path, body):
    a, _, _ = family
    monkeypatch.setattr(settings, "subscription_api_enabled", False)
    r = getattr(client, method)(path, headers=a, **({"json": body} if body is not None else {}))
    assert r.status_code == 403 and r.json()["code"] == "subscription_disabled", r.text


def test_closed_keeps_the_other_billing_endpoints_open(client, family, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(settings, "subscription_api_enabled", False)
    r = client.get("/billing/expenses", params={"month": "2026-10"}, headers=a)
    assert r.status_code == 200, r.text


def test_open_reaches_the_service(client, family, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(settings, "subscription_api_enabled", True)
    assert client.get("/billing/subscriptions", headers=a).status_code == 200


def test_closed_schedule_suggestions_skip_payment_days(monkeypatch):
    monkeypatch.setattr(settings, "subscription_api_enabled", False)
    with SessionLocal() as db:
        assert (
            suggest_sources.billing_lines(db, "no-such-group", "no-such-user", date(2026, 10, 1))
            == []
        )
