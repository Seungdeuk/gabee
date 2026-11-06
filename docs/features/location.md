# 구현 현황: 위치 공유 (베타)

요구사항은 `docs/requirements/location.md`. **이 브랜치(`feature/hojenn-location-beta`)에만 있고 `release/1.2` 에 병합하지 않는다.**

## 서버 (`apps/api/app/features/location/`)
- 완료: 동의·철회(철회 시 위치 삭제), 위치 올리기, 활동 구역 계산(통계, AI 없음), 구역 이탈 알림(부모에게 즉시, 6시간 쿨다운), 일시정지(최대 14일, 켤 때 부모에게 사실만 알림), 가족 위치 조회(부모만 가족 전체), 시연용 이탈 판정.
- 스위치: `LOCATION_ENABLED`(기본 꺼짐). 꺼져 있으면 동의 켜기·위치 올리기·가족 조회·일시정지·시연은 503(`location_disabled`), 상태 조회·동의 철회·내 위치 삭제만 열려 있다.
- 마이그레이션 `8a3f6c2d9b15`(테이블 3개 추가). 임시 PostgreSQL 에서 upgrade/downgrade 와 스키마 일치(location 테이블)를 확인했다. `events_check_items`·`notifications.group_id` 불일치는 release/1.2 에 이미 있던 것이다.
- 시험: `app/features/location/tests/test_location_api.py` 13개 통과.

## 앱 (`apps/mobile/src/features/location/`)
- 완료: 돌봄 탭(`care` 라우트, 제목 "돌봄")에 `지갑 | 위치` 구분. 위치 구역(동의, 여행 모드, 약식 지도, 가족 상태, 시연 도구). 앱이 켜져 있는 동안 1분마다 위치 전송(`expo-location`, 앞에서만).
- 지도 타일·지도 라이브러리는 쓰지 않는다(의존성 추가 없음). 점과 활동 구역을 상대 위치로 그린다.
- 시험: `tests/locationgeo.test.js` 통과. 앱 전체 시험은 기존 실패 1개(`schedule_lunar`)만 남는다. 변경 파일 린트 통과(import 규칙 제외). 실기기 확인은 하지 않았다.

## 이동 기록 타임라인 — 서버 완료, 앱 화면은 다음
- 변환기 `timeline.py`(시험 10개), 왕복 검증 `run_timeline.py`(머묾 recall·precision 1.00, 지어낸 시간 0분), 장소 이름 붙이기(`location_places`, 마이그레이션 `d3b8f15e92a4`), API `GET /location/timeline`·`/location/places`, `POST /location/places`, `DELETE /location/places/{id}`(시험 11개). 위치 시험 합계 54개.
- 구간은 저장하지 않고 요청 때 만든다(설계 6번 "위치를 올릴 때 다시 만든다"에서 바꿈: 파생 데이터를 남기지 않고 결과가 같다).

## 앱을 꺼도 계속 공유 (백그라운드 수집) — 구현됨, 실기기 확인 전
- 서버: `PUT /location/background`, `location_settings.background_enabled/background_at`(마이그레이션 `c7e2a9d41f08`, 컬럼 추가만), `/location/me`의 `background`. 별도 동의 이력은 `location_consent_events`(경로 `location_bg`). 위치 공유 철회 시 함께 꺼지고 이력이 남는다. 시험 4개 추가(위치 시험 합계 33개).
- 앱: `backgroundTask.js`(TaskManager 작업을 루트 레이아웃에서 등록, 깨어나면 저장된 Refresh Token으로 세션 복원 후 위치 업로드), `sharing.js`(권한·시작·중지), `BackgroundCard.js`(동의 안내 7항목과 켜기·끄기), `consentText.js`, `background.js`(수집 조건 `wantsBackground`·`toPoint`·`pickToSend`, 시험 3개). 여행 모드·철회·서버 거절 시 기기 수집이 멈춘다.
- 설정: `app.json`에서 위치 4개 권한의 `blockedPermissions` 삭제, expo-location 플러그인의 백그라운드 위치·포그라운드 서비스·iOS 백그라운드 옵션 켬 → **새 개발 빌드 필요**. Expo Go에서는 동작하지 않는다.
- 확인하지 못한 것: 실기기 동작(권한 흐름, 앱 종료 후 수집, 배터리), 안드로이드 14+ 포그라운드 서비스 동작, 앱 종료 중 Refresh Token 갱신과 앱 재실행 시의 경합.

