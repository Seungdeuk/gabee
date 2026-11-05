# 결정 기록(ADR) 목록

새 ADR 은 **가장 큰 번호 + 1** 로 만든다. 만들기 전에 `git fetch` 로 최신 `main`·`release` 브랜치의 이 목록을 확인해 번호가 겹치지 않게 하고, 만든 뒤 아래 표에 한 줄 추가한다. 이미 쓴 번호는 바꾸지 않는다(링크가 깨진다).

| 번호 | 제목 | 날짜 | 상태 |
|---|---|---|---|
| [0001](0001-monorepo.md) | 모노레포 구조 | 2026-10-21 | 유효 |
| [0002](0002-skeleton-from-original.md) | 원본 프로젝트는 뼈대만 가져온다 | 2026-10-21 | 유효 |
| [0003](0003-postgres-pgvector-dev-env.md) | 개발용 PostgreSQL 에 pgvector 를 켠다 | 2026-10-21 | 유효 |
| [0004](0004-alembic-migrations.md) | Alembic 으로 스키마 마이그레이션을 일원화한다 | 2026-10-22 | 유효 |
| [0005](0005-shared-postgres-env.md) | 팀 공용 PostgreSQL 개발 DB 구축 | 2026-10-22 | 유효(운영 방식은 0007·0009 가 바꿈) |
| [0006](0006-schema-gate-degraded-start.md) | DB 가 코드와 맞지 않아도 서버는 시작하고 해당 기능만 503 | 2026-10-22 | 유효 |
| [0007](0007-shared-db-auto-migration.md) | 공용 PostgreSQL 마이그레이션 자동 배포 | 2026-10-22 | 자동 적용 중지(0009 참고) |
| [0008](0008-shared-db-pull-agent.md) | 공용 DB 자동 배포를 Pull Agent 로 | 2026-10-22 | 자동 주기 적용 중지(0009 참고) |
| [0009](0009-local-first-db-workflow.md) | 개발은 각자 로컬 DB, 공용 DB 는 통합 확인용 | 2026-10-23 | 유효 |
| [0010](0010-upload-ingest-chat-integration.md) | 업로드 → 전처리 → knowledge → 채팅 연결(가린 글자만 외부 모델로) | 2026-10-23 | 유효 |
| [0011](0011-ai-call-minimization.md) | 가족 채팅 AI 는 요청할 때만 부르고 한도·캐시·동시 실행은 PostgreSQL 에 | 2026-10-23 | 유효 |
| [0012](0012-push-via-expo.md) | 폰 푸시는 Expo 푸시 서비스(→ FCM)로 보내고, 소통 메시지 푸시는 암호화해서 알림함에 저장하지 않는다 | 2026-11-05 |

## 번호 변경 이력

- 2026-10-30: 0007 과 0009 가 각각 두 문서에 겹쳐 있어서, AI 쪽 두 문서를 새 번호로 옮겼다. DB 쪽 문서는 `CLAUDE.md`·`README.md` 등이 이름으로 가리키고 있어 그대로 두었다.
  - 업로드·전처리·채팅 연결: 0007 → **0010** (`0010-upload-ingest-chat-integration.md`)
  - 가족 채팅 AI 호출 최소화: 0009 → **0011** (`0011-ai-call-minimization.md`)
  - 옛 번호로 쓴 글("ADR 0007"=업로드·분류기, "ADR 0009"=AI 호출 최소화)을 보면 위 표의 새 번호로 읽으면 된다. 문서 안 링크는 모두 고쳤다.
