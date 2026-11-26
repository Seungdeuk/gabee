# family-secretary

가족용 비서 앱. React Native (Expo) + FastAPI 모노레포. 협업 규칙은 [CLAUDE.md](CLAUDE.md), [CONTRIBUTING.md](CONTRIBUTING.md) 참고.

## 브랜치와 맡는 기능

| 브랜치 | 맡는 기능 |
|---|---|
| `ai_assistant-ingest` | AI 비서 정제화: 원본 전처리, 자동 분류 |
| `ai_assistant-knowledge` | AI 비서 최적화: 데이터화, 벡터 DB |
| `schedule` | 일정 |
| `family_chat` | 소통(가족 채팅) |
| `billing-care` | 가계, 돌봄 |

## 서버 (apps/api)

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate            # cmd. Git Bash: source .venv/Scripts/activate / macOS·Linux: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env            # macOS·Linux·Git Bash: cp
uvicorn app.main:app --reload     # http://localhost:8000/docs
pytest
```

## docker 로 서버 + DB 실행

```bash
copy .env.example .env                        # 값(DB 비밀번호 등)을 채운다
docker compose up -d db                       # PostgreSQL(pgvector) 먼저 기동
docker compose run --rm api alembic upgrade head   # 스키마 적용(최초 1번, 이후 마이그레이션 추가될 때마다)
docker compose up -d --build api              # API 기동 → http://localhost:8000/docs
```

DB 는 `pgvector/pgvector:pg16` 이미지를 쓰고, `127.0.0.1` 에만 포트를 연다(외부 공개 안 함). **스키마(테이블 생성·변경)는 Alembic 이 전담하고, API 는 서버 시작 시 스키마를 바꾸지 않는다.** 마이그레이션이 덜 된 DB 에서도 서버는 시작하되, 그 스키마가 필요한 기능의 API 만 `503`(`schema_not_ready`)을 돌려준다(아래 오류 항목, `GET /health/db`). 개인 DB 는 `db` → `alembic upgrade head` → `api` 순서로 맞춰 두면 전부 열린다.

pgvector 설치 확인 (PowerShell, `.env` 의 값을 그대로 쓴다):

```powershell
docker compose exec db psql -U postgres -d gabee -c "SELECT * FROM pg_extension WHERE extname='vector';"
```

DB 연결 확인:

```powershell
docker compose ps                 # db 가 healthy 인지 확인
curl http://localhost:8000/health # {"status":"ok"} 면 API가 DB에 연결됨
```

Docker 없이 `uvicorn`으로 서버만 띄우면서 이 Postgres에 붙이려면 `apps/api/.env`의 `DATABASE_URL`을 `postgresql+psycopg://<POSTGRES_USER>:<POSTGRES_PASSWORD>@127.0.0.1:<POSTGRES_PORT>/<POSTGRES_DB>`로 바꾼다(기본값은 SQLite. `localhost`보다 `127.0.0.1`을 권장 — 아래 오류 참고).

자주 발생하는 오류:
- **포트 충돌(5432 가 이미 사용 중)**: 루트 `.env`의 `POSTGRES_PORT`를 다른 값(예: `5433`)으로 바꾸고 `docker compose up --build`를 다시 실행한다.
- **`.env`를 안 만들고 실행**: `POSTGRES_USER` 등이 빈 값이 되어 DB가 뜨지 않는다. `copy .env.example .env`를 먼저 한다.
- **이미 `postgres:16`(pgvector 없음)로 떠 있던 볼륨을 쓰던 경우**: 볼륨은 그대로 유지된다. 이미지만 `pgvector/pgvector:pg16`으로 바뀌고, `alembic upgrade head`(기존에 테이블이 있었다면 `alembic stamp head` — 아래 참고)를 실행하면 확장이 켜진다. 데이터는 삭제되지 않는다.
- **Windows 에서 `localhost:5432`로 접속이 멈추거나 느린 경우**: IPv6(`::1`)로 먼저 시도하다가 지연될 수 있다. `localhost` 대신 `127.0.0.1`을 쓴다(Docker는 `127.0.0.1`에만 바인딩하므로 어차피 이게 맞는 주소다).
- **일부 API 가 `503 schema_not_ready` / `db_unavailable` 을 돌려주는 경우**: 서버는 떠 있지만 DB 스키마가 그 기능의 코드보다 뒤처졌거나 DB 에 연결할 수 없는 상태다. `GET /health/db` 로 DB 리비전·코드 head·기능별 준비 상태를 확인한다. 개인 DB 는 `docker compose run --rm api alembic upgrade head` 를 실행하면 서버 재시작 없이 몇 초 안에 열린다. 공용 DB 는 통합 때 DB 담당자가 반영하면 열린다(아래 "통합" 절). 평소 개발은 개인 로컬 DB 로 한다.
- **`apps/api/alembic.ini`를 수정했는데 `UnicodeDecodeError`가 나는 경우**: Windows 한글 로캘(cp949)에서 이 파일에 한글(비-ASCII) 문자가 있으면 `configparser`가 깨진다. `alembic.ini`에는 영어만 쓴다.

