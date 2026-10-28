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

(Task 5~6에서 갱신)

## 시험

- 서버: `tests/test_notifications_model.py`, `tests/test_notifications_notify.py`, `app/features/notifications/tests/test_notifications_api.py`.
