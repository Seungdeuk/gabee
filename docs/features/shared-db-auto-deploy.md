# 공용 DB 배포(Pull Agent) 구현 현황

설계: [ADR 0007](../adr/0007-shared-db-auto-migration.md), [ADR 0008](../adr/0008-shared-db-pull-agent.md), 운영 방식 변경: [ADR 0009](../adr/0009-local-first-db-workflow.md). 설치·운영: [deploy/shared-db-agent/README.md](../../deploy/shared-db-agent/README.md).

## 상태: 설치·검증 완료, **자동 주기 적용은 꺼 둠**(통합 때 담당자가 수동 실행)

공용 DB PC(192.168.0.44)에 2026-10-23 설치했고 활성화해 두 번 자동 적용에 성공했다(`6304cb91e46a` → `719215db61ba` → `e6375079ef99`; 백업·복원 검증·리허설·사후 검증 통과). 이후 5인 팀 규모에 비해 자동화가 무겁다고 판단해(`bless` 반복, 공용 PC 접속 부담 등) **개발은 각자 로컬 DB, 공용 DB 는 통합 확인용**으로 바꾸고 에이전트를 껐다(`agent.env` 의 `GABEE_AGENT_ENABLED=false`).

| 항목 | 상태 |
|---|---|
| `deploy_agent.py`, `shared_db_deploy.py`, `migration_risk.py` | 완료·운영 검증됨. 코드는 그대로 유지 |
| 공용 DB PC 설치(작업 스케줄러 5분 주기) | 설치됨. `ENABLED=false` 라 `disabled` 로 끝남 |
| 자동 적용 | **중지**. 통합 때 담당자가 수동 `run-once` |
| 백업 | 적용 직전 백업은 공용 PC(같은 디스크), 일일 덤프는 개인 PC 에서 따로 받음(각자 설정) |
| 위험 변경 승인 검증 | 문구(`destructive-approved: PR #번호`) 형식만 확인. 실제 승인은 PR 리뷰·통합 때 담당자 확인으로 대신함 |

## 통합 때 반영하는 방법
[README.md](../../README.md) "팀 공용 PostgreSQL 에 연결하기"의 **통합(DB 담당자)** 절을 따른다(dry-run → 적용, 환경변수로 일시 활성화).

## 다시 자동 적용으로 돌아가려면
`agent.env` 에서 `GABEE_AGENT_ENABLED=true`. 배포 도구·신뢰 파일이 바뀐 커밋은 `held` 가 되므로 검토 후 `bless` 한다.

## 알려진 사항
- 공용 DB 는 통합 전까지 `main` 보다 뒤처진다. 그 DB 에 붙은 서버는 새 스키마가 필요한 기능만 스키마 게이트가 `503` 으로 막고 나머지는 동작한다(`GET /health/db`).
- 공용 DB PC 는 학원 공용 PC 이고 로그인한 계정(`403`)이 공용이다. 같은 계정 사용자가 백업·DB 비밀번호 파일에 접근할 수 있다.
- 공용 DB 를 학원 PC 밖으로 옮기는 것은 별도로 논의한다.