이 프로젝트의 DB/API 는 폴더명으로 컨테이너·볼륨·네트워크 이름이 접두사 처리되어, 다른 프로젝트의 PostgreSQL/Docker 볼륨과 자동으로 분리된다.

### Alembic (DB 마이그레이션)

PostgreSQL 스키마는 `apps/api/alembic/`의 Alembic 리비전으로만 바꾼다. SQLite(로컬 비-Docker 실행, 테스트)는 그대로 `init_db()`가 테이블을 바로 만든다 — Alembic을 거치지 않는다.

```bash
cd apps/api
source .venv/Scripts/activate              # 가상환경 활성화(위 "서버" 절 참고)

# 새 마이그레이션 만들기 (모델을 바꾼 뒤)
DATABASE_URL=postgresql+psycopg://<user>:<pw>@127.0.0.1:<port>/<db> \
  alembic revision --autogenerate -m "설명"
# 생성된 apps/api/alembic/versions/*.py 를 반드시 직접 리뷰한다:
#   PK/FK, unique 제약조건 이름, nullable, default, 컬럼 타입, 인덱스, 테이블 생성 순서(FK 의존성)

# 적용
DATABASE_URL=postgresql+psycopg://<user>:<pw>@127.0.0.1:<port>/<db> alembic upgrade head

# 현재 적용된 리비전 확인
DATABASE_URL=... alembic current
```

**이미 테이블이 있는 기존 개발 DB에 Alembic 이력을 처음 도입할 때**(`alembic_version` 테이블이 없는 경우), 무조건 `alembic stamp head`를 하지 않는다. 먼저 실제 스키마가 현재 모델과 일치하는지 확인한다:

```bash
DATABASE_URL=... python scripts/check_schema_matches_models.py   # 모든 테이블이 [OK] 로 나와야 한다
DATABASE_URL=... alembic stamp head                              # 일치할 때만 실행 (테이블/데이터는 그대로)
```

불일치가 나오면 stamp하지 말고 원인을 먼저 파악한다(모델과 실제 DB 중 어느 쪽이 맞는지, 수동으로 맞춰야 하는지).

pgvector 확장은 초기 리비전(`alembic/versions/355a1a748ec5_initial_schema.py`)의 `upgrade()`에서 켜진다(PostgreSQL일 때만, 이미 있으면 그대로 둠). 실제 벡터 컬럼이 있는 테이블을 추가할 때는 그 때 `pgvector-python` 의존성과 새 리비전을 함께 추가한다.

SQLite 테스트(`pytest`)와 PostgreSQL/Alembic 경로는 서로 분리되어 있다 — `apps/api/conftest.py`가 테스트 시작 전에 `DATABASE_URL`을 임시 SQLite 파일로 강제 지정하므로, 테스트는 Alembic이나 실제 Postgres에 전혀 영향받지 않는다. Docker의 `api` 서비스가 의도치 않게 SQLite로 떠 있다면 `DATABASE_URL` 환경변수가 `postgresql+...`로 제대로 전달되는지 `docker compose config`로 확인한다.

## 팀 공용 PostgreSQL 에 연결하기

지금 "DB"라고 부를 수 있는 환경이 세 가지라서 혼동하기 쉽다 — 아래 표로 구분한다.

