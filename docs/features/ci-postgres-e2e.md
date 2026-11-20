# PostgreSQL e2e(`*_pg_e2e`)의 CI 편입 검토 (2026-11-19, 제안 — 워크플로 변경은 별도 요청)

## 현황
- `GABEE_PG16_E2E=1` 일 때만 도는 e2e 13개 파일(53개 시험)이 있다. Docker 가 필요하고 모듈마다 임시 `pgvector/pgvector:pg16` 컨테이너를 따로 띄운다(공용·개인·MVP DB 에 접속하지 않는다).
- **CI(`.github/workflows/ci-check.yml`)는 이 변수를 설정하지 않아 한 번도 실행하지 않는다.** `api` 잡의 `pytest` 에서는 skip, `api-postgres` 잡은 서비스 컨테이너로 `pytest tests/test_pgvector.py` 만 돌린다. 그래서 가입 자동 승인(#144)·사람별 분석 캐시·Alembic 병합 리비전으로 시험이 낡아도 한 달 넘게 몰랐다(2026-11-19 에 13건 실패 확인, #467·#472·#473 으로 수리).
- 2026-11-19 로컬 전체 실행(병합된 release/1.3): **55 passed, 1 skipped, 약 602초(10분 2초)**. 한 건의 skip 은 `tests/test_pgvector.py`(`PGVECTOR_TEST_DATABASE_URL` 이 로컬에 없어서)이며 CI 의 `api-postgres` 에서는 변수가 설정돼 실행된다(숨은 실패가 아니다).
- 파일별 시험 수: ai_guard 7, email 7, family_memory 6, join 5(동시 가입 회귀 2 포함), login 5, schema_gate 5, signup 4, photo_taken_at 3, profile 3, social 3, weekly_news 3, chat_share 1, library_flow 1.

## 실행 시간과 인프라 영향
- 시간: 로컬 약 10분(컨테이너 13번 기동 + 동시 경쟁 시험). `ubuntu-latest` 는 Docker 가 설치돼 있고 네트워크가 빨라 비슷하거나 더 빠를 것으로 본다(미측정).
- 지금 `api` 잡이 약 23~25분(`pytest` 7,000건)이므로 **별도 잡으로 병렬 실행하면 전체 대기 시간은 늘지 않고** 러너 사용 시간만 약 10분 늘어난다.
- 자원: 컨테이너는 모듈 단위로 순차 생성·삭제(동시에 하나), 메모리·포트 영향 작음. 동시 경쟁 시험(스레드 8개)은 CI 러너의 코어 수가 적으면 시간이 흔들릴 수 있다.
- 비밀·권한: 새 비밀 없음. 시험이 만드는 임시 DB 자격은 시험 안에서 무작위로 만든다.

## 편입 제안(권장 순서)
1. **새 잡 `api-pg-e2e`**(같은 `workflow_dispatch` 트리거, `needs` 없음, `timeout-minutes: 25`)를 추가한다: Python·의존성 설치 뒤 `GABEE_PG16_E2E=1 pytest tests -k "pg_e2e" -q`. `.github/workflows/` 수정이라 별도 요청·승인이 필요하다.
2. **첫 2주는 참고용**(`continue-on-error: true`)으로 돌려 러너에서의 시간과 불안정(flaky) 여부를 본다. 불안정한 시험이 있으면 원인을 고치고(시험 약화·skip 으로 통과시키지 않는다) 필수로 올린다.
3. 필수가 되면 병합 전 필수 검증 목록(api·api-postgres·mobile)에 `api-pg-e2e` 를 넣는다. 느리면 파일을 3개 묶음(예: {ai_guard, email, family_memory}, {join, login, schema_gate, signup}, {나머지})으로 matrix 분할해 각 3~4분으로 줄인다(`pytest-xdist` 는 의존성 추가라 쓰지 않는다).
4. 같은 모양의 낡음을 막기 위해 e2e 도우미(`family()` 등)를 한 모듈(예: `tests/pg_e2e_support.py`)로 모으는 정리는 별도 작업으로 둔다(이번 제안 범위 아님).

## 이번 작업에서 바꾸지 않은 것
운영 기능·워크플로·시험 로직(약화 없음). 위 제안은 문서뿐이다.
