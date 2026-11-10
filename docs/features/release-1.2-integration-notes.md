# release/1.2 통합(배포 브랜치 병합·공용 DB 반영) 주의 기록

팀원 모두 Claude Code 로 작업하므로, `release/1.2` 를 배포 브랜치(`main`)에 합치고 공용 DB 에 반영할 때 참고할 수 있게 남긴다. 새 항목이 생기면 해당 절에 한 줄 추가한다. 채팅 DB 쪽 기록은 [chat-integration-notes.md](chat-integration-notes.md), 공용 DB 절차는 `README.md` "통합" 절과 [docs/adr/0009-local-first-db-workflow.md](../adr/0009-local-first-db-workflow.md) 를 따른다. (작성 시점: 2026-11-03, `origin/main` 은 2026-10-30 기준.)

## 1. 원칙: DB 먼저, 코드 나중
- 기능이 쓰는 테이블·컬럼이 공용 DB 에 없으면 그 기능의 라우터가 `schema_ready(<기능>)` 때문에 **전체가 503**(`schema_not_ready`)이 된다(`docs/adr/0006-schema-gate-degraded-start.md`). 새 테이블을 추가한 리비전이 공용 DB 에 적용되기 **전에** 그 코드가 먼저 배포되면, 그 기능의 API 가 새 기능뿐 아니라 **기존 기능까지 모두** 막힌다.
- 그래서 공용 서버에는 **① 리비전 적용(DB 담당자가 Pull Agent 수동 실행) → ② 새 API 배포** 순서로 올린다. 사람이나 Claude Code 가 공용 DB 에 직접 `alembic upgrade/stamp` 를 실행하지 않는다.
- 병합 전 최신 `release/1.2` 를 받아 `cd apps/api && python scripts/check_alembic_migrations.py heads` 로 head 가 1개인지 확인한다. 둘이면 나중에 병합되는 PR 이 `down_revision` 을 현재 head 로 옮긴다.

## 2. `origin/main` 대비 `release/1.2` 에서 늘어난 Alembic 리비전
(순서는 `alembic history` 가 기준이고 아래 표는 참고용이다. 새 리비전이 병합되면 한 줄 추가한다.)

