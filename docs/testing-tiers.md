# API 테스트 3단계 (FAST / MEDIUM / FULL)

API 전체 `pytest` 는 8,025건이고 이 PC(Windows)에서 **혼자 돌려 3시간 53분**(13,972초, 2026-11-21 실측)이 걸렸다. 코드를 고칠 때마다 이걸 돌리면 개발이 멈춘다.
이 문서는 **테스트를 줄이는 것이 아니라 같은 테스트를 불필요하게 반복하는 비용을 줄이는** 운영 기준이다. 병합 직전·릴리스 때는 FULL 을 그대로 돌린다.

모든 명령은 `apps/api` 에서, 가상환경을 켠 상태로 실행한다(`python -m evals...`·`scripts/` 처럼 모듈을 직접 실행할 때는 `PYTHONPATH=.` 를 붙인다. 이 문서의 측정은 모두 `PYTHONPATH=.` 로 실행했다).

## 1. 왜 느린가 (실측)

`pytest --durations=0 --durations-min=0` 결과(통합 브랜치, 8,025건, 다른 시험 없이 단독 실행):

| 구간 | 합계 | 비율 |
|---|---|---|
| setup (픽스처 준비) | 8,827초 | 63% |
| teardown (픽스처 정리) | 2,870초 | 21% |
| call (테스트 본문) | 2,235초 | 16% |

- **원인**: `conftest.py` 의 `client` 픽스처가 테스트마다 `TestClient`(앱 시작 → `init_db()` 가 87개 테이블 생성)를 만들고 끝나면 `Base.metadata.drop_all` 한다. 파일형 임시 SQLite 에서 테스트 1건당 시작 약 1.0~1.5초 + 정리 약 0.3~1초(디스크가 밀리면 8초까지 튄다)가 든다. `client` 를 쓰는 테스트가 대부분이라 시간이 건수에 비례한다.
- `client` 를 쓰지 않는 테스트는 빠르다(예: `tests/test_security_matrix.py` 857건 합계 42초, 개인정보 탐지기 단위 시험 2초).
- 영역별 합계(초): `tests/agent_eval` 3,278 · 소통(family_chat) 2,984 · ai_assistant 1,677 · family_group 1,237 · schedule 968 · play 783 · billing 747 · family_memory 706.
- 시험 수집(import)만 약 65초가 든다(앱·모델 로딩). 파일을 지정하면 몇 초다.
- **`.githooks/pre-push` 가 도는 `scripts/check_local.py`(빠른 검사)는 `tests/` 폴더 전체**(합계 약 65분, 그중 `tests/agent_eval` 55분)라 이름과 달리 빠르지 않다.

## 2. 단계별 범위와 측정 시간

| 단계 | 언제 | 범위 |
|---|---|---|
| FAST | 개발 중 반복 | 고친 파일과 직접 관련된 테스트 파일. 변경 기능의 주요 실패·경계 조건 포함 |
| MEDIUM | PR 작성·갱신 전 | 고친 기능 폴더 전체 + 관련 Agent·Tool Calling 회귀 + 관련 보안·권한 + DB 통합 |
| FULL | 병합 직전(여러 기능 통합·중요 운영 변경·릴리스) | API 전체 pytest + PostgreSQL 마이그레이션·스키마 검증 + PG E2E + 모바일 lint |

측정 시간(건수 / FAST 실측 wall / MEDIUM 은 전체 실행 durations 에서 해당 파일 합계):

| 영역 | FAST | FAST 실측 | MEDIUM | MEDIUM 합계 |
|---|---|---|---|---|
| 소통 Agent | 46건 | 88초 | 836건 | 약 66분 |
| 소통 메시지 검색 | 40건 | 111초 | 111건 | 약 8분 |
| 일정 Agent | 155건 | 290초 | 449건 | 약 20분 |
| 정산 Agent | 47건 | 149초 | 189건 | 약 13분 |
| 개인정보·보안 | 280건 | 수 초(측정치 2초) | 1,416건 | 약 3분 |
| DB 모델·마이그레이션 | 46건 | 68초 | 98건 | 약 1분 |
| Tool Calling 평가기 | 330건 | 98초 | 2,467건 | 약 55분 |

## 3. 변경 영역별 명령 (실제 존재하는 파일만)

