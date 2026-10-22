> **부분 대체됨(2026-10-22): 실행 주체는 GitHub Self-hosted Runner 에서 공용 DB PC 의 Pull Agent 로 바뀌었다 — [0008](0008-shared-db-pull-agent.md).** 아래의 배포 단계(CI 검증·위험 검사·백업·복원 리허설·적용·사후 검증·HALT)와 안전 규칙은 그대로 유효하고, 러너·`Deploy Shared DB` 워크플로우·러너 격리 정책 관련 부분은 더 이상 쓰지 않는다.

# 0007. 공용 PostgreSQL 마이그레이션을 자동 배포한다 (건별 수동 승인 폐지)

- 날짜: 2026-10-22
- 결정: `main`에 병합된 커밋의 `CI Check`가 모두 성공하면 `Deploy Shared DB` 워크플로우(`.github/workflows/deploy-shared-db.yml`)가 LAN 안의 self-hosted 러너에서 공용 DB(`192.168.0.44:5432/gabee`)에 Alembic 마이그레이션을 자동 적용한다. 마이그레이션마다 담당자 승인을 받는 방식([0005](0005-shared-postgres-env.md))은 폐지한다. 사람(과 Claude Code)은 공용 DB에 직접 `alembic`을 실행하지 않는다.
- 이유: 5명이 Claude Code로 병렬 개발하므로 마이그레이션마다 사람의 수동 적용·승인을 기다리면 병목이 된다. 대신 승인의 역할을 자동 검증(CI, 위험 검사, 백업, 복원 리허설)이 맡는다. 구현은 `apps/api/scripts/shared_db_deploy.py`, `apps/api/scripts/migration_risk.py`.
- **적용 범위**: 공용 *개발* DB 전용이다. 운영 DB가 생기면 같은 구조를 그대로 쓰지 말고 별도 보호(승인 게이트, 별도 계정·환경)를 추가해야 한다.

## 배포 흐름

```
main 병합 → CI Check 완료(workflow_run) → [1] 커밋·CI 검증 → [2] 대상 DB 검증 + 잠금 → [3] 리비전·위험 검사
 → [4] 새 백업(pg_dump 16) → [5] 무결성 확인 → [6] 임시 PostgreSQL 16 에 복원 검증 + 복사본에 리허설
 → [7] 적용 직전 재검증 → [8] gabee_migrator 로 alembic upgrade head → [9] 리비전·스키마·gabee_app 권한 검증 → [10] 기록·알림
```

단계마다 실패하면 이후 단계를 건너뛰고, **[8] 이전 실패는 공용 DB를 전혀 바꾸지 않는다.** 결과는 `noop`(이미 최신) / `skipped`(main 이 더 진행됨) / `dry_run_ok` / `success` / `blocked`(안전 검사 실패, DB 미변경) / `failed`(적용 중·후 실패, `HALT`) / `refused`(대상 불일치)다.

## 보안 모델

