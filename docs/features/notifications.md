# 구현 현황: 알림함 (notifications)

- 요구사항: `docs/requirements/notifications.md`
- 설계·계획: `docs/superpowers/specs/2026-10-28-notifications-design.md`, `docs/superpowers/plans/2026-10-28-notifications.md`

## 서버 (구현됨)

- `app/shared/notifications.py`: 모델 `Notification`(테이블 `notifications`), 분류 `KINDS`, 기록 함수 `notify()`.
  - 받는 사람마다 한 줄. 그룹 구성원이 아닌 사람과 행동한 본인은 건너뛰고, 같은 사람은 한 번만 받는다. `group_id=None`(개인 알림)이면 구성원 확인 없이 받는 사람에게 남기고, 목록·읽음 조회도 개인 알림은 본인에게 항상 보인다.
  - 저장이 실패해도 예외를 밖으로 내지 않는다(savepoint 안에서 저장). 알 수 없는 분류는 `ValueError`.
  - 커밋은 부르는 기능이 한다.
- `app/features/notifications/`: 내 알림 API (항상 로그인한 본인 것만, 지금도 구성원인 그룹의 알림만).
  - `GET /notifications?kind=&limit=&cursor=` (최신순, 커서 방식 페이지 이동, 잘못된 커서는 400 `invalid_cursor`)
  - `GET /notifications/unread-count` (`total`, `by_kind`)
  - `POST /notifications/{id}/read` (이미 읽은 것은 시각을 바꾸지 않음, 남의 알림은 404)
  - `POST /notifications/read-all` (본문 `{kind?}`로 분류만 읽음)
- Alembic 리비전 `1ee3e7d2ff2e`(새 테이블 1개, expand만).

## 연결된 사건

- 가족 그룹(`kind=family_group`, `join_service.py`에서 `notify()` 호출)
  - `join_requested`: 새 가입 요청이 만들어졌을 때 그룹 관리자(owner/admin)에게. 같은 사람의 중복 신청(기존 대기 요청을 돌려주는 경로)에서는 알림을 만들지 않는다.
  - `join_approved`: 승인되었을 때 신청자에게.
  - 가입 거절은 알림이 없다(신청자가 아직 구성원이 아니라 알림함에 남지 않는다. 신청자는 기존 대기 화면에서 결과를 본다).
- 고객센터(`kind=support`, `admin/service.py`에서 `notify()` 호출)
  - `ticket_answered`: 관리자가 답변을 저장하면 문의를 보낸 사람에게. `notifications.group_id` 가 비어 있는 개인 알림이라 가족이 없는 사용자도, 가족을 옮긴 사용자도 받는다(Alembic 리비전 `5b7c1d9e3a46`, NOT NULL 완화만).
- 일정(`kind=schedule`, `schedule/together.py`에서 `notify()` 호출, 대상은 `target_type=schedule_request`)
  - `request_received`("같이해요가 도착했어요"): 같이해요를 보내거나, 받는 사람을 바꿔 새로 든 사람에게. 이미 받은 사람에게는 다시 가지 않는다.
  - `request_answered`("같이해요에 답이 왔어요"): 받는 사람이 처음 답하거나 답을 바꿨을 때 보낸 사람에게. 같은 답을 다시 보내면 알림이 없다. 수락·거절 여부와 답한 사람은 문구에 담지 않는다.
  - 알림을 눌러도 이동하는 화면은 아직 없다(읽음 처리만).
- 푸시 설정·토큰 API(푸시 1단계 서버 A, 발송은 서버 B 에서 연결)
  - `GET`·`PUT /notifications/push-settings`: 내 푸시 설정(켜기·끄기 `enabled`, 내용 표시 방식 `preview_mode` full/sender/hidden, 끈 분류 `muted_kinds`, 방해금지 `quiet_start`·`quiet_end`). 저장한 적이 없으면 기본값(줄을 만들지 않는다). 방해금지 시작·끝은 둘 다 있거나 둘 다 없어야 한다(아니면 422).
  - `PUT /notifications/push-token`(204): 이 기기의 Expo 푸시 토큰 등록. 같은 토큰이 이미 있으면 소유자·정보를 갱신한다(기기를 다른 사람이 쓰면 소유자가 옮겨 간다). 형식이 다르면 422. `DELETE /notifications/push-token`(204): 내 토큰만 해제(없어도 204).
