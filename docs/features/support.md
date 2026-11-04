# 구현 현황: 문의·신고 (support)

- 상태: 진행 중 (서버 API·관리자 탭 완료, 앱 화면 남음)
- 담당: kang(서버), 앱 화면은 다른 팀원
- 요구사항: `docs/requirements/support.md`

## 구현된 것

- `app/features/support/models.py`: 모델 `SupportTicket`(테이블 `support_tickets`). Alembic 리비전 `c4e8a2d6f190`(새 표 1개, expand 만).
- `POST /support/tickets`, `GET /support/tickets/mine`(router → service → repository). 보낼 때의 가족(`active_group_id`)을 같이 남긴다.
- `main.py` 에 `schema_ready("support")` 와 함께 등록. 표가 없는 DB 에서는 이 기능만 503.
- 테스트: `app/features/support/tests/test_support_api.py`. 보안 매트릭스에는 "가족 없이 써도 되는 경로"로 등록했다.
- 관리자 쪽(목록·상태·답변)은 `app/features/admin` 의 `GET /admin/support`, `PATCH /admin/support/{ticket_id}` 와 "문의 및 신고" 탭. `docs/features/admin.md` 참고.

## 남은 것

- 앱 문의 보내기·내 문의 화면(다른 팀원).
- 요구사항 "미정" 항목(보내기 횟수 제한, 관리자 알림).
