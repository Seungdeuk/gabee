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
| [0015](0015-family-room-photo-to-library.md) | 가족방 사진은 문서 사진만 골라 가족 문서함에 읽어 넣고, 판별에는 로컬 OCR 과 Claude(haiku)를 함께 쓴다 | 2026-11-09 | 유효 |
| [0016](0016-agent-eval-loop.md) | Agent 평가는 새 패키지(`evals/agent_eval`)에 단계별로 쌓고, 개선 후보는 개발셋 실패로 만들어 검증셋으로 고르며, 보안 위반은 하드 게이트로 막는다 | 2026-11-10 | 유효 |
| [0017](0017-chat-share-cards.md) | 채팅 공유 카드는 서버가 읽어 만든 보낸 시점 스냅샷이고, 글자는 고정 문구로 둔다 | 2026-11-10 | 유효 |
| [0018](0018-leave-family-removes-direct-room-membership.md) | 가족을 나가면 그 사람의 1:1 방 참여도 함께 지우고, 연결은 `shared/member_exit` 훅으로 한다 | 2026-11-10 | 유효 |
| [0019](0019-hybrid-document-search.md) | 문서 검색은 임베딩 후보 안에서 글자 TF-IDF 를 계산해 순위를 섞는다(DB·의존성 변경 없음) | 2026-11-10 | 유효 |
| [0020](0020-family-photo-image-analysis-consent.md) | 가족 공유 사진의 이미지 분석(AI 추억 발견)은 자체 서버에서만, 기본 꺼짐·3중 조건(서버 스위치·가족 활성화·업로더 동의)으로만 한다 | 2026-11-17 | 초안(운영 활성화 미승인) |
| [0021](0021-auto-memory-exposure-policy.md) | 자동 추억 카드의 노출은 문서 판별(D-13)과 분리된 "분석 자격"으로 정하고, 개별 확인 없는 자동 게시(E1)는 독립 안전성 평가와 별도 승인 뒤에만 연다 | 2026-11-17 | 초안(자동 게시 미승인) |

## 번호 변경 이력

- 2026-10-30: 0007 과 0009 가 각각 두 문서에 겹쳐 있어서, AI 쪽 두 문서를 새 번호로 옮겼다. DB 쪽 문서는 `CLAUDE.md`·`README.md` 등이 이름으로 가리키고 있어 그대로 두었다.
  - 업로드·전처리·채팅 연결: 0007 → **0010** (`0010-upload-ingest-chat-integration.md`)
  - 가족 채팅 AI 호출 최소화: 0009 → **0011** (`0011-ai-call-minimization.md`)
  - 옛 번호로 쓴 글("ADR 0007"=업로드·분류기, "ADR 0009"=AI 호출 최소화)을 보면 위 표의 새 번호로 읽으면 된다. 문서 안 링크는 모두 고쳤다.
