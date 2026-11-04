# 운영 관리자 페이지 (ops-admin) 구현 현황

운영(유님) 쪽 문서다. 서비스 관리자 페이지(주님)는 `docs/features/admin.md`에 따로 있고 이 문서는 그 내용을 다루지 않는다.
요구사항은 `docs/requirements/ops-admin.md`.

## 구현된 것

### 요청 계측 (PR 3, `OPS_METRICS_ENABLED=true` 일 때만 동작, 기본 꺼짐)
- `app/features/ops_admin/middleware.py` (`RequestMetricsMiddleware`, 가장 바깥 미들웨어)
  - 요청마다 새 trace id 를 만들어 응답 헤더 `X-Trace-Id` 로 내려준다(꺼져 있으면 헤더도 없다).
  - 메서드, **경로 패턴**(`/family-group/groups/{group_id}`), 상태코드 구분(2xx~5xx), 걸린 시간만 집계한다. URL 원문·쿼리·헤더·본문·사용자·가족 id 는 받지 않는다. 라우트와 맞지 않는 요청(404 등)은 `unmatched` 한 이름으로 묶고, `/health*` 는 제외한다.
  - 처리되지 않은 예외는 5xx 로 센다. 계측 중 어떤 오류가 나도 요청에는 영향이 없다.
- `app/features/ops_admin/service.py`: 메모리에서 구간(기본 300초)별로 합치고, **새 구간의 첫 요청이 지난 구간을 저장**한다(백그라운드 타이머 없음 — Cloud Run CPU 제한 때문, 미확인). 서버 종료 때 남은 집계를 저장한다. 저장에 실패하면 그 묶음을 버리고 로그에 예외 클래스 이름만 남긴다. 보관 일수(기본 90)를 넘은 구간은 저장할 때 시간당 한 번 정리한다.
- `app/features/ops_admin/repository.py`: 같은 키는 더하고 최댓값은 큰 쪽을 둔다(PostgreSQL·SQLite 모두).
- 테이블 `ops_request_metrics`(Alembic `fcf5ce5e68e1`, 테이블·인덱스 추가만): `docs/contracts/db.md`.
- 설정: `OPS_METRICS_ENABLED`(기본 false), `OPS_METRICS_BUCKET_SECONDS`(300), `OPS_METRICS_RETENTION_DAYS`(90). 구간·보관 일수는 추측으로 정한 초기값이라 실제 트래픽과 저장량을 본 뒤 조정한다.
- 계측 PR 에는 엔드포인트가 없고, 조회는 아래 "조회 API" 에서 한다.

### 조회 API (PR 4, `/admin/ops/*`, 읽기 전용)
- `GET /admin/ops/summary?range=1h|24h|7d`: 요청 수, 5xx·4xx 건수, 5xx 비율, 평균·최대 응답 시간, 구간별 추이(빈 구간은 0). 막대 길이는 1h=5분, 24h=1시간, 7d=1일.
- `GET /admin/ops/apis?range=...`: 메서드+경로 패턴별 요청 수, 상태코드 구분별 건수, 5xx 비율, 평균·최대 응답 시간(요청 수 순, 최대 100개).
- 권한: `require_operator("ops_admin")` — 로그인 없으면 401, 허용 목록에 없으면 403 `operator_required`. 응답에는 `metrics_enabled` 가 있어 계측이 꺼져 있어 0 인지 구분할 수 있다.
- **p95 같은 백분위는 없다**: 저장값이 구간별 합계·최댓값뿐이라 계산할 수 없다. 평균은 합계/요청 수이다.
- `/admin/ops/` 아래 호출은 계측에서 제외한다(화면 자동 갱신이 자기 지표를 부풀리지 않게).
- 한계: DB 에 저장된 구간만 읽는다(아직 닫히지 않은 최신 구간은 구간이 바뀐 뒤 반영). 평균 응답 시간은 모든 상태코드 구분을 합친 값이다. 조회 시작은 저장 구간 경계로 내리고, 막대 간격은 저장 구간보다 가늘어지지 않는다. `/apis` 는 최대 100개이며 `total_routes`·`truncated` 로 잘림을 알린다.
- 시험: `ops_admin/tests/test_ops_read_api.py`(권한, 기간 합산, 경로별 집계, 빈 데이터, 잘못된 range). 실제 PostgreSQL 에서의 조회는 아직 확인하지 않았다(SQLite 시험).