| 환경 | 주소 | 용도 | 쓰는 계정 |
|---|---|---|---|
| **개인 로컬 Docker DB** | `127.0.0.1:5433`(`docker-compose.yml`, 위 절 참고) | **각자의 개발·마이그레이션 작성·실험(기본 환경)** | `.env`의 `POSTGRES_USER`(기본 `postgres`) |
| **팀 공용 DB** | `192.168.0.44:5432`, DB 이름 `gabee` | **통합 확인용**(병합된 `main` 을 모아 보는 곳) | 일반 실행: `gabee_app` / 마이그레이션: 통합 때 DB 담당자가 Pull Agent 를 수동 실행(`gabee_migrator`, 사람이 `alembic` 을 직접 실행하지 않음) |
| 기존 MVP DB | `192.168.0.44:5432`, DB 이름 `family-secretary` | 레거시, **절대 건드리지 않는다** | (해당 없음 — 접근하지 않음) |

팀 공용 DB와 기존 MVP DB는 **같은 PostgreSQL 서버(같은 PC)에서 database 단위로만 분리**되어 있다 — 서로 다른 서버가 아니다. 공용 `gabee` DB 작업이 `family-secretary` DB의 데이터를 직접 바꾸지는 않지만, 같은 서버 프로세스를 쓰므로 서버 자체를 재시작·종료하거나 디스크를 가득 채우는 등의 작업은 두 DB 모두에 영향을 줄 수 있다 — 그런 작업은 하지 않는다.

**일반 FastAPI 실행(`gabee_app` 계정)**: 비밀번호를 PowerShell 창에 직접 입력하면 `PSReadLine`이 명령 이력을 디스크에 남기므로, 비밀번호는 커맨드가 아니라 **`apps/api/.env` 파일에만** 적는다(이미 `.gitignore`에 올라 있어 커밋되지 않는다).

```powershell
notepad apps\api\.env
# DATABASE_URL=postgresql+psycopg://gabee_app:<비밀번호>@192.168.0.44:5432/gabee 로 한 줄만 바꾼다

cd apps\api
.venv\Scripts\activate
uvicorn app.main:app --reload
```

다른 PowerShell 창에서 연결 확인(비밀번호 노출 없음):

```powershell
curl http://localhost:8000/health   # {"status":"ok"} 면 공용 DB에 연결됨
```

**개발은 각자 로컬 DB 에서, 공용 DB 는 통합 확인용으로만 쓴다.** 사람이 공용 DB 에 `alembic` 을 직접 실행하지 않는다. 공용 DB 스키마는 병합된 `main` 을 모아 **통합할 때 DB 담당자가 공용 DB PC 의 Pull Agent**(`apps/api/scripts/deploy_agent.py`)를 수동으로 실행해서만 반영한다. 에이전트의 5분 주기 자동 적용은 꺼져 있다(`GABEE_AGENT_ENABLED=false`, [docs/adr/0009-local-first-db-workflow.md](docs/adr/0009-local-first-db-workflow.md)). 수동 실행에도 `CI Check`(api·api-postgres·mobile) 성공 확인 → 위험 검사 → 새 백업 → 무결성 확인 → 임시 PostgreSQL 16 복원 검증 → 복사본에 먼저 적용(리허설) → `gabee_migrator`로 적용 → 리비전·스키마·`gabee_app` 권한 검증이 그대로 적용되고, 하나라도 실패하면 공용 DB 를 건드리지 않고 중단한 뒤 이슈(`db-deploy-failed`)로 알린다.

**개발자(각자)**
1. `git fetch` 후 최신 `main`에서 브랜치를 만들고 `alembic heads`가 1개인지 확인한다. 로컬 DB 가 오래됐으면 `docker compose run --rm api alembic upgrade head` 로 최신화한다.
2. 모델 수정 → **로컬 DB**(또는 격리 PostgreSQL 임시 컨테이너)에서 `alembic revision --autogenerate`, DDL 직접 리뷰, `alembic upgrade head`, `scripts/check_alembic_migrations.py`·`check_schema_matches_models.py` 검증. 로컬에는 가짜 데이터만 쓴다.
3. PR의 `api-postgres` Job이 단일 head·전체 upgrade·스키마 일치를 다시 검증한다. 병합 직전에 최신 `main` 을 받아 `alembic heads` 가 1개인지 다시 확인한다(나중에 병합되는 쪽이 `down_revision` 을 옮긴다).
4. 컬럼·테이블 삭제, 이름·타입 변경, `CONCURRENTLY` 같은 **파괴적·트랜잭션 밖 변경**은 에이전트가 적용하지 않는다. 의도한 변경이면 PR 리뷰에서 **DB 담당자의 사전 승인**을 받고 리비전 docstring에 `destructive-approved: PR #<번호>`를 적는다(문구만으로는 승인이 아니다). 마이그레이션에서 파일·네트워크·프로세스를 쓰는 파이썬(`import os` 등)은 차단되며, 정말 필요하면 같은 방식으로 `unsafe-python-approved: PR #<번호>` 승인을 받는다.