## 위치 기록 질문용 검색(RAG) — 검색 단계까지 완료
- 요약 문장: `summary.py`가 구간(머묾·이동·일시정지·동의 없음·평소 구역 밖)을 문장으로 바꾼다. 규칙만 쓰고 LLM·좌표가 없다. 조각 종류는 span(구간), move(이동), day(하루 요약), place(장소별 방문 횟수·시각)이고, 자정에서 잘라 날짜·요일이 문장에 들어간다.
- 적재·검색: `rag.py`(`index_spans`, `search`), 테이블 `location_chunks`(마이그레이션 `b4d9e1a7c630`, pgvector 384차원 + HNSW). 임베딩은 문서 지식과 같은 e5-small ONNX를 서버에서 계산한다(모델 폴더가 없으면 해시 임베더). 검색은 질문한 사람이 볼 수 있는 사용자(`visible_user_ids`)의 조각만 후보로 하고, 날짜 범위·시각·조각 종류를 받아 좁힌다. 동의 철회·위치 삭제 때 조각도 함께 지운다.
- 임시 PostgreSQL에서 upgrade/downgrade·스키마 일치를 확인했고, 실제 pgvector `<=>` 검색 경로(권한 범위, 시간대 포함 값)를 확인했다.
- 시험: `test_rag.py` 7개 통과(위치 시험 합계 20개).
- 평가(`apps/api/evals/location/`, 가짜 가족 데이터만, LLM·키 없음): `python -m evals.location.validate`(데이터 검증), `python -m evals.location.run_retrieval --embedder e5|hash`.
  - e5 임베더: 질문 문장만으로 검색 recall@3 0.45 → 질문에서 뽑은 사람·날짜·시각·조각 종류 필터를 더하면 0.93(MRR 0.81), 권한 누수 0. 해시 임베더는 0.28 → 0.72로 기준(0.9)에 못 미친다.
  - 필터는 실제 서비스에서는 에이전트가 검색 도구 인자로 넘기는 값이고, 평가에서는 규칙(`query_hints.py`)이 대신한다. 에이전트가 인자를 맞게 뽑는지는 답변 평가에서 따로 본다.
  - 한계: 규칙과 정답 계산은 이 40개 질문을 보면서 다듬었다(과적합 가능). 놓친 질문은 q-012, q-014(순서 질문에서 출발·도착 방향 구분). 모호한 질문 q-035·q-036은 후보 장소를 모두 찾지 못했다. q-037은 질문의 상대 날짜가 평가 시계와 맞지 않아 제외했다.

## 질문 에이전트 (`agent.py`, `POST /location/ask`) — 베타 범위에서 제외, 서버 스위치로 꺼 둠(`LOCATION_ASK_ENABLED`, 기본 꺼짐, 코드는 그대로)
- 유저 결정(2026-11-06): 위치 기록 질문 답변(검색 에이전트) 기능은 제외한다. 앱 질문 입력창·ToolOps·추가 평가는 하지 않는다. 아래는 제외 전에 만든 내용의 기록이다.
- 제외 전 상태: 서버 완료, 실제 LLM 평가 완료(전체 2회 반복 75/78, 프롬프트 보강 후 남은 실패는 케이스 금지어 규칙 때문).
- 도구 `search_location_history`(사람·날짜·시각·질문 성격·찾을 내용). 권한(부모=가족 전체, 그 밖=본인)은 서버가 정하고 LLM 이 권한 밖 사람을 골라도 데이터가 가지 않는다. 마스킹·가족 AI 동의·사용 기록·전용 한도(`AI_LOCATION_AGENT_*`, 사용자 30·그룹 100)는 기존 관문을 쓴다. 관리자 화면 이름 "위치 기록 에이전트" 등록.
- 시험: `test_agent.py` 9개(가짜 LLM: 도구 호출 흐름, 자녀의 권한 밖 요청, 이름 없는 질문의 범위, 없는 이름, 시스템 프롬프트, 비구성원 403, 한도 묶음, 엔드포인트 스위치·로그인·모델 실패·성공). 위치 시험 합계 29개.
- 답변 평가 `python -m evals.location.run_answer`(ANTHROPIC_API_KEY 필요): 도구 사용 여부, 필수·금지 문구(같은 뜻 표현·횟수 표기 인정), 좌표 모양 숫자, 답에 나온 장소가 가져온 문장에 있는지(지어내기 점검). `--dry-run`으로 배선만 확인했고(점수 의미 없음) **실제 LLM 점수는 아직 없다**(이 PC 셸에 키가 없고 `.env`는 읽지 않는다).
- 범위 밖 질문(out_of_scope) 4개의 기대 문구("날씨", "일정 정보", "배터리", "여행 모드")는 이 에이전트가 답할 수 있는 범위를 벗어나 도구 미사용·금지어 없음만 본다.

## 하지 않은 것
- 위치 점(`location_points`)을 구간(머묾·이동)으로 바꾸는 단계: 적재기는 구간을 받는다. 실제 위치에서 구간을 만들려면 머문 곳 판정과 장소 이름 붙이기가 필요하다.
- 실제 LLM 답변 점수 측정, ToolOps 호출 기록 테이블(현재는 `ai_usage_logs`의 기능·토큰·호출 수·상태만), 앱 질문 입력창.
- 14세 미만 보호자 동의(안내 문구에만 있고 확인 절차는 없음), 푸시 알림 연결(알림함에는 쌓인다), 시간대·속도 신호.