| 위협 | 대응 |
|---|---|
| PR 코드가 내부망 DB·러너에 접근 | `pull_request` 계열 트리거를 쓰지 않는다. 트리거는 main 의 CI 완료(`workflow_run`)와 main 한정 수동 재실행(`workflow_dispatch`)뿐이고, `workflow_run` 은 항상 기본 브랜치의 워크플로우 정의로 실행되어 PR 이 이 파일을 바꿔 우회할 수 없다. `tests/test_workflow_safety.py` 가 트리거·권한·러너 라벨 사용처를 검사한다. |
| 로컬 플래그로 CI 우회 | 스크립트에 CI 를 건너뛰는 옵션이 없다. GitHub API 로 ① 대상 SHA 가 main 최신인지 ② 그 SHA 의 `CI Check`(push, main)가 성공했고 필수 Job(`api`, `api-postgres`, `mobile`)이 모두 성공했는지 직접 확인한다. 토큰이 없으면 실행을 거부한다. |
| 검증된 커밋과 다른 코드 배포 | 러너가 정확히 그 SHA 를 체크아웃하고 `git rev-parse HEAD`·작업 트리 청결을 스크립트가 다시 확인한다. 적용 직전에 CI·main 최신 여부를 한 번 더 확인한다(백업·리허설 중 main 이 바뀌면 `skipped`). |
| 동시 실행 | 워크플로우 `concurrency`(취소 없이 대기)와 DB advisory lock(`pg_try_advisory_lock`)을 함께 쓴다. 후자는 GitHub 밖의 수동 실행까지 막는다. |
| 잘못된 DB 대상 | 대상은 코드의 `SHARED`(host·port·db·user)와 정확히 일치해야 하며 환경변수·URL 로 바꿀 수 없다. `family-secretary`·`postgres`·`template*` DB 와 `gabee_app`·`postgres` 계정은 코드에서 거부한다. 연결 후 `current_database()`·`current_user`·서버 주 버전(16)·슈퍼유저 여부를 다시 확인한다. |
| 비밀번호 노출 | `gabee_migrator` 비밀번호는 GitHub 에 저장하지 않고 러너 PC 의 pgpass 파일에만 둔다. 연결은 `passfile` 로만 하며 명령줄·환경변수·URL·로그에 나오지 않는다(`pg_dump` 는 Docker 컨테이너에 pgpass 를 읽기 전용 마운트). |
| `gabee_app` 으로 DDL | 배포는 `gabee_migrator` 만 쓴다. 적용 후 `gabee_app` 이 `public` 스키마에 CREATE 권한이 없는지, 모든 테이블·시퀀스에 앱 권한이 있는지 점검한다. |
| 자동 롤백으로 인한 데이터 손실 | 자동 downgrade·자동 복원 코드를 두지 않는다. Postgres 에서는 전체 마이그레이션이 한 트랜잭션이라 실패하면 DB 가 변하지 않으며, 그 사실을 다시 읽어 확인한 뒤 `HALT` 한다. 복원은 백업을 새 DB 에 올려 사람이 판단한다. |

**남는 위험(수용)**: 개인 저장소에서는 러너 그룹을 쓸 수 없어, 저장소에 쓰기 권한이 있는 협업자가 자기 브랜치에서 `gabee-db-deploy` 라벨을 쓰는 워크플로우를 만들면 그 러너에서 코드를 실행할 수 있다(러너 PC 의 pgpass 접근 가능). 신뢰하는 5명이라는 전제에서 수용하고 다음으로 완화한다: 러너 전용 저권한 OS 계정과 전용 PC 사용, `gabee_migrator` 권한을 DB `gabee` 로 한정(`family-secretary` 접속 불가), `pg_hba.conf` 로 러너 IP 만 허용. GitHub Pro/Team 으로 올리면 브랜치 보호(필수 상태 검사)와 Environment(main 한정 비밀) 로 보강할 수 있다 — 지금은 `main` 병합 차단이 강제되지 않으므로, 배포 게이트를 PR 병합이 아니라 **main 커밋의 CI 성공**에 걸었다.

## 러너 격리 정책 — 활성화 전 선행 조건

**문제**: 개인 저장소(Free)는 러너 그룹·Environment·브랜치 보호를 쓸 수 없다. 쓰기 권한이 있는 협업자 누구든 자기 브랜치에 `runs-on: [self-hosted, gabee-db-deploy]` 워크플로우를 만들어 push 하면 그 러너에서 임의 코드를 실행할 수 있고, 러너 PC 에 있는 pgpass 를 읽어 `gabee_migrator` 비밀번호를 얻을 수 있다. `main` 의 정적 검사나 이 워크플로우의 `if` 조건은 **다른 브랜치의 워크플로우 파일**을 막지 못한다(`workflow_dispatch` 도 브랜치별 파일을 쓴다).

**결정**: 격리 정책이 확정·적용되기 전에는 자동 적용을 활성화하지 않는다. 코드로도 강제한다 — 배포 Job 은 `SHARED_DB_DEPLOY_ENABLED` 외에 `SHARED_DB_RUNNER_ISOLATION_APPROVED` 가 `true` 여야 실행된다(둘 다 저장소 변수, 기본 없음). 후자는 아래 중 하나 이상을 적용했다는 사람의 명시적 확인이다.

