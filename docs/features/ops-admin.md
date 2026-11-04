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
- 이 PR 에는 엔드포인트가 없다(조회 API 는 다음 PR).

## 아직 없는 것
- 오류 이벤트 저장(`ops_error_events`), 조회 API(`/admin/ops/*`), 운영 웹, Agent, RAG.
- 운영자 인증 `require_operator` 는 별도 PR(`feature/hojenn-operator-auth`).

## 확인되지 않은 것
- Cloud Run 에서 응답 뒤 저장이 CPU 제한 없이 끝나는지, 인스턴스가 여러 개일 때의 실제 저장량·지연.
- 공용 PostgreSQL 에는 아직 테이블이 없다. 병합 뒤 통합 때 DB 담당자가 반영해야 하며, 그 전에는 `OPS_METRICS_ENABLED` 를 켜지 않는다(켜도 저장이 실패해 집계를 버릴 뿐 요청은 정상이다).
