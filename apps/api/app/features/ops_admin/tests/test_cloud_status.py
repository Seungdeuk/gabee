"""관리자 챗봇 운영 담당의 Cloud Run 조회: 꺼짐/Cloud Run 아님/권한 없음은 '알 수 없음' 글, 성공은 가짜 GCP 응답으로 값 확인.
로그 본문(message·사용자 정보)은 결과 글에 들어가지 않는다. 바꾸는 요청(POST 는 로그 조회만)을 보내지 않는다."""

import httpx
import pytest

from app.features.ops_admin import admin_facts, cloud_status
from app.shared.config import settings

SERVICE = {
    "terminalCondition": {"type": "Ready", "state": "CONDITION_SUCCEEDED"},
    "latestReadyRevision": "projects/p/locations/asia-northeast3/services/gabee/revisions/gabee-00025-new",
    "latestCreatedRevision": "projects/p/locations/asia-northeast3/services/gabee/revisions/gabee-00025-new",
    "trafficStatuses": [
        {
            "type": "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION",
            "revision": "gabee-00024-old",
            "percent": 90,
        },
        {"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", "percent": 10, "tag": "canary"},
    ],
}
REVISIONS = {
    "revisions": [
        {
            "name": "projects/p/locations/r/services/gabee/revisions/gabee-00024-old",
            "createTime": "2026-11-24T03:07:00Z",
            "conditions": [{"type": "Ready", "state": "CONDITION_SUCCEEDED"}],
        },
        {
            "name": "projects/p/locations/r/services/gabee/revisions/gabee-00025-new",
            "createTime": "2026-11-25T00:30:00Z",
            "conditions": [{"type": "Ready", "state": "CONDITION_FAILED"}],
        },
    ]
}
SECRET_TEXT = "김가비 kim@example.com 비밀 메시지"
LOGS = {
    "entries": [
        {
            "resource": {"labels": {"revision_name": "gabee-00025-new"}},
            "httpRequest": {"status": 500},
            "textPayload": SECRET_TEXT,
        },
        {
            "resource": {"labels": {"revision_name": "gabee-00025-new"}},
            "httpRequest": {"status": 500},
            "jsonPayload": {"message": SECRET_TEXT},
        },
        {"resource": {"labels": {"revision_name": "gabee-00024-old"}}, "textPayload": SECRET_TEXT},
    ]
}


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(settings, "ops_infra_enabled", True)


def _fake_gcp(monkeypatch, handler, seen=None):
    real = httpx.Client

    def wrapped(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return handler(request)

    def make(*_a, **kw):
        return real(
            transport=httpx.MockTransport(wrapped),
            **{k: v for k, v in kw.items() if k != "transport"},
        )

    monkeypatch.setattr(cloud_status.httpx, "Client", make)
    monkeypatch.setenv("K_SERVICE", "gabee")


def _ok(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith("service-accounts/default/token"):
        return httpx.Response(200, json={"access_token": "tok"})
    if url.endswith("project/project-id"):
        return httpx.Response(200, text="proj")
    if url.endswith("instance/region"):
        return httpx.Response(200, text="projects/1/regions/asia-northeast3")
    if "logging.googleapis.com" in url:
        return httpx.Response(200, json=LOGS)
    if url.split("?")[0].endswith("/revisions"):
        return httpx.Response(200, json=REVISIONS)
    if "run.googleapis.com/v2" in url:
        return httpx.Response(200, json=SERVICE)
    return httpx.Response(404)


def test_off_or_not_cloud_run_says_unknown(monkeypatch):
    monkeypatch.setattr(settings, "ops_infra_enabled", False)
    assert "수집이 꺼져 있어 알 수 없음" in cloud_status.traffic()[0]
    monkeypatch.setattr(settings, "ops_infra_enabled", True)
    monkeypatch.delenv("K_SERVICE", raising=False)
    assert "Cloud Run 에서 실행 중이 아니라" in cloud_status.revisions()[0]


def test_traffic_shows_split_and_latest(monkeypatch):
    _fake_gcp(monkeypatch, _ok)
    text = "\n".join(cloud_status.traffic())
    assert "서비스 gabee(asia-northeast3) 상태: 정상" in text
    assert "최신 정상 버전: gabee-00025-new" in text
    assert "트래픽: gabee-00024-old (고정) 90%" in text
    assert "트래픽: gabee-00025-new 10%, 태그 canary" in text


def test_revisions_newest_first_in_kst(monkeypatch):
    _fake_gcp(monkeypatch, _ok)
    lines = cloud_status.revisions()
    assert lines[0] == "버전 gabee-00025-new: 만든 시각 11-25 09:30(한국 시간), 정상 아님"
    assert lines[1].startswith("버전 gabee-00024-old: 만든 시각 11-24 12:07")


def test_error_logs_counts_only_and_no_log_text(monkeypatch):
    seen: list[httpx.Request] = []
    _fake_gcp(monkeypatch, _ok, seen)
    lines = cloud_status.error_logs(6)
    text = "\n".join(lines)
    assert lines[0] == "최근 6시간 Cloud Run 오류 로그: 3건"
    assert "gabee-00025-new 2건" in text and "gabee-00024-old 1건" in text
    assert "500 2건" in text and "응답 코드 없음 1건" in text
    assert (
        "gabee-00025-new 500 2건" in lines[3]
    )  # 어느 버전에서 어떤 응답 코드가 났는지 묶어서도 센다
    assert "김가비" not in text and "example.com" not in text and "비밀" not in text
    body = next(r for r in seen if "logging" in str(r.url)).content.decode()
    assert "severity>=ERROR" in body and 'service_name=\\"gabee\\"' in body
    # 로그 조회 말고는 읽기(GET)만 한다
    assert all(r.method == "GET" for r in seen if "logging" not in str(r.url))


def test_error_logs_hours_are_clamped(monkeypatch):
    _fake_gcp(monkeypatch, _ok)
    assert cloud_status.error_logs(1000)[0].startswith("최근 72시간")
    assert cloud_status.error_logs(0)[0].startswith("최근 1시간")


def test_permission_denied_is_reported(monkeypatch):
    def denied(request: httpx.Request) -> httpx.Response:
        if "googleapis.com" in str(request.url):
            return httpx.Response(403)
        return _ok(request)

    _fake_gcp(monkeypatch, denied)
    assert "조회 권한이 없어요" in cloud_status.traffic()[0]
    assert "Cloud Logging 오류 로그 조회 권한이 없어요" in cloud_status.error_logs()[0]


def test_metadata_failure_is_unknown(monkeypatch):
    _fake_gcp(monkeypatch, lambda r: httpx.Response(500))
    assert cloud_status.revisions() == ["Cloud Run 상태: 실행 환경 정보를 가져오지 못해 알 수 없음"]


def test_chatbot_hours_input_is_checked():
    assert admin_facts.Hours().hours == 24
    with pytest.raises(ValueError):
        admin_facts.Hours(hours=73)