| 리비전 | 내용 | 영향 기능 | 주의 |
|---|---|---|---|
| `44171263393c` message_deleted_at, `432e249f600c` message_reply_to, `8ba852cd9c10` message_reactions, `c606f5b0deb6` chat_room_mutes, `d079d509f651` pin_board_snapshot_and_hides, `b7e4c1a95d36` request_edited_at, `e727c6b5f41e` chat_board_posts, `f06220eb955a` chat_file_attachments | 채팅(삭제·답장·반응·음소거·고정·게시판·파일) | family_chat(`b7e4c1a95d36` 는 일정 요청, schedule) | 새 테이블·컬럼이 없으면 해당 기능 전체 503 → 위 1 의 순서. 자세한 내용은 chat-integration-notes.md |
| `063b754e4c89` events_check_tables | 일정 "데일리 체크" 테이블 3개 추가 | schedule | 새 테이블 추가(expand) |
| **`5d1c0a7b9e42` drop_care_tables** | **돌봄 테이블 5개(`care_items`·`care_entries`·`care_records`·`care_meal_logs`·`care_locations`) 삭제** | care | **데이터가 사라지는 변경이다.** 리비전 설명에 "데이터 삭제 승인 표시는 DB 담당자가 승인한 뒤에 추가한다(아직 없음)" 이라고 적혀 있다. 통합 전에 **DB 담당자의 승인 근거(PR 리뷰)와 `destructive-approved: PR #번호` 표기**를 확인하고, 없으면 병합·반영하지 않는다. downgrade 는 구조만 되살리고 지워진 행은 돌아오지 않는다. |
| `27c7716f7207` knowledge_item_reads | 문서 구성원별 읽음 기록 테이블 추가(PR #224) | **ai_assistant** | 새 테이블 추가(expand). **이 리비전이 공용 DB 에 적용되기 전에 PR #224 코드가 먼저 배포되면 `ai_assistant` API 전체(문서 목록·상세·채팅·업로드·질문)가 503** 이 된다. 1 의 순서를 지킨다. downgrade 는 읽음 기록을 지운다. |

## 3. 앱·서버 호환 순서 (리포트)
- 서버 PR #222(문서 목록 `created_from`·`created_to`)가 **먼저** 배포돼야 앱 PR #223 의 "주마다 그 주 문서 조회"가 적용된다. 서버가 구버전이어도 앱이 그 주로 다시 걸러서 지금보다 나빠지지는 않는다(주마다 같은 최대 200건을 더 받는 트래픽만 늘어난다).
- 서버 PR #224(`seen` 필드, 읽음 기록)가 배포돼야 앱의 "아직 보지 않은 문서" 인사이트(후속 PR)가 동작한다. `seen` 이 없으면 앱은 그 인사이트를 만들지 않는다.
- 앱은 EAS 빌드로 배포되므로 서버가 먼저 올라가 있어야 새 앱이 새 필드를 만난다.

## 4. 소셜 로그인·공개 페이지 배포 체크
- **서버 환경변수**(운영 서버 `.env`): `GOOGLE_CLIENT_IDS`(웹·Android 클라이언트 ID, 쉼표로), `KAKAO_APP_ID`(카카오 앱 ID 숫자), `SUPPORT_EMAIL`(공개 페이지의 문의 이메일). 비어 있으면 해당 소셜 로그인은 `503 social_not_configured`, 이메일은 페이지에 보이지 않는다. **저장소의 개발용 `docker-compose.yml` 은 API 컨테이너에 일부 변수만 넘긴다. 운영 배포가 `.env` 를 컨테이너로 전달하는지(예: `env_file`) 배포 후 확인한다.**
- **공개 페이지**: `GET /`, `/privacy`, `/terms`(서버 `app/shared/public_pages`)와 카카오 중계 `GET /auth/kakao/callback` 은 로그인·DB 없이 열린다. 앞단 프록시(Caddy)가 `api.gabee.cloud` 의 `/` 를 API 로 그대로 넘기는지 확인한다(저장소에 Caddy 설정이 없어 코드로는 검증하지 못했다). 배포 전에는 이 주소들이 404 이다. 배포 후 `https://api.gabee.cloud/privacy` 맨 아래·9항에 문의 이메일이 보이면 `SUPPORT_EMAIL` 이 전달된 것이다.
- **구글 콘솔·카카오 콘솔**: 구글 브랜딩의 홈페이지·개인정보처리방침·약관 URL 은 위 공개 주소를 가리키고 승인된 도메인에 `gabee.cloud` 를 등록한다. 카카오 Redirect URI 는 앱 > 플랫폼 키 > REST API 키 화면에 `https://api.gabee.cloud/auth/kakao/callback` 을 등록한다(클라이언트 시크릿은 끈 채로 둔다).
- **EAS 환경변수**(expo.dev): `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID`, `EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID`, `EXPO_PUBLIC_KAKAO_REST_API_KEY`(preview·production). `EXPO_PUBLIC_SOCIAL_LOGIN_DISABLED` 는 삭제하거나 `false`. 값은 **빌드할 때** 앱에 들어가므로 바꾼 뒤 새 빌드가 필요하다. `app.json` 의 `scheme` 변경(`com.kangminhun.gabee` 추가)도 새 빌드부터 적용된다.
- `/docs`(API 문서 화면)가 `api.gabee.cloud` 에서 공개로 열려 있는 것을 확인했다(2026-11-03). 운영에서 비공개로 할지 별도로 정한다.

## 5. 팀 영역 수정 기록
- 사용자가 **이번 작업(문서 읽음 기록)에 한해** `ai_assistant`(팀원 영역) 수정을 허락했다(PR #224, #222). 두 PR 은 새 인자·필드·함수 추가와 상세 GET 의 읽음 기록만 했고 기존 동작은 바꾸지 않았다. 팀원 확인을 PR 본문에 요청했다.
- 앞으로 계정·그룹 삭제(탈퇴) 기능을 만들면 `knowledge_item_reads`(읽음)와 `chat_board_posts`(게시판 본문 사본)도 함께 정리해야 한다(`users.id` FK 에 `ondelete` 가 없다).