### 오류 이벤트 (1-c-2, `OPS_ERRORS_ENABLED=true` 일 때만 동작, 기본 꺼짐)
- `app/features/ops_admin/masking.py`: 오류 메시지의 개인정보·식별자를 가린다(공용 검출기 + 토큰·UUID·id·URL 쿼리·SQL·IP·홈 경로). 길이 200자, 가림 실패 시 메시지를 버린다. 한국어 이름·주소는 일부 놓칠 수 있다.
- `app/features/ops_admin/error_service.py`: 5xx 응답, 처리되지 않은 예외, 401/403 만 지문별로 합쳐 `ops_error_events` 에 저장한다(4xx 나머지는 저장 안 함). 응답을 보낸 뒤 백그라운드에서 저장하므로 저장이 느리거나 실패해도 응답에는 영향이 없다. 인증 실패는 메시지 없이 응답 code 만 둔다. 예외는 클래스 이름과 발생 위치(`app/...py:줄`)만 남기고 스택의 변수 값은 남기지 않는다.
- `app/shared/errors.py`: **처리되지 않은 예외 응답이 앱 공통 형식 `{code:"internal_error", message}` 로 바뀌었다**(전에는 Starlette 기본 "Internal Server Error" 텍스트). 하위 호환이 깨지는 변경이다. 계측이 켜져 있으면 이 응답에도 `X-Trace-Id` 를 붙인다. shared 가 기능 코드를 import 하지 않도록 관찰자 등록 함수(`set_error_observer`)만 두고 `main.py` 가 연결한다.
- 테이블 `ops_error_events`(Alembic `2110458d9b12`, 테이블·인덱스 추가만): `docs/contracts/db.md`. 설정: `OPS_ERRORS_ENABLED`(기본 false), `OPS_ERRORS_RETENTION_DAYS`(90).
- 이 PR 에는 엔드포인트가 없다(목록·상세 API 는 1-c-3).

## 아직 없는 것
- 오류 이벤트 조회 API(1-c-3)와 화면, 처리 상태 변경(2단계), 배포 이력, 인프라(Cloud Run 등) 지표, Agent, RAG.
- (운영자 인증 `require_operator` 는 병합된 release/1.2 에 있다.)

## 확인되지 않은 것
- Cloud Run 에서 응답 뒤 저장이 CPU 제한 없이 끝나는지, 인스턴스가 여러 개일 때의 실제 저장량·지연.
- 공용 PostgreSQL 에는 아직 테이블이 없다. 병합 뒤 통합 때 DB 담당자가 반영해야 하며, 그 전에는 `OPS_METRICS_ENABLED` 를 켜지 않는다(켜도 저장이 실패해 집계를 버릴 뿐 요청은 정상이다).
- 오류 이벤트(`ops_error_events`)도 공용 DB 반영 전에는 `OPS_ERRORS_ENABLED` 를 켜지 않는다(켜도 저장이 실패해 로그에 예외 클래스 이름만 남는다).
- 오류 이벤트는 응답을 보낸 뒤 백그라운드로 저장한다. Cloud Run 에서 응답 뒤 CPU 가 제한되면 저장이 끝나지 않을 수 있다(미확인, 요청 지표와 같은 우려).
- 개인정보 가림은 정규식 기반이라 한국어 이름·주소는 일부 놓칠 수 있다(예: 도로명 일부가 남는다). 가림 실패 시 메시지를 버리지만 놓친 값을 알 수는 없다.
