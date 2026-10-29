# 채팅 통합(공용 DB·배포) 주의 기록

팀원 모두 Claude Code 로 작업하므로, `release/1.1` 병합·공용 DB 통합 때 참고할 수 있게 남긴다. 새 채팅 DB 변경이 생기면 아래 표에 한 줄 추가한다.

## 원칙: DB 먼저, 코드 나중
- family_chat 의 모델 테이블이 공용 DB 에 없으면 `schema_ready("family_chat")` 가 **`/family-chat/*` 전체(메시지 보내기·읽기 포함)를 503** 으로 막는다(`docs/adr/0006-schema-gate-degraded-start.md`).
- 그래서 공용 서버에는 **① 리비전 적용(DB 담당자가 Pull Agent 수동 실행, 규칙: `docs/adr/0009-local-first-db-workflow.md`) → ② 새 API 배포** 순서로 올린다. 리비전은 expand(추가)만이라 먼저 적용해도 옛 코드는 그대로 돈다.
- 사람이나 Claude Code 가 공용 DB 에 직접 `alembic upgrade/stamp` 를 실행하지 않는다.
- 병합 전 최신 `release/1.1` 을 받아 `alembic heads` 가 1개인지 확인한다. 둘이면 나중에 병합되는 PR 이 `down_revision` 을 현재 head 로 옮긴다.

## 채팅 관련 리비전 (적용 순서대로, 새 테이블·컬럼은 채팅 전체 503 위험)
| 리비전 | 내용 | PR |
|---|---|---|
| `message_deleted_at` ~ `d079d509f651` | 메시지 삭제(soft delete)·답장·반응(`8ba852cd9c10`, `message_reactions`)·고정 사본·나만 숨기기(`chat_pin_hides`) 등 | #146 #147 #149 #150 |
| `b7e4c1a95d36` | request edited at | 팀원 |
| `e727c6b5f41e` | **`chat_board_posts` 새 테이블**(게시판 지난 공지 기록, 기존 고정 공지를 복사) | #156 |

정확한 순서는 `cd apps/api && alembic history` 로 확인한다(위 표는 참고용이며 틀리면 history 가 기준).

## 게시판(#156) 메모
- 마이그레이션 이전 코드로 올린 공지는 게시판 기록이 없다. 새 코드에서 다시 올리면 만들어진다.
- 게시판에는 공지 **전체 본문**이 서버에 남고 원본 메시지를 지워도 유지된다(사용자 결정). 지우려면 게시판에서 글 삭제.
- 계정·그룹 삭제 기능을 나중에 추가하면 `chat_board_posts` 도 함께 정리해야 한다(본문 사본이 남는다).
