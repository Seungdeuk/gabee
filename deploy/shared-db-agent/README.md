# 공용 DB PC Pull Agent 설치·운영 런북

설계와 보안 모델: [docs/adr/0008-shared-db-pull-agent.md](../../docs/adr/0008-shared-db-pull-agent.md). 이 폴더의 모든 스크립트는 **공용 DB 를 직접 바꾸지 않는다**(설치는 폴더·작업 스케줄러만 만들고, 에이전트는 기본 비활성).

| 파일 | 용도 |
|---|---|
| `install.ps1` | 공용 DB PC 에서 1회 실행: 폴더·권한·클론·가상환경·작업 스케줄러 등록 (`-DryRun` 으로 사전 점검) |
| `agent.env.example` | 설정 예시(에이전트 on/off, 적용 on/off, 경로) |
| `db-hardening.sql` | DB 서버에서 관리자가 단계별 실행: 읽기 전용 점검 → MVP 영향 없는 접속 제한 방법 (변경 문장은 주석, 자동 배포는 실행하지 않음) |
| `pull-backups.ps1` | 개발 PC 에서 백업을 안전하게 복사(삭제 없음, 해시 확인) |
| `systemd/` | 공용 DB PC 가 Linux 일 때의 대안(현재 추정은 Windows 라 참고용) |

## 0. 설치 전 점검 (공용 DB PC, 모두 읽기 전용)

**공용 DB PC 의 OS 와 Docker 구성은 아직 확인되지 않았다.** 네트워크 점검(ping TTL, 열린 포트)만으로는 Windows 로 *보이지만* 단정하지 않는다. 아래로 먼저 확인하고, 결과에 따라 `install.ps1`(Windows) 또는 `systemd/`(Linux)를 고른다. 이 명령들은 아무것도 바꾸지 않는다.

```powershell
# Windows 라면 (PowerShell)
[Environment]::OSVersion.VersionString; (Get-CimInstance Win32_OperatingSystem).Caption
whoami; docker version --format "{{.Server.Os}} {{.Server.Version}}"
docker ps --format "table {{.Names}}	{{.Image}}	{{.Ports}}	{{.Status}}"   # PostgreSQL 컨테이너와 MVP 서비스 컨테이너 확인
docker volume ls; docker info --format "{{.DockerRootDir}}"
Get-Service | Where-Object { $_.Name -match "postgres|docker" }               # PostgreSQL 이 Windows 서비스인지
python --version; git --version; Get-PSDrive -PSProvider FileSystem           # 파이썬·git·디스크 여유
```

```sh
# Linux 라면
cat /etc/os-release; id; docker version --format '{{.Server.Os}} {{.Server.Version}}'
docker ps --format 'table {{.Names}}	{{.Image}}	{{.Ports}}	{{.Status}}'; docker volume ls
systemctl list-units --type=service | grep -Ei 'postgres|docker'; df -h; python3 --version; git --version
```

확인할 것: ① PostgreSQL 이 Docker 컨테이너인지, Windows/Linux 서비스인지 ② MVP 서비스가 같은 PostgreSQL 인스턴스를 쓰는지(`family-secretary` DB) ③ 5432 포트와 데이터 볼륨 위치(백업 폴더는 다른 곳) ④ 에이전트를 돌릴 계정과 그 계정의 Docker 권한.

**PostgreSQL·MVP 에 영향을 주지 않는 설치 원칙**
- 설치는 DB 컨테이너·볼륨·설정(`pg_hba.conf` 포함)을 건드리지 않는다. 새 폴더, 가상환경, 작업 스케줄러 1개만 만든다.
- 에이전트의 리허설·복원 검증은 *별도의 임시 컨테이너*(이름 `gabee-deploy-*`, 메모리 512MB·CPU 1개 제한, 끝나면 삭제)에서만 한다. 기존 컨테이너와 볼륨은 조회·변경하지 않는다.
- 공용 DB 에는 `gabee_migrator` 로 DB `gabee` 에만 접속한다(대상 DB 이름 검증, MVP DB 이름이면 거부).
- 새 서버, VM, GitHub Self-hosted Runner 는 만들지 않는다.

