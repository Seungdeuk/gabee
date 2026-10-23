# 0008. 공용 DB 자동 배포를 Self-hosted Runner 대신 공용 DB PC 의 Pull Agent 로 한다

- 날짜: 2026-10-22
- 결정: 공용 DB PC(`192.168.0.44`)가 5분마다 스스로 GitHub 의 최신 `main` 을 확인(pull)해, 필수 CI 가 성공한 커밋의 Alembic 마이그레이션을 자동 적용한다. GitHub Actions Self-hosted Runner 와 `deploy-shared-db.yml` 워크플로우는 제거한다. 배포 단계 자체(CI 검증·위험 검사·백업·복원 리허설·적용·사후 검증·HALT·알림)는 [0007](0007-shared-db-auto-migration.md) 그대로이며 `shared_db_deploy.py` 를 재사용한다.
- 이유: 개인 저장소에는 러너 그룹이 없어 쓰기 권한이 있는 팀원이 **자기 브랜치**에서 러너를 요청하는 워크플로우를 만들면 그 코드가 러너 PC 의 DB 자격증명에 닿을 수 있었다(0007 의 선행 조건). Pull 방식은 GitHub 쪽에서 내부망으로 들어오는 경로 자체가 없고(아웃바운드 HTTPS 만), 에이전트가 `main` 의 정확한 커밋만 체크아웃하므로 PR·브랜치 코드는 실행되지 않는다. 별도 서버·VM 이 필요 없다.

## 구성

```
[작업 스케줄러: 부팅/로그온 + 5분 반복, 중복 실행 안 함]
  deploy_agent.py run-once   (agent/ 의 고정 복사본, 가상환경 파이썬)
   1 킬스위치(GABEE_AGENT_ENABLED) → 단일 인스턴스 파일 잠금 → HALT 확인
   2 GitHub API 로 main tip 조회(읽기 전용 토큰) → 이미 처리한 커밋이면 종료(상태 파일 state/agent-state.json)
   3 에이전트 소유 클론에서 그 정확한 SHA 만 fetch+checkout (main 이력 포함 여부 확인, 토큰은 환경변수로만)
   4 신뢰 점검: 배포 도구·alembic/env.py 등이 관리자가 검토(bless)한 것과 같은가 → 다르면 held(이슈) 로 멈춤
   5 pyproject 변경 시에만 의존성 설치
   6 agent/shared_db_deploy.py run (CI 검증 → 위험 검사 → 백업 → 복원 → 리허설 → 적용 → 사후 검증)
   7 결과 기록(state, logs/), 실패 시 HALT + 이슈
```

## 보안 모델

| 위협 | 대응 |
|---|---|
| 협업자가 PR/브랜치로 DB 자격증명을 읽으려 함 | 러너·DB 배포 워크플로우가 없다(`tests/test_workflow_safety.py` 가 self-hosted 사용을 금지). 에이전트는 `main` 의 CI 통과 커밋만 체크아웃한다 |
| 병합된 마이그레이션(파이썬)이 자격증명을 쓰거나 파일·네트워크에 접근 | `migration_risk.py` 가 허용 import 외·`open/eval/exec`·내부 탐색을 차단한다(`unsafe-python-approved: PR #N` 으로 리뷰 승인 시에만 경고로 완화). **CI 통과 ≠ 안전**이라 위험 검사를 CI 와 별도로 배포 직전에 다시 한다 |
| 배포 도구(에이전트/오케스트레이터)를 바꾸는 PR 이 병합돼 자격증명으로 실행됨 | 에이전트는 `agent/` 의 *고정 복사본*으로 실행하고, 체크아웃의 같은 파일·`alembic/env.py`·`alembic.ini`·`check_schema_matches_models.py`·`pyproject.toml`·env.py 가 불러오는 공통 코드가 `bless` 된 해시와 다르면(아래 '보완') `held` 로 멈추고 이슈를 만든다. 관리자가 리뷰 후 `bless --yes` |
| 토큰·비밀번호 유출 | 파일(pgpass, token)로만 받고 ACL 로 실행 계정만 읽기. git 에는 환경변수 `http.extraheader` 로 전달(명령줄·프로세스 목록 비노출). 자식 프로세스에는 허용 목록 환경변수만 전달. GitHub 토큰은 fine-grained, 이 저장소 한정(Contents·Actions·Metadata 읽기 + Issues 쓰기) |
| MVP DB 접근 | 오케스트레이터가 대상 DB 이름을 `gabee` 로 검증한다. 추가로 관리자가 MVP 영향을 확인한 뒤 `pg_hba.conf` 거부 규칙 등으로 `gabee_*` 계정의 `family-secretary` 접속을 막는다(`db-hardening.sql`) |
| 반복 실행·중복 적용 | 파일 잠금(작업 스케줄러 `IgnoreNew` 와 이중), 커밋별 상태 기록, Alembic 현재 리비전 == head 이면 `noop` |
| 장애 확산 | 자동 롤백 없음. 실패하면 `HALT`(사람이 `clear-halt`), 한 트랜잭션 DDL 이라 부분 적용 없음, 백업 보존(최근 14개). 컨테이너는 메모리 512MB·CPU 1개로 제한, 프로세스 우선순위 낮음 |

