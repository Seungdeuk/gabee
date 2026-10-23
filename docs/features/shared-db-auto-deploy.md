# 공용 DB 자동 배포(Pull Agent) 구현 현황

설계: [ADR 0007](../adr/0007-shared-db-auto-migration.md), [ADR 0008](../adr/0008-shared-db-pull-agent.md). 설치·운영: [deploy/shared-db-agent/README.md](../../deploy/shared-db-agent/README.md).

## 상태: 코드 완료·병합(PR #25), 공용 DB PC 설치는 **보류**

공용 DB PC(192.168.0.44)에 직접 접근할 수 없어 설치·권한 변경·작업 스케줄러 등록·활성화를 하지 않았다. 코드와 테스트는 그대로 보존한다. 자동화는 더 확장하지 않는다.

| 항목 | 상태 |
|---|---|
| `deploy_agent.py`, `shared_db_deploy.py`, `migration_risk.py` | 완료 (pytest 193 passed, 격리 PG16 e2e: 게이트 5 / 배포 17 / 에이전트 7 통과) |
| `install.ps1`, `pull-backups.ps1`, `db-hardening.sql`, systemd 유닛 | 작성됨. PowerShell 문법만 검사, **실제 설치 미검증** |
| 공용 DB PC 의 OS·Docker 구성 | **미확인** (Windows 로 단정하지 않음) |
| 공용 DB PC 설치, DB 권한 정리, 스케줄러 등록 | 보류 |
| 자동 적용 활성화 | 금지 (설치 후에도 기본 비활성) |

## 그동안의 마이그레이션 적용 방법
공용 DB 는 자동 배포가 켜지기 전까지 코드보다 뒤처질 수 있다(2026-10-22 조회 기준 `6304cb91e46a`, 코드 head `c3a9f21d7e54`). 뒤처진 기능은 스키마 게이트가 503 으로 막고 서버는 계속 뜬다(`GET /health/db`). 새 기능은 개인 로컬 Docker DB 또는 격리 PostgreSQL 에서 개발·테스트하고, 공용 DB 반영은 접근이 가능해진 뒤 아래 순서로 한다.

## 공용 DB PC 접근 후 재개 체크리스트
1. [ ] 읽기 전용으로 환경 확인: OS, `docker version`, `docker ps`(PostgreSQL·MVP 컨테이너), 데이터 볼륨 위치, 디스크 여유 (런북 0절 명령). Windows/Linux 판정에 따라 `install.ps1` 또는 `systemd/` 선택.
2. [ ] MVP 영향 확인: `db-hardening.sql` STEP 1(읽기 전용)로 `family-secretary` 접속 롤·ACL 확인. 변경은 `pg_hba.conf` 거부 규칙 우선, SQL `REVOKE FROM PUBLIC` 은 MVP 롤에 명시 GRANT 후에만.
3. [ ] GitHub fine-grained 토큰 생성(저장소 한정: Contents/Actions/Metadata 읽기, Issues 쓰기, 만료일 지정).
4. [ ] 백업 폴더를 DB 데이터 폴더와 분리된 위치로 결정.
5. [ ] `install.ps1 -DryRun` → 설치(비활성). 배포 도구 검토 후 bless.
6. [ ] `agent.env` 에서 `GABEE_AGENT_ENABLED=true` 로 dry-run 확인(백업·복원·리허설, 공용 DB 미변경) → 결과 확인.
7. [ ] `GABEE_AGENT_APPLY=true` 로 적용 활성화(첫 배포에서 공용 DB 가 밀린 리비전을 따라잡음, 사전에 팀 공지).
8. [ ] 재부팅 후 작업 재개와 `deploy_agent.py status` 확인, 백업을 개발 PC 로 복사(`pull-backups.ps1`) 점검.
9. [ ] (선택) 에이전트 전용 계정 분리, `gabee_*` 계정의 MVP DB 접속 차단 확인.

## 알려진 사항
- knowledge 테이블이 `ai_assistant` 스키마 게이트에 포함돼 있어, 공용 DB 가 `c3a9f21d7e54` 에 도달하기 전에는 ai_assistant API 가 503 이다.
- 이 보류 기간에 추가되는 마이그레이션도 공용 DB 에는 적용되지 않는다. 신규 기능(회원가입 등)은 해당 테이블이 공용 DB 에 생길 때까지 그 DB 에 연결된 서버에서 503 이다.