**통합(DB 담당자, 공용 DB PC 에서)**
1. 통합할 `main` 을 정하고 팀에 알린다. 그 커밋의 CI 가 통과했고 `alembic heads` 가 1개인지 확인한다. 위험 변경이 있으면 승인 근거(PR 리뷰)를 직접 확인한다.
2. 먼저 **dry-run**(백업·복원 검증·리허설까지, 공용 DB 는 바뀌지 않음). 일반 PowerShell(에이전트 실행 계정)에서:
   ```powershell
   cd C:\gabee-deploy
   $env:GABEE_AGENT_ENABLED = 'true'; $env:GABEE_AGENT_APPLY = 'false'
   C:\gabee-deploy\venv\Scripts\python.exe C:\gabee-deploy\agent\deploy_agent.py run-once
   ```
   결과가 `dry_run_ok` 이면 다음 단계로 간다. `held` 면 배포 도구·신뢰 파일 변경을 검토한 뒤 `deploy_agent.py bless --sha <커밋> --yes` 를 실행하고 다시 한다. `blocked` 면 사유(위험 변경 미승인 등)를 해결한다.
3. **적용**:
   ```powershell
   $env:GABEE_AGENT_APPLY = 'true'
   C:\gabee-deploy\venv\Scripts\python.exe C:\gabee-deploy\agent\deploy_agent.py run-once
   Remove-Item Env:GABEE_AGENT_ENABLED, Env:GABEE_AGENT_APPLY   # 환경변수 정리(agent.env 는 그대로 false)
   ```
4. 결과는 `deploy_agent.py status` 와 `db-deploy-failed` 이슈(실패 시)로 확인한다. 반영 전에는 공용 DB 가 `main` 보다 뒤처지고, 그 DB 에 붙은 서버는 새 스키마가 필요한 기능만 `503` 이다가 반영되면 재시작 없이 열린다(`GET /health/db`).

**Pull Agent 설치·운영(인프라 소유자, 공용 DB PC 에서)** — 현재 상태: 설치돼 있고 자동 적용은 꺼져 있다(`GABEE_AGENT_ENABLED=false`, 위 "통합" 절로 수동 실행). 설치 산출물과 운영 절차는 [deploy/shared-db-agent/README.md](deploy/shared-db-agent/README.md), 설계와 보안 모델은 [docs/adr/0008-shared-db-pull-agent.md](docs/adr/0008-shared-db-pull-agent.md) 참고. 요약:

1. 먼저 런북 0절의 읽기 전용 명령으로 공용 DB PC 의 OS·Docker 구성을 확인한다(Windows 로 단정하지 않음). Windows 로 확인되면 관리자 PowerShell 에서 `deploy\shared-db-agent\install.ps1 -DryRun` 으로 점검 후 `install.ps1` 을 실행한다(폴더·권한·가상환경·작업 스케줄러 등록). 에이전트는 **비활성**으로 설치된다.
2. `gabee_migrator` 비밀번호와 GitHub 읽기 전용 토큰은 설치 중 프롬프트로 받아 파일(pgpass, token)에만 저장한다 — GitHub·코드·로그·명령줄에 남기지 않는다.
3. (권장) `deploy/shared-db-agent/db-hardening.sql` 의 읽기 전용 점검으로 MVP 가 쓰는 롤을 확인한 뒤, `pg_hba.conf` 거부 규칙 등 MVP 에 영향이 없는 방법으로 `gabee_app`/`gabee_migrator` 가 `family-secretary` 에 접속하지 못하게 한다(런북 0-1절). 무턱대고 `REVOKE ... FROM PUBLIC` 하지 않는다.
4. **단계적 활성화**: `agent.env` 에서 ① `GABEE_AGENT_ENABLED=true` 만 켜서 dry-run(백업·복원 검증·리허설까지, 공용 DB 미변경)을 확인 → ② 문제가 없으면 `GABEE_AGENT_APPLY=true`. 즉시 끄려면 `GABEE_AGENT_ENABLED=false`.
5. 실패하면 이후 배포가 멈춘다(`state\HALT`). 원인을 고친 뒤 `deploy_agent.py clear-halt` 로 재개한다. 자동 롤백은 하지 않는다 — 필요하면 백업(`gabee_pg16_deploy_*.dump`)으로 새 DB에 복원해 사람이 판단한다.
6. 배포 도구(`deploy_agent.py`·`shared_db_deploy.py`·`migration_risk.py`)나 `alembic/env.py` 가 PR 로 바뀌면 에이전트는 자격증명으로 실행하지 않고 멈춘 뒤(`held`) 이슈로 알린다. 관리자가 변경을 리뷰하고 `deploy_agent.py bless --sha <커밋> --yes` 를 실행해야 재개된다.