| 선택지 | 효과 | 비용·한계 |
|---|---|---|
| A. GitHub Pro/Team + **Environment(`main` 브랜치 한정)** + 브랜치 보호 | 비밀을 `main` 배포 Job 에만 전달, 협업자 브랜치 워크플로우는 비밀·승인된 러너에 접근 불가. 필수 상태 검사도 강제 가능 | 유료 플랜. 러너 자체가 협업자 워크플로우에 호출될 수 있는 점은 남으므로 B 와 병행 권장 |
| B. **권한 분리 실행기**: pgpass 는 별도 OS 계정(`gabee-deployer`)만 읽을 수 있고, 러너 계정은 그 계정으로 고정 위치(러너 계정이 쓰기 불가)에 설치된 검증된 배포 스크립트만 실행하는 작업 스케줄러 작업을 트리거한다 | 협업자 코드가 러너에서 실행돼도 비밀번호 파일을 읽을 수 없다 | 설치·갱신 절차 필요, 배포 스크립트 버전 고정·서명 확인 설계 필요 |
| C. 전용 러너 PC·계정 + DB 측 제한 | 노출돼도 피해 범위를 DB `gabee` 로 한정(`family-secretary` 접근 불가, `pg_hba.conf` 로 러너 IP 만) | 비밀번호 노출 자체는 막지 못함 — 단독으로는 충분하지 않다 |
| D. 배포 직전 일회성 비밀번호 발급·배포 후 폐기 | 파일에 남는 장기 비밀번호가 없다 | 발급 권한을 가진 별도 계정·절차 필요 |

C 는 어떤 경우에도 적용하고(피해 범위 한정), A 또는 B 를 더해 비밀번호 접근 자체를 막는 구성을 권장한다. 선택과 적용 결과는 이 문서에 날짜와 함께 기록한 뒤 변수를 켠다.

## 마이그레이션 안전성

| 상황 | 동작 |
|---|---|
| 여러 Alembic head | `blocked` (PR 단계의 `api-postgres` 도 막음) |
| 이미 최신 | `noop` — 백업·적용 없음 |
| DB 에 있는 리비전이 코드에 없음 / `alembic_version` 이상 | `blocked` |
| main 과의 동시 변경 | 배포 SHA 가 main 최신이 아니면 `skipped`(더 새 커밋의 배포가 이어받음) |
| 백업 실패·무결성 실패·복원 검증 실패 | `blocked`, 공용 DB 미변경 |
| DROP/rename/타입 변경/`TRUNCATE`·`DELETE`/`CONCURRENTLY` 등 | `blocked` — 리비전 docstring 에 `destructive-approved: PR #<번호>` 가 있으면 허용(PR 리뷰가 승인한 흔적) |
| 기존 데이터와 충돌하는 NOT NULL/UNIQUE/FK | 경고로 기록하고, **실제 백업을 복원한 복사본에 먼저 적용하는 리허설**이 데이터 충돌을 잡아 `blocked` |
| 마이그레이션 중 연결 실패 | `failed` + `HALT`, 실패 후 DB 상태를 다시 읽어 변경 여부를 기록 |
| 적용 후 스키마·리비전·권한 불일치 | `failed` + `HALT` |
| 기존 FastAPI 와 신규 스키마 | 하위 호환 변경만 자동 적용(위험 검사). 서버 쪽 처리는 ADR 0006(기능별 스키마 점검·503) |

## 서버 쪽 전제 (ADR 0006)

자동 배포가 끝나기 전에 새 코드가 실행되는 일시적 불일치는 [0006](0006-schema-gate-degraded-start.md)의 정책으로 처리한다: 서버는 DB 리비전과 무관하게 시작하고, 스키마가 준비되지 않은 기능만 `503` 이며, 배포가 끝나면 서버 재시작 없이 열린다(`GET /health/db`). 배포가 실패하면 DB 는 이전 그대로이므로 서버는 부분 동작을 유지하고 `db-deploy-failed` 이슈가 남는다. 이 ADR 은 그 정책 위에서 마이그레이션을 어떻게 안전하게 적용하는지를 다룬다.

