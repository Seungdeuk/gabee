# 기능: 관리자 AI 초안 (프로액티브)

## 목적
관리자가 묻기 전에 AI 가 먼저 서버 알림과 새 문의를 살펴보고, **공지 초안**과 **문의 답변 초안**을 만들어 대기함에 둔다.
관리자는 초안을 읽고 고친 뒤 직접 저장한다. 초안 자체는 앱에 올라가지 않는다(2026-11-25 결정).

예외로, `AUTO_NOTICE_ENABLED` 를 켜면 서버 오류율 '긴급' 알림이 생길 때 **정해 둔 문구(AI 아님)** 로 공지를 바로 올린다.

## 화면 (관리자 페이지)
- 알림(첫 화면): 대기 중인 초안이 있으면 "AI 가 먼저 살펴보고 초안을 만들어 뒀어요: 공지 초안 N개 · 답변 초안 N개" 한 줄
- 공지사항: 맨 위 "AI 초안" 카드. 초안마다 종류·제목·내용·근거와 [버리기] [공지 칸에 넣기]. [공지 칸에 넣기]를 누르면 쓰기 칸에 채워지고, 관리자가 [공지 올리기]를 눌러야 올라간다. 최근 자동 공지 기록과 자동 공지 켜짐 여부도 보인다.
- 문의 및 신고: 맨 위 "AI 초안" 카드. 초안이 있는 문의 제목에 "AI 초안" 표시. 펼치면 초안·종류·근거와 [버리기] [답변 칸에 넣기]. 저장은 관리자가 [답변 저장]으로.
- 두 카드 모두 [지금 분석] 버튼(알림 점검을 기다리지 않고 한 번 분석).
- 공지사항: "올린 공지" 머리의 [글쓰기] 옆 [✦ AI 공지 초안]. 주제를 적고 [만들기]를 누르면 초안이 공지 쓰기 칸에 바로 채워진다(올리기는 관리자).
- 문의 및 신고: 줄 오른쪽 [답변하기] 옆 [✦ AI 초안](없으면 지금 만들기) / [✦ AI 초안 보기](있으면 펼치기).

## 언제 만드나
- 알림 점검(`POST /internal/alerts/run`, 비밀 토큰)이 규칙을 다 돌린 뒤 후속 작업으로(`app.shared.alert_rules.register_followup`)
- 관리자의 [지금 분석] 버튼

## 규칙
- 공지 초안: 최근 6시간의 '긴급'·'주의' 알림 문구(숫자만)와 최근 24시간 문의·신고 건수를 Claude 에 보낸다. Claude 가 공지가 필요 없다고 보면 대기함에 띄우지 않는다(같은 알림 묶음으로 다시 묻지 않게 기록만 남긴다). 같은 알림 묶음으로는 한 번, 공지 초안은 6시간에 하나까지.
- 답변 초안: 답변 없는 '접수' 문의를 오래된 것부터 한 번에 최대 5개. 제목·내용을 `mask_text` 로 가린 뒤 보낸다(연락처·이메일·카드·계좌·주소·라벨 있는 이름). 보낸 사람·가족 정보는 보내지 않는다. 문의 하나에 초안 하나.
- 자동 공지: 최근 1시간 안에 생긴 서버 오류율(`server_error_rate`) '긴급' 알림이 있을 때만. 6시간에 한 번. 문구는 서버 코드에 고정(`admin_drafts/service.py` 의 `AUTO_TITLE`·`AUTO_BODY`), 종류는 점검(maintenance).
- Claude 호출이 실패하면 그 차례를 건너뛴다(알림 점검 결과에는 영향 없음).
- 설정: `ADMIN_DRAFTS_ENABLED`(초안, 기본 꺼짐), `AUTO_NOTICE_ENABLED`(자동 공지, 기본 꺼짐).

## API (통합관리자 `require_operator("admin")`)
- `GET /admin/service/drafts` → `enabled`, `auto_notice_enabled`, `pending`(대기 초안 최근순, 최대 100), `auto_notices`(최근 자동 공지 5개)
- `POST /admin/service/drafts/run` → `enabled`, `notices`, `replies`, `published`(새로 만든 수)
- `POST /admin/service/drafts/notice` `{topic}` → 적은 주제(비우면 최근 긴급·주의 알림)로 공지 초안을 지금 만든다(가린 뒤 보냄). 꺼져 있으면 409, 주제·알림 둘 다 없으면 422, AI 실패 503
- `POST /admin/service/drafts/reply/{ticket_id}` → 문의 하나의 답변 초안을 지금 만든다(상태 무관, 버린 초안은 새 내용으로 다시 대기). 꺼져 있으면 409, 없는 문의 404, AI 실패 503
- `POST /admin/service/drafts/{draft_id}/status` `{status: used|dismissed}` → 204, 없으면 404

## 데이터
- `admin_drafts`: 초안 한 건 = 한 줄. `kind`(notice|reply), `source_key`(중복 방지 지문, `kind` 와 함께 유일), `ticket_id`(답변 초안만), `category`·`title`·`body`·`reason`(근거), `status`(pending|used|dismissed), `auto`·`notice_id`(자동 공지 기록), 시각. 회원 이름·연락처·사용자 id 칸은 없다.

## 완료 조건
- 꺼져 있으면 Claude 를 부르지 않는다
- 초안을 만들어도 공지·문의 답변은 바뀌지 않는다(자동 공지만 예외)
- Claude 로 가는 문의 글에 전화번호·이메일이 없다
- 같은 근거로 초안을 두 번 만들지 않는다, 한 번에 답변 초안 5개까지
- 통합관리자가 아니면 401/403
- `app/features/admin_drafts/tests/test_admin_drafts.py`

## 미정
- 장애가 끝났을 때 자동 공지를 "복구됐어요" 로 고치는 일(이번에는 하지 않음)
- 답변 초안에 관리자 챗봇 FAQ(`admin_knowledge/faq.md`)를 함께 줄지(지금은 프롬프트의 짧은 앱 안내만 쓴다)
- 알림 점검을 몇 분마다 부를지(Cloud Scheduler 설정, 배포 담당)