- 2차로 미룬 것: 가계·돌봄·AI 기록·구성원 변경.

## 앱

- `features/notifications/`: `api.js`(목록·개수·읽음·전부 읽음), `kinds.js`(분류별 이름·아이콘·색과 알림을 눌렀을 때 이동 경로 `routeFor`), `format.js`(배지 글자·상대 시각·개수 실패 처리), `useUnread.js`(안 읽은 개수 훅, 못 읽으면 0), `screens/NotificationsScreen.js`, `components/NotificationRow.js`.
- 홈(AI 채팅) 상단 종 아이콘과 숫자 배지(`AppHeader`의 `onBell`·`bellBadge`). 연결은 라우트 `app/(tabs)/chat.js`에서 한다(기능끼리 서로를 import 하지 않기 위해). 누르면 `/notifications` 화면이 열린다.
- 알림 화면: 분류 칩(전체·일정·지갑·안부. 가족·기록 알림은 칩 없이 "전체"에서만 보인다), 제목·부제·칩은 가운데 정렬, 안 읽은 알림은 굵은 제목과 점, 누르면 읽음 처리 후 이동(가입 요청 → `/family-requests`, 가입 승인 → `/family`, 그 외는 읽음만), "모두 읽음"(현재 분류만), "더 보기"로 다음 페이지, 빈 목록·불러오기 실패(다시 시도) 안내.
- 개수는 홈 화면에 돌아올 때마다 다시 읽는다(폴링·폰 푸시 없음). 못 읽으면 배지만 숨긴다.

## 고객센터 답변 알림(앱, 2026-11)
- 분류 `support`("고객센터", 알림 칩은 두지 않고 "전체"에서만 보임)와 이동 규칙(`routeFor` → `/support?tab=mine`)을 앱에 추가했다. 서버는 관리자가 답변을 저장할 때(`admin/service.update_support`) `notify(group_id=None, kind="support", event="ticket_answered")` 로 보낸 사람에게만 남긴다. 새 답변이나 고친 답변일 때만 보내고(같은 답변을 다시 저장하거나 상태만 바꾸면 없음), 문구는 고정("문의에 답변이 달렸어요")이며 문의 제목·내용·답변은 담지 않는다.

## 시험

- 앱: `tests/notifications.test.js`(API 경로, 분류·이동 규칙, 배지·시각 표시, 개수 실패 처리). 화면 렌더링과 실기기는 자동화하지 않았다.
- 서버: `tests/test_notifications_model.py`, `app/features/family_group/tests/test_join_notifications.py`,, `tests/test_notifications_notify.py`, `app/features/notifications/tests/test_notifications_api.py`.

## 화면 다듬기 (release/1.1)
- 알림 화면의 분류 칩 줄: `Screen` 의 `pinned` 영역은 좌우 여백이 없어 칩이 왼쪽 끝에서 시작하던 문제를 고쳤다. 제목과 같은 여백(`spacing.xl`)을 두고, 한 줄로 두어 폭이 모자라면 가로로 민다.
- 상단바(`AppHeader`): 종 아이콘이 붙어 오른쪽 버튼이 늘면서 로고가 왼쪽으로 밀리던 문제를 고쳤다. 왼쪽·오른쪽 영역을 같은 너비(flex 1)로 두어 로고가 항상 가운데에 온다.
- 종 배지: 숫자가 작고 종과 겹쳐 안 보일 수 있어 배지를 20px 로 키우고 글자 줄 높이를 고정했다. 실기기(안드로이드)에서는 아직 확인하지 못했다.