## 남는 한계(받아들인 것)

- 에이전트 계정은 Docker 를 쓰므로 사실상 그 PC 의 Docker 엔진 권한을 가진다. 전용 저권한 계정으로 실행하고 PC 의 다른 용도와 분리하는 것이 이상적이다.
- Docker Desktop 은 로그온된 세션에서만 동작한다. PC 가 재부팅 후 로그온되기 전에는 배포가 시작되지 않고(작업은 로그온 시 재개), 그동안 앱은 스키마 게이트(503)로 안전하게 동작한다.
- 위험 검사는 정적 분석이라 우회 가능성이 0 은 아니다. 그래서 마이그레이션 PR 리뷰(특히 파이썬 로직)와 배포 도구 `bless` 가 최종 방어선이다.
- 지연: 병합 후 CI 완료 + 최대 5분.

## 보완 (2026-10-23, 설치 전 점검 결과)

공용 DB PC 설치 전 점검에서 찾은 4가지를 구조를 바꾸지 않고 보완했다.

1. **설치 순서**: `install.ps1` 은 main SHA 를 먼저 고정하고, 체크아웃·검토 정보 표시 → 사람이 그 SHA 앞 12자리를 입력 → 그 SHA 의 도구 고정 → 의존성 설치 → `bless`·`check` 순으로 진행한다. 체크아웃·`pip install`·`bless` 는 실행 계정의 비관리자 권한(일회용 작업, RunLevel Limited)으로 하고, 하나라도 실패하면 작업 스케줄러를 등록하지 않는다.
2. **신뢰 범위**: `held` 판단에 `pyproject.toml`(·없어야 하는 `setup.py`/`setup.cfg`)과 `alembic/env.py`·스키마 검사가 import 로 닿는 `app` 모듈(현재 `app/__init__.py`, `app/shared/{__init__,db,config,schema,location_consent}.py`)의 해시를 더했다. 이 범위는 AST 로 매번 다시 계산한다. 기능 모델(`app/features/**/models.py`·`__init__.py`)과 리비전(`alembic/versions/*.py`)은 **main 의 PR 리뷰·CI 를 전제로 신뢰**하고 해시로 고정하지 않는다(기능 개발마다 bless 하지 않도록). 대신 자격증명 프로세스가 불러오기 *전에* 에이전트가 `migration_risk.unsafe_python` 으로 위험한 import·호출을 검사하고, 모델이 다른 app 코드를 끌어들이면 그 코드는 고정 대상이 되어 `held` 가 된다. 검사 중 오류는 `held`(fail-closed). 오케스트레이터의 파이썬 자식 프로세스는 `-P` + `PYTHONPATH=apps/api` 로 실행하고, `apps/api` 최상위에 라이브러리를 가릴 수 있는 모듈이 생기면 `held` 다.
3. **CI 선확인**: 에이전트는 의존성 설치(=체크아웃 코드 실행) 전에 그 SHA 의 필수 CI(`api`, `api-postgres`, `mobile`) 성공을 확인하고, GitHub API 오류·실패면 진행하지 않는다(오케스트레이터가 적용 직전에 다시 확인). `pyproject.toml` 이 바뀐 커밋은 `held` → 검토 후 `bless` 해야 설치된다.
4. **알림**: `held`·CI 차단은 GitHub 이슈로 알린다. 이슈 생성이 실패해도 배포는 멈춘 채이고 로컬 로그에 남으며, `held` 알림은 성공할 때까지 다음 주기에 다시 시도한다.

남는 한계: 정적 검사는 임의의 파이썬 실행을 완벽히 막지 못한다(우회 가능한 동적 기법, 서드파티 패키지 내부 코드). main 브랜치 보호는 현재 개인 비공개 저장소에서 **기술적으로 강제되지 않을 수 있고**, "main 직접 push 금지, PR 리뷰·CI 필수"는 팀 운영 규칙이다. 누군가 main 에 직접 push 해도 에이전트는 CI 성공을 요구하지만, CI 는 그 커밋 자체가 정의하므로 리뷰를 대신하지 못한다. 백업은 DB 와 같은 물리 디스크(C:)에 있으므로 외부 보관 전에는 `APPLY=true` 를 권장하지 않는다(README 4절). `gabee_*` 계정의 `family-secretary` 접속 차단은 아직 적용되지 않았다(README 0-1절).

## 활성화 전 상태

이 변경은 코드·설치 스크립트·문서만 추가한다. 에이전트는 설치돼도 기본 **비활성**(`GABEE_AGENT_ENABLED=false`)이고, 활성화는 dry-run → 적용의 2단계로 인프라 소유자가 직접 한다(`deploy/shared-db-agent/README.md`).
