# 2026-11-04 서비스 관리자 페이지·문의 정리 (kang)

- 11-02 에 딴 관리자 브랜치(#230)가 release/1.2 보다 123커밋 뒤처지고 `auth.py`에서 충돌해, 최신 release/1.2 에서 기능별 브랜치 두 개로 다시 만들었다.
  - `feature/kang-support-tickets`: 문의·신고 앱 API 와 `support_tickets` 표.
  - `feature/kang-service-admin-dashboard`: 관리자 페이지(회원·가족 그룹·기능·AI 이용).
- 관리자 확인은 `users.is_staff` 칸 대신 팀이 병합한 `require_operator("service_admin")`(허용 목록 `SERVICE_ADMIN_USER_IDS`)로 바꿨다. 막히면 404 대신 403 `operator_required`.
- release/1.2 에서 돌봄 기능·표가 지워져 관리자 "기능 관리"의 돌봄 줄을 뺐다.
- 관리자 "문의 및 신고" 탭은 두 PR 이 병합된 뒤 별도 PR 로 붙인다.
- 확인한 것: release/1.2 에 Alembic head 가 이미 2개다(`11498574b1ed` 데일리 체크, `27c7716f7207` 문서 읽음이 같은 부모 `063b754e4c89`). DB 담당자에게 알린다.
