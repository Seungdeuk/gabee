# 관리자 알림

관리자 화면 "운영 업무 › 알림". 기준을 넘은 서버 신호를 목록으로 보여 주고, 관리자가 확인하면 목록과 배지에서 빠진다. 요구사항은 `docs/requirements/admin-alerts.md`.

## 구현 현황 (알림 틀 + 규칙 5개)

- 폴더: `app/features/admin_alerts/` (`models.py`, `repository.py`, `service.py`, `router.py`, `schemas.py`, `tests/`).
- 규칙 명단: `app/shared/alert_rules.py` 의 `register(name, check)`. 각 기능이 자기 `alert_rules.py` 에서 올리고, 그 기능의 `router.py` 가 불러온다(관리자 챗봇의 `admin_facts` 와 같은 방식, 기능 간 내부 import 없음).
- 규칙 5개: 서버 오류율·처음 보는 서버 오류(`ops_admin/alert_rules.py`), 답 안 한 문의·AI 사용 급증·승인 대기 참가 요청(`service_admin/alert_rules.py`).
  - 답 안 한 문의: `support_tickets` 에서 `new`·`working` 상태로 등록한 지 6시간 넘은 줄이 있으면 주의. 문구는 개수와 가장 오래된 대기 시간뿐(제목·내용·작성자 없음). 하루 한 번(`stale_support:<한국 날짜>`).
  - AI 사용 급증: `ai_usage_logs`(`nested`·`rejected` 표식 줄 제외)에서 오늘(한국 시간 자정부터) 요청이 50건 이상이고 최근 7일 하루 평균의 3배 이상이면 주의. 평균이 0이어도 50건이면 울린다. 하루 한 번(`ai_usage_spike:<한국 날짜>`).
  - 승인 대기 참가 요청: `join_requests` 에서 `pending` 상태로 24시간 넘은 줄이 있으면 주의. 가족 이름·신청자는 쓰지 않는다. 하루 한 번(`stale_join:<한국 날짜>`).
  - 세 규칙이 읽는 표는 `service_admin/repository.py` 가 표 이름으로 읽는다(다른 기능의 파일을 가져오지 않는다). 날짜 경계는 `ai_day_utc_offset_hours`(기본 9, 한국 시간 자정).
  - 처음 보는 서버 오류: `ops_error_events` 에서 최근 24시간에 처음 나온 (오류 종류, 경로) 조합이 있으면 주의. 지문에 가린 메시지가 섞여 있어 줄이 아니라 조합으로 묶고, 그 전에 같은 조합이 있었으면 새것이 아니다(`repository.new_server_error_pairs`). 서버 오류만 보고 인증 실패는 무시한다. 한 조합은 한 번만(지문에 시간 없음), 한 번 점검에 최대 10개. 문구는 오류 종류·경로·횟수뿐이다.
  - 서버 오류율: `ops_request_metrics` 의 최근 60분 합계를 읽어 요청 20건 이상이고 5xx 5% 이상이면 긴급, 1% 이상이면 주의. 지문은 `server_error_rate:<UTC 시>` 라 같은 시간대에는 한 번만 생긴다.
- 표: `admin_alert_log` (리비전 `9c4e7a2b1d63`, 표·인덱스 추가만). `key` 기본키로 중복을 막는다. 점검이 동시에 두 번 돌아도 savepoint + 고유 키로 한쪽만 들어간다.
- 주소:
  - `POST /internal/alerts/run`: 점검. `X-Alert-Token` 이 `ADMIN_ALERTS_TOKEN` 과 같아야 하고(비교는 `hmac.compare_digest`), 설정이 비어 있으면 아무도 통과하지 못한다(403). `ADMIN_ALERTS_ENABLED=false`(기본)이면 아무 일도 하지 않는다. 규칙 하나가 실패해도 나머지는 돈다(로그에는 예외 종류만).
  - `GET /admin/alerts`: 목록(확인 안 된 것 먼저, 최근 것 먼저, 50개) + `unacked`.
  - `POST /admin/alerts/{key}/ack`: 확인. 이미 확인된 것은 바꾸지 않고, 없는 키는 404. 확인한 사람은 사용자 id 가 아니라 고정 표시 "운영자".
  - 세 주소 모두 `schema_ready("admin_alerts")` 를 거쳐, 표가 없는 DB 에서는 503 이고 다른 기능은 영향이 없다.
- 화면은 별도 PR 로 올렸다. 화면(`service_admin/static/app.js`): 메뉴 "알림"(종 아이콘)·확인 안 된 개수 배지·목록·"확인함" 버튼. 알림은 다른 화면 데이터와 따로 받아서, 알림 표가 없거나 실패해도 나머지 관리자 화면은 열린다.
- AI 는 쓰지 않는다. 감시는 숫자 비교뿐이다.
- 시험: `admin_alerts/tests/test_admin_alerts.py` 26개(토큰·꺼짐·기준선 20건/1%/5%·중복·규칙 실패·권한·멱등 확인·없는 키·개인 정보 없음, 처음 보는 서버 오류 6가지, 문의·AI 사용·참가 요청 규칙 9가지). 보안 시험 표(`tests/test_security_matrix.py`)에 점검 주소는 "로그인 대신 토큰", 목록·확인 주소는 "가족 데이터 아님"으로 올렸다.

## 남은 것

- 자동 실행: GCP Cloud Scheduler 가 5분마다 점검 주소를 부르게 설정해야 한다(배포 설정이라 담당자 허락 필요). 그 전까지는 아무도 점검 주소를 부르지 않아 알림이 생기지 않는다. 서버(Cloud Run)는 CPU 를 요청 중에만 쓰므로 서버 안 스레드 방식은 쓰지 않는다.
- 실제 PostgreSQL 에서 마이그레이션 적용 확인(이 PC 는 Docker 가 꺼져 있어 오프라인 SQL 만 확인했다). PR 의 CI(`api-postgres`)가 다시 검증한다.
- `ai_usage_logs` 에는 시간만으로 찾는 인덱스가 없다((가족, 시간)·(사용자, 시간)뿐). 기록이 많이 쌓이면 5분마다 도는 AI 사용 급증 조회가 느려질 수 있어 그때 인덱스 추가 마이그레이션을 따로 만든다.
- 규칙 3~5 의 기준 숫자(6시간, 3배·50건, 24시간)는 제안값이라 운영하며 조정한다.
- 긴급 알림을 화면 밖으로 알리는 방법(메일·푸시)과 알림 목록 자동 새로고침은 아직 없다. 지금은 관리자가 "알림" 메뉴를 열어야 보인다.
- 새 알림의 AI 요약(하루 상한 포함).