**Docker 권한이 DB 에 미치는 영향 (명확히)**
Docker 를 쓸 수 있는 계정은 그 PC 에서 사실상 관리자 권한이다. 컨테이너에 호스트 폴더를 마운트하거나 실행 중인 컨테이너(공용 PostgreSQL, MVP)에 `docker exec` 로 들어가 데이터 폴더와 모든 DB(`gabee`, `family-secretary`)를 읽고 바꿀 수 있다. 즉 에이전트 계정이 탈취되면 DB 비밀번호와 상관없이 MVP DB 까지 영향이 간다. 에이전트 코드는 `docker run/cp/rm` 으로 자기 임시 컨테이너만 다루도록 만들어져 있고, 신뢰 점검(bless)과 `main` 한정 체크아웃으로 변조를 막지만, 이 한계 자체는 남는다. 완화: ① 전용 계정에 토큰·pgpass 만 두고 다른 용도로 쓰지 않는다 ② 에이전트 폴더는 읽기 전용 `agent/`·`secrets/` ACL ③ `GABEE_AGENT_ENABLED=false` 킬스위치 ④ 필요하면 데이터베이스가 있는 PC 와 에이전트를 분리(이번 범위 아님).

## 0-1. DB 계정 권한 정리 (관리자, 선택이지만 권장)

`db-hardening.sql` 은 **기본이 읽기 전용 점검**이고, 변경 문장은 모두 주석으로 되어 있다. 순서:

**현재 운영 위험(2026-10-23 읽기 전용 확인)**: `family-secretary` 의 접속 권한이 기본값(PUBLIC CONNECT)이라 `gabee_migrator`·`gabee_app` 모두 MVP DB 에 접속할 수 있다. 에이전트는 대상 DB 이름을 `gabee` 로 검증하지만 DB 쪽 차단은 아직 없다. **`APPLY=true` 전에** 아래를 MVP 담당자와 함께 적용하기를 권장한다.

1. **MVP 접속 계정·경로 점검**(읽기 전용): STEP 1 쿼리로 MVP 가 쓰는 롤과 `pg_stat_activity` 의 `client_addr`(Docker 네트워크 172.x 인지, 호스트·다른 PC 인지)를 며칠에 걸쳐 여러 번 확인한다. 백업·모니터링 같은 다른 도구의 접속도 함께 본다.
2. **`pg_hba.conf` 거부 규칙(권장, DB 권한을 바꾸지 않음)**: `host family-secretary gabee_app,gabee_migrator all reject` 를 추가한다. pg_hba 는 **위에서부터 처음 맞는 줄**만 쓰므로 이 줄은 `host all all ...` 같은 일반 허용 규칙보다 *위에* 둔다. `local`(컨테이너 안 소켓) 접속도 막으려면 `local` 줄도 같은 위치에 추가한다.
3. **백업과 원복**: 편집 전 `docker exec postgres sh -c 'cp "$PGDATA/pg_hba.conf" "$PGDATA/pg_hba.conf.bak-<날짜>"'` 로 복사본을 둔다. 적용은 `SELECT pg_reload_conf();`(재시작 불필요), 결과는 `pg_hba_file_rules` 의 `error` 컬럼이 비었는지로 확인한다. 원복은 `.bak` 을 되돌려 놓고 다시 `pg_reload_conf()`. 컨테이너 재생성·볼륨 변경은 하지 않는다.
4. **기존 연결과 신규 연결**: pg_hba 는 *새 연결의 인증 시점*에만 검사한다. 이미 열린 세션은 reload 후에도 끊기지 않으며, 재접속할 때부터 거부된다. 그래서 MVP 영향은 MVP 가 재접속(재시작·풀 재생성)할 때 드러난다. 적용 직후 MVP 를 한 번 재시작하거나 새 연결을 열어 정상인지 확인하고, 문제가 있으면 바로 원복한다.
5. SQL 로 PUBLIC 접속 권한을 회수하는 방법(STEP 2-B)은 MVP 롤 전부에 먼저 명시 GRANT 한 뒤에만, 트랜잭션 안에서 검증하며 한다. `REVOKE ... FROM gabee_app` 만으로는 막히지 않고, 무턱대고 `FROM PUBLIC` 을 하면 MVP 가 끊길 수 있다.
6. 이 차단은 **DB 계정 경로만** 막는다. Docker 엔진 권한(위 '0. 설치 전 점검')은 별개의 위험이라, 에이전트 계정이 탈취되면 `docker exec` 로 MVP DB 에 닿을 수 있다는 한계는 남는다.

