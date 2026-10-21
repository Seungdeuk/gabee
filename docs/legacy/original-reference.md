# 원본 프로젝트 참고 (family-secretary_prj)

원본: https://github.com/kangminhun/family-secretary_prj (비공개)

이 레포(`gabee`)는 원본의 코드를 옮기지 않고 **뼈대만** 만들었다. 기능을 채울 때 아래 표에서 해당 부분만 찾아 읽는다.
원본은 서버 5개(+게이트웨이)와 웹 화면으로 나뉘어 있었고, 여기서는 FastAPI 서버 하나(`apps/api`)와 Expo 앱 하나(`apps/mobile`)로 합쳤다.

## 기능별로 어디를 보면 되나

| 우리 기능 | 지금 뼈대에 있는 것 | 원본에서 참고할 곳 | 채울 것(TODO) |
|---|---|---|---|
| family-group (로그인·가족 그룹) | 가입(토큰), 그룹 생성, 초대 코드 참여 | `comms/model-lab/comms_app/chat.py`, `chat_store.py`, `identity_*.py`, `firebase_auth.py`, `backend/app/chat_token.py` | 소셜 로그인(Firebase), 그룹 여러 개, 초대 만료·재발급, 권한(`docs/contracts/permissions.md`) |
| family-chat (소통) | 가족 그룹 대화 보내기·가져오기 | `comms/model-lab/comms_app/chat.py`, `chat_topics.py`, `chat_schedule.py`, `modules/` | 대화방 여러 개, 읽음 표시, 대화 주제 추천, 대화에서 일정 제안 |
| schedule (일정) | 일정 등록·확정·삭제 | `checkin/backend/checkin_app/routers/core.py`(events), `comms_app/chat_schedule.py` | 처방전·고지서에서 일정 자동 제안, 의례(ceremonies), 반복 |
| billing (가계) | 지출 등록, 월 합계와 균등 분담 계산 | `billing/backend/billing_app/` (`expenses.py`, `settlements.py`, `splits.py`, `ledger.py`) | 영수증 인식, 분담 방식, 구독, 정산 승인·송금 확인 흐름 |
| care (돌봄) | 컨디션·식사·약·걷기 기록(같은 날 덮어쓰기), 오늘 요약 | `checkin/backend/checkin_app/` (`models.py`, `routers/core.py`, `agent/`) | 병원 일정, 가족 요청, AI 안부 대화·제안 승인 |
| ai-assistant (AI 비서) | AI 채팅(키 없으면 기본 안내), 사진 올리기 | `capture/rag/` (분류·OCR·문서 저장·질의), `agent/src/` (사진 수집, 주간 리포트, 위치), `common/gabi_llm.py` | 사진 분류·OCR, RAG 질의, 주간 리포트, 위치 기록, 사용자별 AI 호출 한도 |
| more (기타 화면) | 오늘 요약·가족 그룹·설정 화면(임시 데이터) | `unified/index.html`의 홈, `checkin/frontend/src/app/(tabs)/` | 서버 연동, 자동 전송·위치 저장 동의 |

## 원본 앱 화면(이미 Expo 였던 것)
- 돌봄: `checkin/frontend/src/` (Expo Router, TypeScript)
- 결제: `billing/mobile/src/screens/` (React Navigation, TypeScript)
이 둘은 이미 React Native 라서 화면 구성과 흐름을 그대로 참고하되, 이 레포는 JavaScript(`.js`)로 쓴다.

## 일부러 가져오지 않은 것
- 웹 화면(`unified/`, comms 실험용 페이지, capture 웹 페이지, agent 웹): 앱 화면으로 다시 만든다.
- ADB/MTP(폰을 USB 로 읽는 부분), `android-app/`(앱 껍데기), `dashboard/`
- 게이트웨이(`backend/`)의 서비스 중계: 서버가 하나라서 필요 없다. 신원 확인 방식(토큰 헤더 `X-Gyeot-Token`)만 이어받았다.
- 샘플 사진, 평가 데이터, 배포·실행 스크립트

## 흐름도
원본과 이 레포의 흐름도(구조, 요청·인증, 사진 파이프라인, 협업)는 팀 공유용 페이지로 따로 정리해 두었다.
