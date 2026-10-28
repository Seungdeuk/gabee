# 구현 현황: 알림함 (notifications)

- 요구사항: `docs/requirements/notifications.md`
- 설계·계획: `docs/superpowers/specs/2026-10-28-notifications-design.md`, `docs/superpowers/plans/2026-10-28-notifications.md`

## 서버 (구현됨)

- `app/shared/notifications.py`: 모델 `Notification`(테이블 `notifications`), 분류 `KINDS`, 기록 함수 `notify()`.
  - 받는 사람마다 한 줄. 그룹 구성원이 아닌 사람과 행동한 본인은 건너뛰고, 같은 사람은 한 번만 받는다.
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
- 2차로 미룬 것: 일정·가계·돌봄·AI 기록·구성원 변경.

## 앱

- `features/notifications/`: `api.js`(목록·개수·읽음·전부 읽음), `kinds.js`(분류별 이름·아이콘·색과 알림을 눌렀을 때 이동 경로 `routeFor`), `format.js`(배지 글자·상대 시각·개수 실패 처리), `useUnread.js`(안 읽은 개수 훅, 못 읽으면 0), `screens/NotificationsScreen.js`, `components/NotificationRow.js`.
- 홈(AI 채팅) 상단 종 아이콘과 숫자 배지(`AppHeader`의 `onBell`·`bellBadge`). 연결은 라우트 `app/(tabs)/chat.js`에서 한다(기능끼리 서로를 import 하지 않기 위해). 누르면 `/notifications` 화면이 열린다.
- 알림 화면: 분류 칩(전체·일정·가계·돌봄·가족·기록), 안 읽은 알림은 굵은 제목과 점, 누르면 읽음 처리 후 이동(가입 요청 → `/family-requests`, 가입 승인 → `/family`, 그 외는 읽음만), "모두 읽음"(현재 분류만), "더 보기"로 다음 페이지, 빈 목록·불러오기 실패(다시 시도) 안내.
- 개수는 홈 화면에 돌아올 때마다 다시 읽는다(폴링·폰 푸시 없음). 못 읽으면 배지만 숨긴다.

## 시험

- 앱: `tests/notifications.test.js`(API 경로, 분류·이동 규칙, 배지·시각 표시, 개수 실패 처리). 화면 렌더링과 실기기는 자동화하지 않았다.
- 서버: `tests/test_notifications_model.py`, `app/features/family_group/tests/test_join_notifications.py`,, `tests/test_notifications_notify.py`, `app/features/notifications/tests/test_notifications_api.py`.