`F=app/features/family_chat/tests`, `A=app/features/ai_assistant/tests`, `S=app/features/schedule`, `B=app/features/billing/tests`, `P=app/shared/privacy/tests`, `E=tests/agent_eval` 로 줄여 쓴다. 실제 입력할 때는 경로를 펼친다.
`python -m pytest -q -p no:cacheprovider <경로…>` 형태로 실행한다.

### 소통 Agent (`family_chat/agent.py`, `ai_assistant` 의 소통 호출)
- FAST: `$F/test_agent_announcement_search.py $F/test_agent_isolation_statement.py $F/test_agent_max_tokens.py $A/test_ask_family_chat.py $A/test_agent_name_token_args.py`
- MEDIUM: `$F` 폴더 전체 + `$A/test_ask_family_chat.py $A/test_agent_name_token_args.py $A/test_direct_agent_reply.py $A/test_direct_room_assistant.py $A/test_room_assistant_post.py $A/test_room_context.py $A/test_room_visibility.py $A/test_tab_agents.py $E/test_scope_leak_private_ids.py $E/test_answer_key_isolation.py $E/test_runner_isolation.py tests/test_membership_enforcement.py`

### 소통 메시지 검색 (`family_chat` 검색·공지 검색)
- FAST: `$F/test_search.py $F/test_agent_announcement_search.py`
- MEDIUM: FAST + `$F/test_ai_privacy.py $F/test_ai_direct.py $F/test_rooms.py $F/test_message_paging.py tests/test_membership_enforcement.py`

### 일정 Agent (`schedule/agent/*`)
- FAST: `$S/agent/tests/test_modify.py $S/agent/tests/test_request_agent.py $S/agent/tests/test_register.py $S/agent/tests/test_period.py $S/agent/tests/test_agent.py`
- MEDIUM: `$S` 폴더 전체 + `$A/test_ask_schedule.py $A/test_room_schedule.py $A/test_schedule_confirm_cards.py $E/test_schedule_outcome.py tests/test_push_schedule.py`

### 정산 Agent (`billing/agent`)
- FAST: `$B/test_billing_agent_write.py $B/test_billing_agent_write_stage1.py $B/test_billing_agent_split.py $B/test_billing_agent_update_expense.py $B/test_billing_agent_delete_expense.py $B/test_billing_agent_chat.py $B/test_billing_agent_mask.py`
- MEDIUM: `$B` 폴더 전체 + `tests/test_schema_gate_billing.py`

### 개인정보 탐지·보안 (`app/shared/privacy`, 권한·마스킹)
- FAST: `$P/test_detectors.py $P/test_hardening.py $P/test_gateway.py $P/test_pseudonymizer.py $P/test_tokenize_mapped_names.py $P/test_honorific_alias.py`
- MEDIUM: `app/shared/privacy` 폴더 전체 + `$F/test_ai_privacy.py tests/test_security_matrix.py tests/test_membership_enforcement.py $E/test_exposure.py $E/test_scrub.py`
- 권한·개인정보·쓰기 동작을 바꾼 PR 은 어느 영역이든 위 `tests/test_security_matrix.py tests/test_membership_enforcement.py` 를 FAST 에 **추가**한다(합계 약 1분).

### DB 모델·마이그레이션 (`models.py`, `alembic/`)
- FAST: `tests/test_model_registry.py tests/test_schema_gate.py tests/test_schema_gate_billing.py tests/test_migration_risk.py tests/test_migration_unsafe_python.py tests/test_db_hide_parameters.py`
- MEDIUM: FAST + `tests/test_allowance_migration.py tests/test_default_subscription_migration.py tests/test_shared_db_deploy.py tests/test_membership_enforcement.py`
- 스키마가 바뀌면 격리 PostgreSQL(임시 컨테이너)에서 `python scripts/check_alembic_migrations.py heads`, `assert-empty`, `alembic upgrade head`, `assert-at-head`, `python scripts/check_schema_matches_models.py` 를 FULL 의 일부로 반드시 돌린다. 공용 DB·MVP DB 는 쓰지 않는다.

### Tool Calling 평가기 (`evals/agent_eval`, `tests/agent_eval`)
- FAST(채점·스키마·저장): `$E/test_scoring.py $E/test_matchers.py $E/test_scorer_v2.py $E/test_criteria_v2.py $E/test_schema.py $E/test_store.py $E/test_runner_write_gate.py $E/test_runner_unsupported.py`
- 실행기·게이트를 고쳤으면 FAST 에 `$E/test_real_gate.py $E/test_real_hardening.py $E/test_preflight.py $E/test_runner_budget.py` 를 추가한다.
- MEDIUM: `tests/agent_eval` 폴더 전체(약 55분). 시드·월드·정답지·해시를 건드리면 `test_val_pins.py`, `test_world_variants.py`, `test_seeds_world.py`, `test_answer_key_isolation.py` 를 줄이지 않는다.
- 실제 Claude 호출이 필요한 평가는 이 단계에 없다(별도 승인 전까지 실행하지 않는다).

