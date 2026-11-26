"""관리자 챗봇 운영 담당이 쓰는 Cloud Run 상태 조회(읽기 전용). `gcloud run services describe`·`revisions list`·
`logging read` 로 보던 것을 챗봇이 말로 답할 수 있게 같은 정보를 REST 로 읽는다.

- 미리 정한 조회 3개만 한다(트래픽, 최근 버전, 오류 로그 건수). 바꾸기·배포·삭제는 하지 않고, 셸 명령도 실행하지 않는다.
- 토큰은 infra_service 처럼 Cloud Run 메타데이터 서버에서 받는다. Cloud Run 이 아니거나 `OPS_INFRA_ENABLED` 가 꺼져 있으면 부르지 않는다.
- 결과 글은 Claude 로 나간다. 버전 이름·비율·시각·건수·응답 코드만 담고, 로그 본문(message·사용자 정보·trace)은 넣지 않는다.
- 필요한 역할: roles/run.viewer(트래픽·버전), roles/logging.viewer(오류 로그 건수).
"""

import os
from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.shared.config import settings

from .infra_service import RUN_API, TIMEOUT, _http_reason, _meta

LOGGING_API = "https://logging.googleapis.com/v2/entries:list"
KST = ZoneInfo("Asia/Seoul")
RECENT_REVISIONS = 5
MAX_LOG_ENTRIES = 1000  # 한 번에 세는 최대 오류 로그 수(넘으면 "이상"으로 적는다)
MAX_HOURS = 72


class _Skip(Exception):
    """조회하지 않은 이유(챗봇에게 그대로 돌려줄 짧은 문장)."""


def _short(name: str | None) -> str:
    """`projects/.../revisions/gabee-00024-abc` → `gabee-00024-abc`."""
    return (name or "").rsplit("/", 1)[-1] or "알 수 없음"


def _kst(ts: str | None) -> str:
    if not ts:
        return "알 수 없음"
    try:
        return (
            datetime.fromisoformat(ts.replace("Z", "+00:00"))
            .astimezone(KST)
            .strftime("%m-%d %H:%M")
        )
    except ValueError:
        return "알 수 없음"


def _ready(conditions: list[dict] | None, terminal: dict | None = None) -> str:
    cond = terminal or next((c for c in conditions or [] if c.get("type") == "Ready"), None)
    if not cond:
        return "상태 알 수 없음"
    return "정상" if cond.get("state") == "CONDITION_SUCCEEDED" else "정상 아님"


def _run(read) -> list[str]:
    """Cloud Run 정보를 모은 뒤 read(client, headers, project, region, service) 를 부른다. 실패는 글로 돌려준다."""
    if not settings.ops_infra_enabled:
        return ["Cloud Run 상태: 수집이 꺼져 있어 알 수 없음(OPS_INFRA_ENABLED)"]
    service = os.environ.get("K_SERVICE")
    if not service:
        return ["Cloud Run 상태: Cloud Run 에서 실행 중이 아니라 알 수 없음"]
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            try:
                token = _meta(client, "instance/service-accounts/default/token")["access_token"]
                project = str(_meta(client, "project/project-id"))
                region = str(_meta(client, "instance/region")).rsplit("/", 1)[-1]
            except (httpx.HTTPError, KeyError, ValueError, TypeError):
                raise _Skip("Cloud Run 상태: 실행 환경 정보를 가져오지 못해 알 수 없음") from None
            headers = {"Authorization": f"Bearer {token}"}
            return read(client, headers, project, region, service)
    except _Skip as e:
        return [str(e)]
    except Exception:  # 조회 실패가 챗봇 답 전체를 막으면 안 된다
        return ["Cloud Run 상태: 가져오지 못해 알 수 없음"]


def _get(client: httpx.Client, url: str, headers: dict, what: str, **params) -> dict:
    try:
        r = client.get(url, headers=headers, params=params or None)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        raise _Skip(f"{_http_reason(what, e)}. 알 수 없음") from None


