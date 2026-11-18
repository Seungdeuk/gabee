# 관리자 알림

관리자 화면 "운영 업무 › 알림". 기준을 넘은 서버 신호를 목록으로 보여 주고, 관리자가 확인하면 목록과 배지에서 빠진다. 요구사항은 `docs/requirements/admin-alerts.md`.

## 구현 현황 (알림 틀 + 서버 오류율)

- 폴더: `app/features/admin_alerts/` (`models.py`, `repository.py`, `service.py`, `router.py`, `schemas.py`, `tests/`).
- 규칙 명단: `app/shared/alert_rules.py` 의 `register(name, check)`. 각 기능이 자기 `alert_rules.py` 에서 올리고, 그 기능의 `router.py` 가 불러온다(관리자 챗봇의 `admin_facts` 와 같은 방식, 기능 간 내부 import 없음).
- 규칙 1개(`ops_admin/alert_rules.py`): 서버 오류율.
  - 서버 오류율: `ops_request_metrics` 의 최근 60분 합계를 읽어 요청 20건 이상이고 5xx 5% 이상이면 긴급, 1% 이상이면 주의. 지문은 `server_error_rate:<UTC 시>` 라 같은 시간대에는 한 번만 생긴다.
- 표: `admin_alert_log` (리비전 `9c4e7a2b1d63`, 표·인덱스 추가만). `key` 기본키로 중복을 막는다. 점검이 동시에 두 번 돌아도 savepoint + 고유 키로 한쪽만 들어간다.
- 주소:
  - `POST /internal/alerts/run`: 점검. `X-Alert-Token` 이 `ADMIN_ALERTS_TOKEN` 과 같아야 하고(비교는 `hmac.compare_digest`), 설정이 비어 있으면 아무도 통과하지 못한다(403). `ADMIN_ALERTS_ENABLED=false`(기본)이면 아무 일도 하지 않는다. 규칙 하나가 실패해도 나머지는 돈다(로그에는 예외 종류만).
  - `GET /admin/alerts`: 목록(확인 안 된 것 먼저, 최근 것 먼저, 50개) + `unacked`.
  - `POST /admin/alerts/{key}/ack`: 확인. 이미 확인된 것은 바꾸지 않고, 없는 키는 404. 확인한 사람은 사용자 id 가 아니라 고정 표시 "운영자".
  - 세 주소 모두 `schema_ready("admin_alerts")` 를 거쳐, 표가 없는 DB 에서는 503 이고 다른 기능은 영향이 없다.
- 화면은 별도 PR 로 올렸다. 화면(`service_admin/static/app.js`): 메뉴 "알림"(종 아이콘)·확인 안 된 개수 배지·목록·"확인함" 버튼. 알림은 다른 화면 데이터와 따로 받아서, 알림 표가 없거나 실패해도 나머지 관리자 화면은 열린다.
- AI 는 쓰지 않는다. 감시는 숫자 비교뿐이다.
- 시험: `admin_alerts/tests/test_admin_alerts.py` 11개(토큰·꺼짐·기준선 20건/1%/5%·중복·규칙 실패·권한·멱등 확인·없는 키·개인 정보 없음). 보안 시험 표(`tests/test_security_matrix.py`)에 점검 주소는 "로그인 대신 토큰", 목록·확인 주소는 "가족 데이터 아님"으로 올렸다.

## 남은 것

- 자동 실행: GCP Cloud Scheduler 가 5분마다 점검 주소를 부르게 설정해야 한다(배포 설정이라 담당자 허락 필요). 그 전까지는 아무도 점검 주소를 부르지 않아 알림이 생기지 않는다. 서버(Cloud Run)는 CPU 를 요청 중에만 쓰므로 서버 안 스레드 방식은 쓰지 않는다.
- 실제 PostgreSQL 에서 마이그레이션 적용 확인(이 PC 는 Docker 가 꺼져 있어 오프라인 SQL 만 확인했다). PR 의 CI(`api-postgres`)가 다시 검증한다.
- 긴급 알림을 화면 밖으로 알리는 방법(메일·푸시)과 알림 목록 자동 새로고침은 아직 없다. 지금은 관리자가 "알림" 메뉴를 열어야 보인다.
- 규칙 추가: 처음 보는 서버 오류, 답 안 한 문의, AI 사용 급증, 승인 대기 참가 요청(기능별로 따로 올린다).
- 새 알림의 AI 요약(하루 상한 포함).