## 병렬 개발·배포 순서

1. 5명이 각자 최신 `main` 에서 브랜치를 만들어 리비전을 병렬로 작성한다(혼자서는 단일 head).
2. PR 의 `ci-check`(`pull_request`)는 PR 을 최신 `main` 과 합친 merge ref 를 검사하므로, 다른 PR 이 먼저 병합돼 head 가 둘이 되면 `api-postgres` 가 실패한다. 나중에 병합되는 쪽이 `main` 을 받아 `down_revision` 을 현재 head 로 옮기고 다시 검증한다. 병합 버튼을 누르기 직전에 `main` 이 또 바뀌었을 수 있으므로(플랜상 "최신 상태 필수" 강제 불가) 병합 후 `push` 이벤트의 CI 가 다시 단일 head 를 확인하고, 실패하면 배포가 시작되지 않는다.
3. 병합 → `CI Check`(main push) → `Deploy Shared DB` 가 새 마이그레이션을 먼저 적용한다. 새 코드를 받은 팀원이 그보다 먼저 서버를 띄워도 ADR 0006 의 정책으로 영향 기능만 잠시 503 이다.
4. 구 코드와 호환되지 않는 변경(컬럼 삭제·이름 변경·NOT NULL 강화)은 한 번에 하지 않고 expand → deploy → contract 로 나눈다: ① 새 컬럼/테이블을 nullable 또는 기본값과 함께 추가(구 코드 호환) ② 코드 전환 ③ 모두가 새 코드를 받은 뒤 별도 PR 에서 제거(`destructive-approved`).

## 백업 정책

- 매 배포마다 `gabee` DB 만 `pg_dump -Fc`(PostgreSQL 16 클라이언트 = 러너의 `pgvector/pgvector:pg16` 컨테이너)로 `gabee_pg16_deploy_<UTC시각>_<이전>-to-<이후>.dump` 에 저장한다(`.partial` 로 쓰고 성공 후 이름 변경, `.sha256` 동봉).
- 사람이 만든 기존 백업(`gabee_pg16.dump` 등)과 패턴에 맞지 않는 파일은 읽거나 지우지 않는다. 최근 14개만 보관한다(성공 뒤에만 정리).
- 백업에는 공용 DB 의 실제 데이터가 있으므로 Git 에 넣지 않고(`.gitignore`) 소유자 전용 권한으로 저장한다(Windows `icacls`, 실패 시 경고). 외부 클라우드 동기화 폴더에 두지 않는다.

## 실패 후 재시도 정책

`blocked`/`skipped` 는 DB 를 건드리지 않았으므로 다음 main 커밋이나 `Run workflow` 로 다시 시도하면 된다. `failed` 는 `<STATE_DIR>\HALT` 를 남기고 이후 배포를 모두 거부한다. 원인을 고친 뒤 HALT 파일을 지워야 재개된다. 실패는 Actions 요약, `deploy-log.jsonl`, GitHub 이슈(`db-deploy-failed`)로 남는다.

## 활성화 상태와 후속

- 이 PR 로 코드와 워크플로우는 추가되지만 **비활성**이다(`SHARED_DB_DEPLOY_ENABLED` 와 `SHARED_DB_RUNNER_ISOLATION_APPROVED` 변수가 없으면 Job 이 건너뛰어짐). 최초 설정·단계적 활성화 절차는 README "팀 공용 PostgreSQL 에 연결하기" 참고.
- 검증: 격리 PostgreSQL 16 컨테이너를 가짜 공용 DB 로 쓰는 e2e(`tests/test_shared_db_deploy_e2e.py`, `GABEE_DEPLOY_E2E=1`)와 Docker 불필요한 단위 테스트(CI 에서 실행)로 위 표의 상황을 확인했다. 실제 공용 DB 에는 접속하지 않았다.
- 후속: GitHub 플랜 상향 후 필수 상태 검사·Environment 적용, 파괴적 변경 린트를 PR 단계 CI 에도 추가.
