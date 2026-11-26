# 관리자 AI 초안 (admin_drafts) 구현 현황

요구사항: `docs/requirements/admin-drafts.md`

## 구현된 것 (2026-11-25)
- 서버 `apps/api/app/features/admin_drafts/`
  - `service.py`: 공지 초안(최근 6시간 긴급·주의 알림 + 24시간 문의 건수 → Claude, 구조화 출력), 답변 초안(답변 없는 새 문의 최대 5개, `mask_text` 로 가린 제목·내용 → Claude), 자동 공지(서버 오류율 긴급 → 고정 문구, AI 없음, 6시간에 한 번). 지시문은 `prompts/notice.md`·`prompts/reply.md`.
  - `router.py`: `GET /admin/service/drafts`, `POST /admin/service/drafts/run`, `POST /admin/service/drafts/{draft_id}/status`(통합관리자). 불러올 때 알림 점검 후속 작업으로 `service.followup` 을 올린다.
  - `repository.py`: 알림·문의·공지 표는 다른 기능 모델을 가져오지 않고 표 이름으로 읽는다. 자동 공지는 `notices` 표에 바로 한 줄 넣는다(쓴 사람 비움).
  - `models.py`: `admin_drafts` 표, 리비전 `d7a2c94e1b58`.
- 공용 `app/shared/alert_rules.py`: `register_followup`·`all_followups`(점검 뒤 후속 작업). `admin_alerts/service.run_checks` 가 저장한 뒤 차례로 부르고, 실패하면 되돌리고 경고 로그(예외 종류)만 남긴다.
- 설정 `ADMIN_DRAFTS_ENABLED`·`AUTO_NOTICE_ENABLED`(둘 다 기본 꺼짐).
- 관리자 화면 `service_admin/static/app.js`: AI 초안 카드, 문의 펼침 안 답변 초안 상자, 첫 화면 안내.
- 테스트 `app/features/admin_drafts/tests/test_admin_drafts.py`(12개).

## 고도화 (2026-11-26, 평가 결과로 고침)
- 가림 보강(`service._mask`): `mask_text` 가 놓치던 라벨 없는 계좌번호("국민 123456-…")와 10자리 이상 번호를 가린 뒤 보낸다.
- 공지: 주제로 쓰는 공지에는 지금 '시각' 대신 오늘 날짜만 준다. 초안에 주제·알림에 없는 숫자가 있으면 한 번만 다시 쓰게 한다(`_ask_notice`). 주제에 없는 요일은 지우고, 관리자가 주제에 적은 연락처는 초안에서 원래 값으로 되돌린다(Claude 에는 가린 값만 간다).
- 공지 지시문(`prompts/notice.md`): 주제에 없는 날짜·기능·메뉴 위치·할 일을 덧붙이지 않기, 확인 중·진행 중·해결됨 단계별 쓰는 법, 장애 공지는 단계와 상관없이 `maintenance`.
- 답변: 회원용 앱 안내 자료(`prompts/app_guide.md`, 앱 화면·문서에서 확인한 사실만)를 함께 준다. 자료에 있으면 바로 안내하고 없는 것만 "확인한 뒤 안내"로 미룬다. **앱 화면이 바뀌면 이 파일을 고친다.**
- 답변 검사(`_reply_issues`): 가려진 이름(김** 회원님), 외국어 낱말, 약속하는 말이 있으면 한 번만 다시 쓰게 하고, 가려진 이름은 마지막에 지운다.
- 평가(저장소 밖 임시 스크립트, 진짜 Claude): 장애 공지 70개 해결 공지 분류 4/34 → 34/34, 불필요한 빈칸 5 → 0. 공지 21개 빈칸 9 → 0, 요일·가려진 번호 노출 0. 문의 33개 가리지 못한 개인정보 1 → 0.
- 테스트 21개.

## 남은 것
- 장애가 끝나면 자동 공지를 "복구됐어요" 로 고치기
- 운영에서 켜기 전에 알림 점검 주기(Cloud Scheduler)와 `ADMIN_ALERTS_ENABLED` 가 켜져 있는지 확인