백업은 날짜·시각과 리비전 범위가 들어간 파일(`gabee_pg16_deploy_<UTC시각>_<이전>-to-<이후>.dump` + `.sha256`)로 저장되고, 사람이 만든 기존 백업(`gabee_pg16.dump` 등 이름이 다른 파일)은 건드리지 않는다. 최근 14개만 보관하고 Git에는 올리지 않는다(`.gitignore`의 `*.dump`). 백업에는 공용 DB의 실제 데이터가 들어 있으므로 폴더 접근 권한을 소유자로 제한하고, 외부 클라우드 동기화 폴더에 두지 않는다. 개발 PC 로 복사하려면 `deploy/shared-db-agent/pull-backups.ps1` 을 쓴다.

**리비전 확인(시점에 따라 달라짐)**: 2026-10-22 기준으로는 개인 로컬 Docker DB가 `355a1a748ec5`, 공용 DB가 `b6931fc30c66`에 있었지만, 이 값들은 **그 순간의 상태일 뿐**이다 — `main`에 새 리비전이 계속 추가되므로, 실제로 어떤 DB가 어느 리비전에 있는지는 항상 `alembic current`(연결된 DB 기준)나 `alembic heads`(코드 기준 최신)로 직접 확인하고, 이 문서나 다른 문서에 적힌 리비전 ID를 "지금의 최신"이라고 가정하지 않는다.

**공용 DB 안전 규칙**
- 공용 DB 스키마 변경(`alembic upgrade`/`downgrade`/`stamp`)을 사람이 직접 실행하지 않는다. `main`에서 CI를 통과한 커밋만, 통합 때 DB 담당자가 공용 DB PC 의 Pull Agent 를 수동 실행해 `gabee_migrator`로 반영한다(백업·복원 검증·리허설·사후 검증 포함). 파괴적 변경은 PR 리뷰에서 DB 담당자가 사전 승인하고 `destructive-approved` 표기가 있어야 한다.
- 일반 FastAPI 실행에는 `gabee_app`을 쓴다. 이 계정은 DDL(테이블 생성·변경) 권한이 없지만, **데이터 CRUD 권한은 있다** — 즉 실수로 다른 팀원이 넣은 행을 지우거나 고칠 수 있는 위험은 여전히 남아 있으니 공용 DB의 데이터를 직접 조작하는 작업은 신중하게 한다.
- `pytest`나 마이그레이션 실험은 공용 DB가 아니라 개인 로컬 Docker DB 또는 별도 격리 DB에서 한다.
- 공용 DB를 테스트용으로 초기화·삭제하지 않는다.
- 기존 MVP `family-secretary` DB는 어떤 경우에도 변경하지 않는다.
- DB 비밀번호·`.env`·연결 문자열에 들어간 인증정보는 명령 이력·커밋·문서에 남기지 않는다.

배경과 결정 이유는 [docs/adr/0005-shared-postgres-env.md](docs/adr/0005-shared-postgres-env.md), 배포 단계는 [docs/adr/0007-shared-db-auto-migration.md](docs/adr/0007-shared-db-auto-migration.md), 로컬 우선·통합 방식은 [docs/adr/0009-local-first-db-workflow.md](docs/adr/0009-local-first-db-workflow.md) 참고.

## 앱 (apps/mobile)

```bash
cd apps/mobile
npm install
npx expo start
```

서버에 붙이려면 `apps/mobile/.env` 에 `EXPO_PUBLIC_API_URL=http://<개발 PC 의 IP>:8000` 을 적는다(폰에서는 `localhost` 가 폰 자신이라 PC 의 IP 를 써야 한다). 주소가 없으면 임시 데이터로 화면만 동작한다.

원본 프로젝트를 참고하는 방법은 [docs/legacy/original-reference.md](docs/legacy/original-reference.md).