## 0-2. 사전 준비 (토큰, 폴더)

1. **에이전트 실행 계정**: 가능하면 전용 저권한 계정(Docker 사용 가능, 자동 로그온 권장).
2. **GitHub 토큰**: 소유자 계정에서 fine-grained 토큰을 만든다 — 저장소 `kangminhun/gabee` 한정, 권한 Contents:Read, Actions:Read, Metadata:Read, Issues:Write(알림용). 만료일을 정한다.
3. 백업 폴더는 **DB 데이터 폴더·Docker 볼륨과 다른 드라이브/폴더**에 둔다.

## 1. 설치 (최초 1회, 관리자 PowerShell)

```powershell
cd <저장소 clone>\deploy\shared-db-agent
.\install.ps1 -DeployHome C:\gabee-deploy -DryRun   # 점검만(아무것도 만들지 않음)
.\install.ps1 -DeployHome C:\gabee-deploy           # 설치 (이 PC 는 C: 드라이브만 있다)
```

진행 순서와 사람이 할 일:

1. 토큰·`gabee_migrator` 비밀번호를 프롬프트로 입력한다(화면에 표시되지 않고 `secrets\` 파일에만 저장).
2. 스크립트가 main 최신 SHA 를 **고정**하고, 실행 계정의 비관리자 권한으로 그 SHA 를 체크아웃해 검토할 파일 목록·이전 검토 이후 변경·`pyproject.toml` 을 보여 준다. 저장소 코드는 이때까지 실행되지 않는다.
3. 배포 도구·`alembic/env.py`·`pyproject.toml`·`app/shared` 를 **직접 검토했다면 그 SHA 의 앞 12자리**를 입력한다. 검토 중 main 이 바뀌어도 고정한 SHA 만 설치된다.
4. 그 SHA 의 도구를 `agent\` 에 고정 → (비관리자) `pip install -e` → `bless --sha` → `check --sha` 가 모두 성공해야 작업 스케줄러가 등록된다. 실패하면 등록하지 않으며, 원인을 해결하고 다시 실행하면 이어서 진행한다.

비관리자 단계는 일회용 작업(`GabeeSharedDbDeployAgent-Setup`, 끝나면 삭제)으로 실행되므로 **실행 계정이 로그인해 있어야** 한다. 로그는 `logs\install-checkout.log`, `logs\install-deps.log`. 설치 직후 에이전트는 비활성(`ENABLED=false`, `APPLY=false`)이다.

## 2. 활성화 (2단계)

`D:\gabee-deploy\agent.env` 편집:

1. **dry-run**: `GABEE_AGENT_ENABLED=true` (APPLY 는 false 유지). 5분 안에 에이전트가 최신 main 을 확인하고 백업 → 복원 검증 → 복사본 리허설까지 하되 공용 DB 는 바꾸지 않는다. 확인:
   ```powershell
   D:\gabee-deploy\venv\Scripts\python.exe D:\gabee-deploy\agent\deploy_agent.py status
   Get-Content D:\gabee-deploy\logs\agent-*.log -Tail 40
   ```
   `last_outcome` 이 `dry_run_ok` 이고 백업 파일이 생겼으면 정상.
2. **적용**: `GABEE_AGENT_APPLY=true`. 이후 CI 를 통과한 main 의 새 마이그레이션이 자동 적용된다. **켜기 전 조건**: ① 백업이 다른 장치에 정기적으로 복사·해시 확인되고 있음(4절) ② `gabee_*` 계정의 MVP DB 접속 차단(0-1절) ③ dry-run 결과 확인. 외부 백업 보관이 확인되기 전에는 켜지 않는다.
3. **즉시 중지**: `GABEE_AGENT_ENABLED=false` (또는 작업 스케줄러에서 `GabeeSharedDbDeployAgent` 비활성화).

## 3. 운영

| 상황 | 동작 |
|---|---|
| 상태 보기 | `deploy_agent.py status` (활성 여부, 마지막 결과, HALT, 최근 백업) |
| 실패 후 멈춤(HALT) | 이슈 `db-deploy-failed` 확인 → 원인 해결(수정 커밋 main 병합) → `deploy_agent.py clear-halt` |
| `held`(배포 도구/신뢰 파일 변경) | 이슈에 안내됨(이슈 생성이 실패해도 멈춘 채이며, 로컬 로그에 남고 다음 주기에 다시 알림). 변경된 코드를 리뷰한 뒤 관리자 PowerShell 에서 `deploy_agent.py bless --sha <커밋> --yes` |
| `held`(위험한 파이썬·모듈 문제) | 리비전·모델의 허용되지 않은 import/호출, 라이브러리를 가리는 모듈, 검사 오류. bless 로는 풀리지 않는다 — main 에서 코드를 고친다 |
| 재부팅 | 작업이 로그온 시 자동 재개, 놓친 주기는 `StartWhenAvailable`. 같은 커밋을 다시 적용하지 않음(상태 파일) |
| 토큰 교체 | `secrets\github-token` 내용 교체(ACL 유지) |
| 의존성 변경 | `pyproject.toml`(또는 `setup.py`/`setup.cfg` 생성)이 바뀐 커밋은 `held`. 검토 후 `bless` 하면, 그 커밋의 CI 성공을 확인한 뒤 에이전트가 `pip install -e` (실패하면 `blocked`, 배포 안 함) |

**무엇을 사람이 검토(bless)하고 무엇을 리뷰·CI 에 맡기나**

| 범위 | 신뢰 방식 |
|---|---|
| `agent\` 의 배포 도구, `alembic/env.py`·`alembic.ini`·`check_schema_matches_models.py`, `pyproject.toml`(·`setup.py`/`setup.cfg` 없음), env.py 가 import 로 닿는 `app` 공통 코드(현재 `app/__init__.py`, `app/shared/{__init__,db,config,schema,location_consent}.py`) | 해시 고정. 바뀌면 `held` → 사람이 bless. 범위는 매 실행 AST 로 다시 계산한다 |
| 기능 모델(`app/features/**/models.py`·`__init__.py`), 리비전(`alembic/versions/*.py`) | **main 의 PR 리뷰·CI 통과를 전제로 신뢰**(평소 기능·마이그레이션 개발에 bless 불필요). 자격증명 프로세스가 불러오기 전에 위험한 import·호출을 정적 검사하고, 모델이 다른 app 코드를 끌어들이면 그 코드는 해시 고정 대상이 된다 |

정적 검사는 임의의 파이썬 실행을 **완벽히 막지 못한다**(동적 기법, 서드파티 패키지 내부 코드). 리비전·모델의 파이썬 로직은 PR 리뷰가 최종 방어선이다.

**main 신뢰 정책**: 에이전트는 GitHub 이 알려 준 main 최신 SHA 하나만 대상으로 하고, ① 그 SHA 가 main 이력에 있는지 ② 그 SHA 의 `CI Check`(push, main)에서 `api`·`api-postgres`·`mobile` 이 모두 성공했는지 확인한다. 확인 실패·GitHub API 오류면 의존성 설치도 하지 않는다. PR·다른 브랜치는 가져오지 않는다. 팀 규칙으로 **main 직접 push 를 금지하고 PR 리뷰와 CI 통과를 필수**로 한다. 단 현재 개인 비공개 저장소에서는 브랜치 보호가 **기술적으로 강제되지 않을 수 있다**. 그러면 이 규칙은 사람의 약속일 뿐이고, 직접 push 된 커밋의 CI 는 그 커밋이 정의한 워크플로우로 돌기 때문에 리뷰를 대신하지 못한다.

## 4. 백업과 복원

- 위치: `GABEE_BACKUP_DIR` (`gabee_pg16_deploy_<UTC>_<이전>-to-<이후>.dump` + `.sha256`), 최근 14개 보관. `.gitignore` 가 `*.dump`·`*.dump.sha256` 을 제외한다 — 백업 파일은 절대 Git 에 커밋하지 않는다.
- **단일 디스크 위험**: 공용 DB PC 는 C: 하나뿐이라 Docker 데이터(WSL 디스크)와 백업(`C:\gabee-deploy\backups`)이 같은 물리 디스크에 있다. 디스크가 고장 나면 DB 와 백업을 함께 잃는다. 그래서 **다른 장치로의 정기 복사가 확인되기 전에는 `APPLY=true` 를 켜지 않는다.**
- **접근 권한**: 백업 폴더는 설치 시 상속을 끊고 관리자·SYSTEM·실행 계정만 접근하게 하며, 오케스트레이터가 각 백업 파일에도 같은 제한을 건다. 공유는 *읽기 전용*으로, 백업을 받는 개발자 1명 계정에만 연다.
- **개발 PC 로 정기 복사(절차, 이번 작업에서는 설정하지 않음)**:
  1. 공용 DB PC(관리자): `New-SmbShare -Name gabee-deploy-backups -Path C:\gabee-deploy\backups -ReadAccess "<도메인>\<개발자 계정>"`. 폴더 ACL 에도 그 계정의 읽기를 추가한다.
  2. 개발 PC: `.\pull-backups.ps1 -ListOnly` 로 목록을 확인하고 `.\pull-backups.ps1` 로 복사한다(robocopy `/XO`, 삭제 없음). 복사 뒤 각 `.dump` 의 SHA-256 을 `.sha256` 과 비교해 `[OK]`/`불일치!` 를 표시한다. 불일치가 있으면 그 파일은 쓰지 말고 다시 복사한다.
  3. 정기 실행: 개발 PC 작업 스케줄러에 하루 1회(배포가 잦으면 더 자주) 등록하거나, 배포 이슈·로그를 본 뒤 수동으로 실행한다. 받은 폴더는 개발 PC 계정만 접근하게 하고 클라우드 동기화 폴더에 두지 않는다(실제 데이터 포함).
  4. 첫 복사·해시 확인 결과를 팀에 공유한 뒤에 `APPLY=true` 를 켠다.
- **복원(사람이 판단, 자동 롤백 없음)**: 항상 *새* DB 로 복원해 먼저 확인한다.
  ```powershell
  docker run --rm -d --name restore-check -e POSTGRES_PASSWORD=<임시> -p 127.0.0.1:55432:5432 pgvector/pgvector:pg16
  docker cp <백업>.dump restore-check:/tmp/b.dump
  docker exec restore-check sh -c "createdb -U postgres check && pg_restore -U postgres -d check --no-owner /tmp/b.dump"
  ```
  공용 DB 자체를 되돌려야 하면 팀과 합의 후 서버를 멈추고 수행한다.

## 5. 제거

작업 스케줄러에서 `GabeeSharedDbDeployAgent` 삭제 → 배포 폴더 삭제(백업 폴더는 보존). 공용 DB 는 영향 없음.
