"""메타 광고 성과(/admin/service/meta-ads): 설정 없음·메타 오류는 200 + 이유, 성공은 가짜 메타 응답으로 숫자 확인, 관리자만 접근.

메타에는 실제로 연결하지 않는다(httpx.MockTransport). 토큰·광고 계정 번호는 시험용 가짜 값이다."""

import httpx
import pytest

from app.features.service_admin import meta_ads
from app.shared.config import settings

URL = "/admin/service/meta-ads"
PASSWORD = "Sunny-day-2026"
FAKE_TOKEN = "test-token-not-real"


def _login(client, login_id="jimin_kim") -> tuple[dict, str]:
    body = {
        "login_id": login_id,
        "password": PASSWORD,
        "email": f"{login_id}@example.com",
        "name": "김지민",
    }
    assert client.post("/family-group/auth/signup", json=body).status_code == 201
    r = client.post("/family-group/auth/login", json={"login_id": login_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]["id"]


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    meta_ads._cache.clear()
    monkeypatch.setattr(settings, "meta_ads_access_token", FAKE_TOKEN)
    monkeypatch.setattr(settings, "meta_ads_account_id", "1234567890")
    yield
    meta_ads._cache.clear()


@pytest.fixture
def admin(client, monkeypatch) -> dict:
    headers, user_id = _login(client)
    monkeypatch.setattr(settings, "admin_user_ids", user_id)
    return headers


def _fake_meta(monkeypatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    real = httpx.Client

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def make(*_a, **kw):
        return real(
            transport=httpx.MockTransport(record),
            **{k: v for k, v in kw.items() if k != "transport"},
        )

    monkeypatch.setattr(meta_ads.httpx, "Client", make)
    return seen


def _row(
    cid: str, name: str, spend: str, installs: str | None = None, signups: str | None = None
) -> dict:
    actions = [{"action_type": "link_click", "value": "99"}]
    if installs is not None:
        actions.append({"action_type": "mobile_app_install", "value": installs})
    if signups is not None:
        actions.append(
            {"action_type": "app_custom_event.fb_mobile_complete_registration", "value": signups}
        )
    return {
        "campaign_id": cid,
        "campaign_name": name,
        "spend": spend,
        "impressions": "1000",
        "clicks": "40",
        "actions": actions,
        "account_currency": "KRW",
    }


def test_requires_login(client):
    assert client.get(URL).status_code == 401


def test_non_admin_is_denied(client, monkeypatch):
    headers, _ = _login(client)
    monkeypatch.setattr(settings, "admin_user_ids", "")
    r = client.get(URL, headers=headers)
    assert r.status_code == 403 and r.json()["code"] == "operator_required"


def test_not_configured_returns_reason_without_calling_meta(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "meta_ads_access_token", "")
    seen = _fake_meta(monkeypatch, lambda _r: httpx.Response(500))
    r = client.get(URL, headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False and body["ok"] is False and body["reason"]
    assert body["campaigns"] == [] and seen == []


def test_bad_account_id_is_not_sent(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "meta_ads_account_id", "123/../me")
    seen = _fake_meta(monkeypatch, lambda _r: httpx.Response(200, json={"data": []}))
    body = client.get(URL, headers=admin).json()
    assert body["configured"] is False and seen == []


def test_campaigns_are_summed_and_sorted_by_spend(client, admin, monkeypatch):
    def ok(_request: httpx.Request) -> httpx.Response:
        rows = [
            _row("1", "가을 설치 광고", "12000.5", installs="30", signups="12"),
            _row("2", "인스타 릴스", "50000", installs="80"),
        ]
        return httpx.Response(
            200, json={"data": rows, "paging": {"cursors": {"before": "a", "after": "b"}}}
        )

    seen = _fake_meta(monkeypatch, ok)
    r = client.get(URL, headers=admin, params={"days": 30})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] and body["ok"] and body["days"] == 30 and body["currency"] == "KRW"
    assert [c["name"] for c in body["campaigns"]] == ["인스타 릴스", "가을 설치 광고"]
    first = body["campaigns"][1]
    assert first == {
        "campaign_id": "1",
        "name": "가을 설치 광고",
        "spend": 12000.5,
        "impressions": 1000,
        "clicks": 40,
        "installs": 30,
        "signups": 12,
    }
    assert body["total"] == {
        "spend": 62000.5,
        "impressions": 2000,
        "clicks": 80,
        "installs": 110,
        "signups": 12,
    }

    # 요청: act_ 를 붙인 광고 계정, 캠페인 단위, 30일, 토큰은 주소가 아니라 머리줄로만
    (req,) = seen
    assert req.url.path.endswith("/act_1234567890/insights")
    assert req.url.params["level"] == "campaign" and req.url.params["date_preset"] == "last_30d"
    assert FAKE_TOKEN not in str(req.url)
    assert req.headers["Authorization"] == f"Bearer {FAKE_TOKEN}"


def test_follows_next_page(client, admin, monkeypatch):
    def pages(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("after") == "p2":
            return httpx.Response(
                200,
                json={"data": [_row("2", "둘째", "10")], "paging": {"cursors": {"after": "p3"}}},
            )
        return httpx.Response(
            200,
            json={
                "data": [_row("1", "첫째", "20")],
                "paging": {"cursors": {"after": "p2"}, "next": "https://graph.facebook.com/next"},
            },
        )

    seen = _fake_meta(monkeypatch, pages)
    body = client.get(URL, headers=admin).json()
    assert [c["name"] for c in body["campaigns"]] == ["첫째", "둘째"] and len(seen) == 2
    assert all(FAKE_TOKEN not in str(r.url) for r in seen)


@pytest.mark.parametrize(
    ("status", "code", "words"),
    [
        (400, 190, "토큰"),
        (403, 10, "ads_read"),
        (400, 17, "한도"),
        (400, 80000, "한도"),
        (500, 1, "HTTP 500"),
    ],
)
def test_meta_error_is_200_with_reason_and_no_token(
    client, admin, monkeypatch, status, code, words
):
    def fail(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={
                "error": {"message": f"bad {FAKE_TOKEN}", "type": "OAuthException", "code": code}
            },
        )

    _fake_meta(monkeypatch, fail)
    r = client.get(URL, headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True and body["ok"] is False and words in body["reason"]
    assert FAKE_TOKEN not in r.text and body["campaigns"] == []


def test_network_error_is_200_with_reason(client, admin, monkeypatch):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    _fake_meta(monkeypatch, down)
    body = client.get(URL, headers=admin).json()
    assert body["ok"] is False and "연결" in body["reason"]


def test_result_is_cached(client, admin, monkeypatch):
    seen = _fake_meta(
        monkeypatch, lambda _r: httpx.Response(200, json={"data": [_row("1", "a", "1")]})
    )
    client.get(URL, headers=admin)
    client.get(URL, headers=admin)
    assert len(seen) == 1


def test_only_7_or_30_days(client, admin):
    assert client.get(URL, headers=admin, params={"days": 14}).status_code == 422
