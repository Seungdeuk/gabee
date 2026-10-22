# 0006. DB 가 코드와 맞지 않아도 서버는 시작하고, 스키마가 준비되지 않은 기능만 503 으로 막는다

- 날짜: 2026-10-22
- 결정: PostgreSQL 에서 `alembic_version` 이 코드 head 와 다르면 서버 기동을 막던 방식([0004](0004-alembic-migrations.md))을 폐지한다. 서버는 DB 리비전·연결 상태와 무관하게 시작하고, **기능별로 실제 스키마를 점검**해서 준비되지 않은 기능의 API 만 `503` 을 돌려준다. 점검·재점검·상태 확인 API 는 `app/shared/schema.py`, `schema_gate.py`, `main.py` 에 있다.
- 이유: 5명이 병렬로 개발하며 공용 DB 를 함께 쓰므로 "새 마이그레이션이 들어 있는 코드가 DB 보다 먼저 실행"되거나 반대로 "다른 브랜치의 새 마이그레이션이 이미 적용된 DB 에 오래된 코드가 붙는" 순간이 자주 생긴다. 이때 서버 전체를 죽이면 그 스키마와 무관한 기능(일정·채팅 등)까지 못 쓰게 된다. 반대로 모든 API 를 무조건 허용하면 없는 컬럼을 읽다가 500 이 난다.

## 동작

- **기능별 스키마 의존성**: 각 기능(`family_group`, `family_chat`, `schedule`, `billing`, `care`, `ai_assistant`)의 SQLAlchemy 모델이 쓰는 테이블·컬럼이 DB 에 실제로 있고, 이 코드의 INSERT 를 깨뜨리는 변경(코드가 모르는 'NOT NULL + 기본값 없음' 컬럼, NOT NULL 로 강화된 컬럼)이 없을 때만 그 기능을 연다. 모든 기능은 로그인·그룹 멤버십을 쓰므로 `family_group` 이 준비돼야 한다. `app/shared` 의 공통 모델은 `SHARED_MODEL_FEATURES` 에 쓰는 기능을 등록하고(예: 위치 동의 이력 → `family_group`, `care`), 등록하지 않으면 모든 기능의 전제로 본다.
- **리비전 번호가 아니라 실제 스키마로 판단**: DB 가 코드보다 **앞서** 있어도(알 수 없는 리비전) 호환된다고 가정하지 않고 같은 점검을 통과해야 한다. 리비전 상태(`ready`, `behind`, `ahead_or_unknown`, `no_revision`, `invalid_revision_state`, `multiple_heads`, `code_error`, `db_unavailable`, SQLite 는 `not_applicable`)는 진단 정보이며 `GET /health/db` 의 `status` 가 `ready` 가 아니면 `degraded`/`unavailable` 로 표시한다.
- **응답**: 준비되지 않은 기능은 `503 {"code": "schema_not_ready", ...}`, DB 연결이 안 되면 `503 {"code": "db_unavailable", ...}`, 둘 다 `Retry-After: 5`. `/health` 는 프로세스 생존만 뜻하고 그대로 `ok` 다.
- **서버 재시작 없이 회복**: 점검 결과는 짧게만 캐시한다(준비됨 30초, 준비 안 됨 2초). 마이그레이션이 끝나면 다음 요청부터 열리고 `GET /health/db` 는 즉시 재점검한다(최소 간격 1초). 설정은 `SCHEMA_RECHECK_*`(선택).
- **`GET /health/db`**: DB 연결, 현재 리비전, 코드 head(들), 적용 대기 리비전, 기능별 준비 여부를 돌려준다. 비밀번호·접속 주소·계정·테이블/컬럼 이름은 응답에 싣지 않는다(예외는 클래스 이름만, 상세는 서버 로그). 인증 없이 열려 있으므로 공개 환경이 되면 제한을 검토한다.
- **DB 연결**: PostgreSQL 엔진에 연결 제한 시간 5초와 `pool_pre_ping` 을 둔다. 응답 없는 DB 에서 요청이 오래 붙잡히지 않고, DB 재시작·배포로 끊긴 연결은 자동으로 버려진다.

## 영향과 한계

- DB 가 코드보다 뒤처지면 새 컬럼이 필요한 기능만이 아니라, 그 코드가 읽는 테이블에 컬럼이 없는 기능은 전부 막힌다. 예를 들어 `users` 에 컬럼이 추가된 마이그레이션이 아직 적용되지 않았다면 `family_group` 이 막혀 모든 기능이 503 이다 — 그 코드는 어차피 `users` 를 읽을 수 없다.
- 점검은 컬럼 존재·NULL 허용·기본값만 본다. 타입 변경이나 제약(UNIQUE/FK) 변경은 감지하지 못한다.
- 같은 기능 안에서는 일부 엔드포인트만 열지 않고 기능 단위로 막는다(모델을 공유하기 때문).
- 이 ADR 은 서버 쪽 정책이다. 공용 DB 마이그레이션을 어떻게 적용하는지는 다루지 않는다.
- 검증: SQLite 로 스키마를 어긋나게 만든 단위·통합 시나리오(`tests/test_schema_gate.py`)와, 임시 PostgreSQL 16 컨테이너에서 실제 Alembic 마이그레이션을 쓰는 통합 테스트(`tests/test_schema_gate_pg_e2e.py`, `GABEE_PG16_E2E=1`)로 확인했다.
