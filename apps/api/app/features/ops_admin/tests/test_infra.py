"""인프라 상태: 꺼짐/Cloud Run 아님/권한 없음은 collected=false, 성공은 가짜 GCP 응답으로 값 확인, 운영자만 접근."""

import httpx
import pytest

from app.features.ops_admin import infra_service
from app.shared.config import settings

SIGNUP = "/family-group/auth/signup"
LOGIN = "/family-group/auth/login"
PASSWORD = "Sunny-day-2026"


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(infra_service, "_cache", None)
    monkeypatch.setattr(settings, "ops_infra_enabled", True)


def _fake_gcp(monkeypatch, handler):
    real = httpx.Client

    def make(*_a, **kw):
        return real(
            transport=httpx.MockTransport(handler),
            **{k: v for k, v in kw.items() if k != "transport"},
        )

    monkeypatch.setattr(infra_service.httpx, "Client", make)
    monkeypatch.setenv("K_SERVICE", "gabee")
    monkeypatch.setenv("K_REVISION", "gabee-00042")


def _ok(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith("service-accounts/default/token"):
        return httpx.Response(200, json={"access_token": "tok"})
    if url.endswith("project/project-id"):
        return httpx.Response(200, text="proj")
    if url.endswith("instance/region"):
        return httpx.Response(200, text="projects/1/regions/asia-northeast3")
    if "run.googleapis.com/v2" in url:
        return httpx.Response(
            200,
            json={
                "template": {
                    "scaling": {"minInstanceCount": 1, "maxInstanceCount": 3},
                    "containers": [{"resources": {"cpuIdle": True}}],
                }
            },
        )
    if "instance_count" in url:
        return httpx.Response(
            200,
            json={
                "timeSeries": [
                    {
                        "metric": {"labels": {"state": "active"}},
                        "points": [{"value": {"int64Value": "2"}}],
                    },
                    {
                        "metric": {"labels": {"state": "idle"}},
                        "points": [{"value": {"int64Value": "1"}}],
                    },
                ]
            },
        )
    value = 0.4 if "cpu" in url else 0.6
    return httpx.Response(
        200, json={"timeSeries": [{"points": [{"value": {"doubleValue": value}}]}]}
    )


def test_disabled_collects_nothing(monkeypatch):
    monkeypatch.setattr(settings, "ops_infra_enabled", False)
    r = infra_service.get_infra()
    assert r.collected is False and "OPS_INFRA_ENABLED" in r.reason


def test_not_on_cloud_run(monkeypatch):
    monkeypatch.delenv("K_SERVICE", raising=False)
    r = infra_service.get_infra()
    assert r.collected is False and r.service is None and r.metrics is None


def test_collects_service_and_metrics(monkeypatch):
    _fake_gcp(monkeypatch, _ok)
    r = infra_service.get_infra()
    assert r.collected is True and r.reason is None
    assert (r.service.name, r.service.region, r.service.revision) == (
        "gabee",
        "asia-northeast3",
        "gabee-00042",
    )
    assert r.service.project_id == "proj"
    assert (r.service.min_instances, r.service.max_instances, r.service.cpu_allocation) == (
        1,
        3,
        "request",
    )
    assert (r.metrics.instances_active, r.metrics.instances_idle) == (2, 1)
    assert (r.metrics.cpu_p99, r.metrics.memory_p99) == (0.4, 0.6)


def test_permission_denied_is_reported_without_raising(monkeypatch):
    def handler(request):
        if "googleapis.com" in str(request.url):
            return httpx.Response(403, json={})
        return _ok(request)

    _fake_gcp(monkeypatch, handler)
    r = infra_service.get_infra()
    assert r.collected is False and "권한" in r.reason


def test_partial_failure_keeps_what_worked(monkeypatch):
    def handler(request):
        if "monitoring.googleapis.com" in str(request.url):
            return httpx.Response(403, json={})
        return _ok(request)

    _fake_gcp(monkeypatch, handler)
    r = infra_service.get_infra()
    assert r.collected is True and r.service.max_instances == 3 and "Cloud Monitoring" in r.reason


def test_result_is_cached(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return _ok(request)

    _fake_gcp(monkeypatch, handler)
    infra_service.get_infra()
    n = len(calls)
    infra_service.get_infra()
    assert len(calls) == n


def test_endpoint_requires_operator(client, monkeypatch):
    assert client.get("/admin/ops/infra").status_code == 401
    body = {
        "login_id": "infra_tester",
        "password": PASSWORD,
        "email": "infra_tester@example.com",
        "name": "시험",
    }
    assert client.post(SIGNUP, json=body).status_code == 201
    login = client.post(LOGIN, json={"login_id": "infra_tester", "password": PASSWORD}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    monkeypatch.setattr(settings, "admin_user_ids", "")
    assert client.get("/admin/ops/infra", headers=headers).status_code == 403
    monkeypatch.setattr(settings, "admin_user_ids", login["user"]["id"])
    monkeypatch.delenv("K_SERVICE", raising=False)
    r = client.get("/admin/ops/infra", headers=headers)
    assert r.status_code == 200 and r.json()["collected"] is False
