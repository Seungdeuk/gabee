# 구현 현황: 문의·신고 (support)

- 상태: 진행 중 (서버 완료, 앱 화면은 다른 팀원 담당)
- 요구사항: `docs/requirements/admin.md`(문의 및 신고), 결정 근거는 `docs/requirements/service-admin.md` 의 "문의·신고"(2026-11-04)

## 구현된 것

- `app/features/support/models.py`: 모델 `SupportTicket`(테이블 `support_tickets`). Alembic 리비전 `c4e8a2d6f190`(새 테이블 1개, expand만). 임시 PostgreSQL 에서 올리기·내리기·다시 올리기와 모델 일치(`alembic check`)를 확인했다.
- 앱 API (로그인한 본인 것만)
  - `POST /support/tickets`: `{kind: inquiry|report, title(1~100자), body(1~2000자)}`. 보낼 때의 가족(`active_group_id`)을 같이 남긴다. 201.
  - `GET /support/tickets/mine`: 내가 보낸 것 최근순 최대 100건, 상태와 답변 포함.
- 관리자 API·화면은 `features/admin` 이 공용 메타데이터의 표로 읽고 바꾼다(`docs/features/admin.md`).
- 정한 것(2026-11-04): 신고에도 사용자가 쓴 글만 담는다(가족 채팅 내용 첨부 없음), 신고 대상은 고르지 않는다, 답변 알림은 1차에 없다, 상태는 마지막 값만 남긴다.
- 테스트: `app/features/support/tests/test_support_api.py`(비로그인 401, 보내기·내 목록, 남의 것 안 보임, 가족 없는 회원, 잘못된 입력 422), 관리자 쪽은 `test_admin_api.py`.

## 남은 것

- 앱(Expo) 문의 보내기·내 문의 화면: 다른 팀원이 만든다(2026-11-04). 서버 API 는 위 두 경로를 쓴다.
- `require_operator` 병합 뒤 관리자 경로를 `/admin/service/tickets` 로 옮기기.
- 보내기 횟수 제한(도배 방지)은 정하지 않았다.