## 4. 실행 정책

1. 코드를 고칠 때마다 FULL 을 자동 실행하지 않는다. **FAST → MEDIUM** 순서로 올라간다.
2. 실패하면 먼저 원인을 분석하고 그 테스트만 다시 돌린다. 실패를 `skip`/`xfail`/정답 변경으로 가리지 않는다.
3. 문서만 고쳤다면 해당 문서의 일관성(링크·경로·명령·숫자가 코드와 맞는지, `git diff --check`)으로 시작한다. API 계약 문서(`docs/contracts/openapi.json`)는 직접 고치지 않고 `PYTHONPATH=. python scripts/export_openapi.py` 로 만든다.
4. **보안·권한·쓰기·DB 스키마 변경은 위 영역별 보안 시험·스키마 검사를 줄이지 않는다.**
5. 병합 직전 FULL 필요 여부는 변경 위험과 최근 통합 검증 이력으로 판단한다. 생략하면 PR 에 **돌리지 않은 범위를 적는다**.
6. 실제 Claude API 평가, 공용·운영 DB 접근은 이 단계에 포함되지 않는다.

## 5. FULL 이 반드시 필요한 변경

- 여러 기능에 걸친 통합 PR, 릴리스·운영 배포 직전
- `app/shared/*`(auth, db, errors, llm, privacy, schema 게이트), `conftest.py`·테스트 헬퍼, `pyproject.toml`·의존성
- DB 스키마·모델·Alembic 리비전(+ 격리 PostgreSQL 검사 + PG E2E 13개 `GABEE_PG16_E2E=1`)
- 권한·인증·개인정보·외부 호출(LLM·네트워크) 경로 변경
- 평가 시드·월드·정답지·해시·채점기 변경(고정값 시험 포함)
- 앱(`apps/mobile`)을 건드렸으면 `npm ci && npm run lint`

FULL 명령: `python scripts/check_local.py --full` (ruff 린트·포맷 → Alembic head → 시크릿 패턴 → 전체 pytest).

## 6. 아직 적용하지 않은 개선 후보 (동작 보존 확인 필요)

- **테스트 전용 SQLite 설정**(`PRAGMA journal_mode=MEMORY`, `synchronous=OFF`)을 임시 DB 연결에 적용 — 임시 파일이라 내구성이 필요 없다. 실측: FAST 6개 단계 합계 804초 → 140초(5~9배), 통과·실패 결과 동일. **전체 8,025건도 3시간 52분 → 24분 50초(약 9.4배)**, 통과 7,918건으로 같고 실패 목록은 날짜·순서에 따라 달라지는 테스트(§7)만 달랐다. 임시로 `conftest.py` 에 넣고 잰 값이며 저장소에는 넣지 않았다. `conftest.py` 를 바꾸는 일이라 별도 PR 로 제안한다.

## 7. 2026-11-21 전체 실행에서 확인한 날짜 의존 시험

- `app/features/schedule/agent/tests/test_modify.py::test_delete_many_asks_once_then_deletes_each`: 오늘+1~+3일 일정 3건을 만들고 "이번 주"로 지운다. 목~토요일에는 3번째가 다음 주라 실패한다(코드 읽기 기준 추정, 평일 재실행으로 확인 필요).
- `app/features/play/tests/test_quiz_rec.py::test_items_are_half_for_each_user`: 한 번은 실패, 다음 실행은 통과(비결정적).
- 평가 해시 고정값 시험(`test_val_pins`)은 하위 Agent 프롬프트의 "오늘은 <날짜>" 때문에 하루 만에 깨졌고, 고정 시계로 계산하도록 고쳤다(#491 브랜치).
- `pytest-xdist` 병렬화는 DB·전역 상태(`MEMORY_RESETS` 모듈 변수)·임시 파일의 프로세스 격리를 검증한 뒤에만 검토한다. 지금은 도입하지 않는다.
- `client` 픽스처 범위 변경(모듈 단위 재사용 등)은 동작 보존 테스트 없이 하지 않는다.
