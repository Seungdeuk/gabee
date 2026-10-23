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

1. STEP 1 의 점검 쿼리를 실행해 MVP 가 어떤 롤로 접속하는지, `family-secretary` 의 접속 권한(ACL)이 PUBLIC 기본값인지 확인한다(며칠에 걸쳐 여러 번).
2. **가장 안전한 방법은 `pg_hba.conf` 에 `gabee_app`/`gabee_migrator` 의 `family-secretary` 접속 거부 규칙을 추가**하는 것이다(DB 권한을 바꾸지 않고, 규칙 삭제 후 reload 로 즉시 원복).
3. SQL 로 PUBLIC 접속 권한을 회수하는 방법(STEP 2-B)은 MVP 롤 전부에 먼저 명시 GRANT 한 뒤에만, 트랜잭션 안에서 검증하며 한다. `REVOKE ... FROM gabee_app` 만으로는 막히지 않고, 무턱대고 `FROM PUBLIC` 을 하면 MVP 가 끊길 수 있다.
4. 어느 쪽이든 MVP 담당자와 같이 하고, 되돌리는 명령(`GRANT CONNECT ... TO PUBLIC`)을 먼저 준비해 둔다.

## 0-2. 사전 준비 (토큰, 폴더)

1. **에이전트 실행 계정**: 가능하면 전용 저권한 계정(Docker 사용 가능, 자동 로그온 권장).
2. **GitHub 토큰**: 소유자 계정에서 fine-grained 토큰을 만든다 — 저장소 `kangminhun/gabee` 한정, 권한 Contents:Read, Actions:Read, Metadata:Read, Issues:Write(알림용). 만료일을 정한다.
3. 백업 폴더는 **DB 데이터 폴더·Docker 볼륨과 다른 드라이브/폴더**에 둔다.

## 1. 설치 (최초 1회, 관리자 PowerShell)

```powershell
cd <저장소 clone>\deploy\shared-db-agent
.\install.ps1 -DryRun                      # 점검만(아무것도 만들지 않음)
.\install.ps1 -DeployHome D:\gabee-deploy  # 설치
```

설치 중 토큰·`gabee_migrator` 비밀번호를 프롬프트로 입력한다(화면에 표시되지 않고 파일에만 저장). 마지막에 `main` 커밋의 배포 도구를 **직접 검토했다면** `yes` 를 입력해 고정(bless)한다. 설치 직후 에이전트는 비활성이다.

## 2. 활성화 (2단계)

`D:\gabee-deploy\agent.env` 편집:

1. **dry-run**: `GABEE_AGENT_ENABLED=true` (APPLY 는 false 유지). 5분 안에 에이전트가 최신 main 을 확인하고 백업 → 복원 검증 → 복사본 리허설까지 하되 공용 DB 는 바꾸지 않는다. 확인:
   ```powershell
   D:\gabee-deploy\venv\Scripts\python.exe D:\gabee-deploy\agent\deploy_agent.py status
   Get-Content D:\gabee-deploy\logs\agent-*.log -Tail 40
   ```
   `last_outcome` 이 `dry_run_ok` 이고 백업 파일이 생겼으면 정상.
2. **적용**: `GABEE_AGENT_APPLY=true`. 이후 CI 를 통과한 main 의 새 마이그레이션이 자동 적용된다.
3. **즉시 중지**: `GABEE_AGENT_ENABLED=false` (또는 작업 스케줄러에서 `GabeeSharedDbDeployAgent` 비활성화).

## 3. 운영

| 상황 | 동작 |
|---|---|
| 상태 보기 | `deploy_agent.py status` (활성 여부, 마지막 결과, HALT, 최근 백업) |
| 실패 후 멈춤(HALT) | 이슈 `db-deploy-failed` 확인 → 원인 해결(수정 커밋 main 병합) → `deploy_agent.py clear-halt` |
| `held`(배포 도구/신뢰 파일 변경) | 이슈에 안내됨. 변경된 코드를 리뷰한 뒤 `deploy_agent.py bless --sha <커밋> --yes` |
| 재부팅 | 작업이 로그온 시 자동 재개, 놓친 주기는 `StartWhenAvailable`. 같은 커밋을 다시 적용하지 않음(상태 파일) |
| 토큰 교체 | `secrets\github-token` 내용 교체(ACL 유지) |
| 의존성 변경 | `pyproject.toml` 이 바뀌면 에이전트가 자동 `pip install -e` |

## 4. 백업과 복원

- 위치: `GABEE_BACKUP_DIR` (`gabee_pg16_deploy_<UTC>_<이전>-to-<이후>.dump` + `.sha256`), 최근 14개 보관, Git 제외.
- **개발 PC 로 복사**: 공용 DB PC 에서 백업 폴더를 `gabee-deploy-backups` 라는 *읽기 전용* 공유로 열고(개발자 1명만 접근), 개발 PC 에서:
  ```powershell
  .\pull-backups.ps1 -ListOnly   # 목록 확인
  .\pull-backups.ps1             # 복사 + 해시 확인 (삭제 없음)
  ```
  백업에는 실제 데이터가 있으므로 클라우드 동기화 폴더에 두지 않는다.
- **복원(사람이 판단, 자동 롤백 없음)**: 항상 *새* DB 로 복원해 먼저 확인한다.
  ```powershell
  docker run --rm -d --name restore-check -e POSTGRES_PASSWORD=<임시> -p 127.0.0.1:55432:5432 pgvector/pgvector:pg16
  docker cp <백업>.dump restore-check:/tmp/b.dump
  docker exec restore-check sh -c "createdb -U postgres check && pg_restore -U postgres -d check --no-owner /tmp/b.dump"
  ```
  공용 DB 자체를 되돌려야 하면 팀과 합의 후 서버를 멈추고 수행한다.

## 5. 제거

작업 스케줄러에서 `GabeeSharedDbDeployAgent` 삭제 → 배포 폴더 삭제(백업 폴더는 보존). 공용 DB 는 영향 없음.
