# 구현 현황: 공지사항

- 상태: 완료(1차)
- 담당: kang
- 요구사항: docs/requirements/notices.md

## 구현된 것
- 서버 `app/features/notices/`: 모델(`notices` 표), 앱용 `GET /notices`. 테스트 `app/features/notices/tests/test_notices_api.py`(로그인 필요, 빈 목록·최근순·응답 칸).
- 서비스 관리자 `app/features/service_admin/`: 목록·쓰기·고치기·지우기 API 와 "공지사항" 탭(쓰기 칸, 목록, 고치기·지우기 버튼, 지울 때 확인 창). 테스트 `test_notice_write_edit_delete`, `test_notice_rules`(401·403·422·404).
- 앱 `apps/mobile/src/features/notices/`: `api.js`, 칩·날짜·미리보기 계산 `notices.js`(시험 `tests/notices.test.js`), 읽음 기억 `readStore.js`(AsyncStorage), 화면 `screens/NoticesScreen.js`, 경로 `/notices`. 더보기 메뉴의 공지사항이 이제 열린다.
- 마이그레이션 `alembic/versions/7d2e4a9c1b38_notices.py`.

## 남은 것
- 새 공지 알림(정하지 않음), 고정 공지.