def traffic() -> list[str]:
    """지금 트래픽이 어느 버전으로 몇 % 가는지, 최신 버전과 서비스 상태."""

    def read(client, headers, project, region, service) -> list[str]:
        body = _get(
            client,
            f"{RUN_API}/projects/{project}/locations/{region}/services/{service}",
            headers,
            "Cloud Run 서비스",
        )
        latest = _short(body.get("latestReadyRevision"))
        lines = [
            f"서비스 {service}({region}) 상태: {_ready(None, body.get('terminalCondition'))}",
            f"최신 정상 버전: {latest}, 가장 최근 만든 버전: {_short(body.get('latestCreatedRevision'))}",
        ]
        statuses = body.get("trafficStatuses") or body.get("traffic") or []
        for t in statuses:
            rev = latest if "LATEST" in str(t.get("type", "")) else _short(t.get("revision"))
            pinned = "" if "LATEST" in str(t.get("type", "")) else " (고정)"
            tag = f", 태그 {t['tag']}" if t.get("tag") else ""
            lines.append(f"트래픽: {rev}{pinned} {t.get('percent', 0)}%{tag}")
        if not statuses:
            lines.append("트래픽: 정보 없음")
        return lines

    return _run(read)


def revisions() -> list[str]:
    """최근 만든 버전 최대 5개(이름, 만든 시각, 정상 여부)."""

    def read(client, headers, project, region, service) -> list[str]:
        body = _get(
            client,
            f"{RUN_API}/projects/{project}/locations/{region}/services/{service}/revisions",
            headers,
            "Cloud Run 버전 목록",
            pageSize=100,
        )
        items = sorted(
            body.get("revisions") or [], key=lambda r: r.get("createTime") or "", reverse=True
        )
        if not items:
            return ["최근 버전: 없음"]
        return [
            f"버전 {_short(r.get('name'))}: 만든 시각 {_kst(r.get('createTime'))}(한국 시간), {_ready(r.get('conditions'))}"
            for r in items[:RECENT_REVISIONS]
        ]

    return _run(read)


def error_logs(hours: int = 24) -> list[str]:
    """최근 hours 시간 Cloud Run 오류(ERROR 이상) 로그 건수. 버전별·응답 코드별, 그리고 둘을 묶어서만 센다(로그 본문은 읽어 넘기지 않는다)."""
    hours = max(1, min(int(hours), MAX_HOURS))

    def read(client, headers, project, region, service) -> list[str]:
        since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
        body = {
            "resourceNames": [f"projects/{project}"],
            "filter": (
                f'resource.type="cloud_run_revision" AND resource.labels.service_name="{service}" '
                f'AND severity>=ERROR AND timestamp>="{since}"'
            ),
            "orderBy": "timestamp desc",
            "pageSize": MAX_LOG_ENTRIES,
        }
        try:
            r = client.post(LOGGING_API, headers=headers, json=body)
            r.raise_for_status()
            entries = r.json().get("entries") or []
        except httpx.HTTPError as e:
            raise _Skip(f"{_http_reason('Cloud Logging 오류 로그', e)}. 알 수 없음") from None
        more = "이상" if len(entries) >= MAX_LOG_ENTRIES else ""
        if not entries:
            return [f"최근 {hours}시간 Cloud Run 오류 로그: 0건"]
        by_rev = Counter(
            _short((e.get("resource") or {}).get("labels", {}).get("revision_name"))
            for e in entries
        )
        by_status = Counter(
            str((e.get("httpRequest") or {}).get("status") or "응답 코드 없음") for e in entries
        )
        by_both = Counter(
            (
                _short((e.get("resource") or {}).get("labels", {}).get("revision_name")),
                str((e.get("httpRequest") or {}).get("status") or "응답 코드 없음"),
            )
            for e in entries
        )
        return [
            f"최근 {hours}시간 Cloud Run 오류 로그: {len(entries)}건{more}",
            "버전별: " + ", ".join(f"{k} {v}건" for k, v in by_rev.most_common(5)),
            "응답 코드별: " + ", ".join(f"{k} {v}건" for k, v in by_status.most_common(5)),
            "버전과 응답 코드별: "
            + ", ".join(f"{rev} {code} {v}건" for (rev, code), v in by_both.most_common(8)),
        ]

    return _run(read)
