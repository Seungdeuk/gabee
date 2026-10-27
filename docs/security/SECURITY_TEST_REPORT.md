# 보안 시험 결과 (전 기능 통합 시험)

기준: 브랜치 `test/security-matrix`, `origin/main` `2e070d6`. 시험 파일: `apps/api/tests/test_security_matrix.py`(보조: `apps/api/tests/security_matrix_support.py`).
서비스 코드는 고치지 않았고 시험만 추가했다. 사실만 적고, 확인하지 못한 것은 "미확인"으로 적는다.

## 1. 환경과 방법

- 임시 SQLite(`apps/api/conftest.py` 가 만드는 임시 파일)만 사용. 공용 PostgreSQL·MVP DB·개인 Docker DB·`.env` 는 열지 않았다.
- **실제 Claude·Anthropic·외부 API 는 부르지 않았다.** 서버의 모든 외부 호출(Anthropic·Jev)이 `httpx.post` 를 거치므로
  이 함수 하나를 가짜(`FakeHttp`)로 바꿔 요청을 전부 기록한다. 가짜는 구조화 출력 스키마에 맞는 응답이나 도구 호출 시나리오를 돌려준다.
  Anthropic 외 주소(로컬 모델·Jev)로 가는 요청은 기록만 하고 실패 응답을 준다. 소셜 로그인(`urllib`)은 호출 경로를 시험하지 않았다.
- 한 모듈 안에서 앱·DB·시드(가족 A·B 의 모든 종류 리소스)를 한 번만 만들어 재사용한다. 이 모듈 단독 실행은 약 50초(측정 47~71초, 첫 시드에 15~20초), 전체 스위트와 함께 돌리면 약 18분이 걸린다(전체 스위트 시간은 이 모듈이 아니라 기존 시험이 대부분을 차지).
- 결과가 사실과 다르면 시험을 약하게 하지 않고 `known_defect(조건, reason)` 으로 남겼다. 사전 조건(상태 200, 호출 횟수, 대조 요청 성공 등)은 보통의 `assert` 로 먼저 확인하므로 깨지면 xfail 이 아니라 **실패**로 보이고, 결함 단언만 xfail 로 바뀐다. 결함이 고쳐지면 strict 항목은 XPASS 와 같이 실패해 표시를 지우게 된다(이전 버전의 `xfail(raises=AssertionError)` 는 마커 전체에 걸려 사전 조건 실패도 가릴 수 있어 이 방식으로 바꿨다).
- 환경 고정: 모듈 시작 때 Settings(`ALLOW_LEGACY_TOKEN_AUTH`, `CHAT_INCLUDE_SENSITIVE`, AI 한도·캐시·로그인·초대 제한 등)를 시험 전용 값으로 monkeypatch 해 `apps/api/.env` 에 따라 결과가 달라지지 않게 했다(`.env` 는 열지 않음). 한도 묶음(`register_bucket`) 값은 import 때 정해지므로 시험은 코드가 가진 실제 값을 읽어 쓴다. CORS 는 앱 생성 시점 값이라 고정하지 못해 환경 의존으로 표시했다.
  개인정보 가명화 '현황'처럼 설계상 의도일 수 있는 항목은 `strict=False`.
- 실행: `cd apps/api && PYTHONUTF8=1 PYTHONPATH=. python -m pytest tests/test_security_matrix.py -q`

## 2. 결과 요약

704개: 통과 689, xfail(결함·현황) 15, 건너뜀 0 (이전 609개에서 늘어난 이유: 격리 82항목마다 '리소스 주인 가족이 보내면 2xx' 대조 시험 82개 추가, 가족 없는 사용자 기대 표 시험·문서 격리(AI 켠 상태) 시험 등 추가, 위치 등 소수 정리. 중복 파라미터였던 1:1 방 시험 3개는 1개로 정리). `ruff check .` / `ruff format --check .` 통과.

| 영역 | 시험 수 | 통과 | xfail | 건너뜀 |
|---|---|---|---|---|
| 1. 인증: openapi 의 모든 비공개 경로가 인증 없이 401 (125개 경로·메서드) + 잘못된 자격(48) + 우회 방지 | 177 | 177 | 0 | 0 |
| 2. 그룹 격리: 가족 B 의 id 로 가족 A 사용자(소유자·구성원)가 접근 82항목×2 + **대조 82** + 1:1 방 비참여자 + 가족 없는 사용자 107 + 기타 | 약 385 | 약 384 | 1 | 0 |
| 3. 권한 규칙(역할표): 관리자·소유자·용돈·할 일·정산 담당·위치 동의·에이전트 확인 토큰 | 11 | 11 | 0 | 0 |
| 4. AI 관문: 10개 AI 엔드포인트 × (동의 꺼짐·정상 1회·사용자 한도·가족 한도·키 없음) + 쿨다운·동의 토글·AI 켠 상태에서 타 가족 문서 차단·호출 지점 정적 점검 | 60 | 59 | 1 | 0 |
| 5. 개인정보 전송 최소화 | 약 25 | 약 19 | 6 | 0 |
| 6. 속도 제한(검색·고정·모음·미리보기·사진·로그인·초대 코드) | 7 | 7 | 0 | 0 |
| 7. 로그에 개인정보 없음 | 2 | 2 | 0 | 0 |
| 8. 응답 형식·오류·적대적 입력 | 약 45 | 약 38 | 7 | 0 |

(영역별 수는 파라미터 묶음 기준 근사치. 합계는 pytest 출력 기준이다.)

### 2-1. 시험한 AI 엔드포인트(10개)와 관문

| 엔드포인트 | 기능 이름(한도 묶음) | 관문 |
|---|---|---|
| POST /family-chat/ai/analysis · replies · topics | analysis · reply · topics (기본 묶음: 사용자 10/일, 가족 30/일, 쿨다운 30초) | `ai_guard.run` |
| POST /schedule/agent | schedule_chat (30/100) | `ai_guard.run` |
| POST /ai-assistant/chat | assistant_chat (100/300) | `ask_guarded` → `ai_guard.run` |
| POST /ai-assistant/knowledge/ask | knowledge_ask (100/300) | `ask_guarded` |
| POST /ai-assistant/knowledge/items/{id}/summary | doc_summary (기본 묶음) | `ai_guard.run` |
| POST /ai-assistant/knowledge/answer | doc_answer (기본 묶음) | `ai_guard.run` |
| POST /billing/agent/chat · /care/agent/chat | billing_agent · care_agent (60/200) | `agent_guard.run_turn` → `ai_guard.run` |

각각에 대해: (a) 동의 꺼짐 → 403 `ai_not_enabled`, LLM 0회 (b) 사용자·가족 일일 한도(코드의 버킷 값을 읽어 사용) 초과 → 429, LLM 0회 (c) 동의 켜짐 정상 호출 → LLM 정확히 1회 (d) 서버 키 없음 → 외부 요청 0.
**모두 통과.** 코드 정적 점검(`test_every_outbound_call_site_is_known`, `test_every_llm_caller_goes_through_a_guard`)으로 `httpx.post` 호출 파일과 LLM 래퍼를 쓰는 파일이
알려진 목록과 같은지 강제한다(새 호출 지점이 생기면 시험이 실패해 사유를 적게 한다).

### 2-2. 관문을 거치지 않는 외부 호출 지점

| 지점 | 대상 | 관문 | 평가 |
|---|---|---|---|
| `shared/llm/jev.py` ← `ingest/classify.py` ← 파일 업로드(`POST /ai-assistant/files`) | **Jev(api.typesafe.ai, 외부)** | 없음(`TYPESAFE_API_KEY` 가 있을 때만 사용) | **결함 2번 참고** |
| (제거됨) `shared/llm/local.py`, `ingest/caption.py` | 로컬 Ollama | — | 최신 main 병합 후 코드에서 사라져 허용 목록에서도 뺐다(새 외부 호출 지점은 없음) |
| `family_group/social_providers.py` | 소셜 로그인 공급자(`urllib`) | 해당 없음(AI 아님) | 시험 제외 |
| 그 밖의 Anthropic 호출 | `ai_guard.run` 경유 | 있음 | 정상 |

## 3. 발견된 결함·불일치 (우선순위순)

| # | 심각도 | 경로 | 근거(시험) | 권장 수정 | 담당 영역 |
|---|---|---|---|---|---|
| 1 | 중간(직접 호출 시) | `POST /ai-assistant/knowledge/items` → 이후 문서 요약·질문·채팅 검색 도구 | `test_knowledge_items_api_body_is_masked_before_llm` (xfail strict ×3). **등급 조정**: 모바일 앱은 이 엔드포인트를 부르지 않고(GET·PATCH·DELETE 만 사용) 일반 사용 흐름에서는 노출되지 않는다 — 직접 API 를 호출해 문서를 넣을 때만 해당한다. 다만 같은 가족의 누구든 호출할 수 있고, 민감 지정(`sensitivity`)이나 `CHAT_INCLUDE_SENSITIVE=true`(기본값 true)와 겹치면 주민번호 같은 원문이 요약·질문·채팅 도구로 외부에 나가므로 위험하다(false 이면 민감 문서는 막히지만 민감으로 지정하지 않은 문서는 막히지 않는다). `knowledge/service.py::ingest()` 는 본문을 가리지 않고 저장(가리기는 파일 업로드 전처리·`update_item` 에서만). 이 API 로 넣은 주민번호·전화·이메일 원문이 Claude 요청에 그대로 실린다. 파일 업로드로 들어온 문서는 가려져 안전함(`test_uploaded_file_text_is_masked_before_llm` 통과) | `ingest()` 에서 `masking.mask_text(body, sensitive_kind(body))` 적용, 또는 이 API 를 내부 전용으로 제한 | ai_assistant/knowledge |
| 2 | 중간 | `POST /ai-assistant/files` → `ingest/classify.py` → Jev | `test_file_upload_does_not_call_external_jev_when_family_ai_is_off` (xfail strict). `TYPESAFE_API_KEY` 가 설정되면 가족 AI 동의가 꺼져 있어도 가린 글이 외부 서비스로 나간다(한도·동의 관문 없음) | `files.process_file` 에서 `ai_guard.is_enabled` 확인 후에만 Jev 사용(꺼져 있으면 로컬 모델) | ai_assistant/ingest |
| 3 | 중간 | `GET /family-chat/messages`(after_id·around_id·before_id), `POST /family-chat/pins`(message_id), `POST /billing/expenses`(amount) 등 상한 없는 정수 | `test_known_integer_overflow_inputs_return_500` (xfail strict ×5). 2**63 이상 → DB 드라이버 OverflowError(SQLite)/DataError(PostgreSQL 은 미확인이나 같은 종류 오류가 예상) → 500. 본문 `NaN` 은 검증 오류 응답 직렬화 단계에서 500. 응답에 스택은 없음 | 해당 Field 에 `le` 지정, 검증 오류 핸들러에서 `input` 제거(8번과 같이) | family_chat, billing, shared/errors |
| 4 | 중간(현황) | `POST /ai-assistant/chat` | `test_assistant_chat_masks_user_text_before_sending` (xfail, strict=False). 메인 채팅은 사용자 문장·앞 대화를 가리지 않고 전송(일정·탭 에이전트는 `mask_text` 적용) | `agent_guard.prepare` 와 같은 마스킹을 `ask_guarded` 앞에 적용 | ai_assistant |
| 5 | 중간(설계) | 정산·돌봄 에이전트 도구 결과·시스템 프롬프트 | `test_tab_agent_tool_results_do_not_leak_raw_personal_data`, `test_tab_agent_does_not_send_real_member_names` (xfail strict=False). 코드 주석상 의도된 설계(`agent_guard.py`)이나 지출 제목에 적은 전화·이메일, 구성원 실명, 위치 좌표가 가공 없이 LLM 으로 나간다. 사용자 질문 문장은 가려짐(`test_tab_agent_question_text_is_masked` 통과) | 자유 입력 문자열에 `mask_text`, 이름은 별칭 | billing, care, shared/llm |
| 6 | 낮음 | `POST /schedule/events` 의 `who_ids` | `test_event_who_ids_must_be_family_members` (xfail strict). 타 가족 사용자 id 도 201 로 저장(`share_with`·담당자·결제자·나눌 사람은 400). 이름은 응답에 없어 직접 유출은 없음 | `_share_targets` 와 같은 멤버십 검사 | schedule |
| 7 | 낮음 | 모든 검증 오류(422) | `test_validation_errors_use_common_format` (xfail strict). 공통 `{code,message}` 가 아니라 FastAPI 기본 `{detail:[...]}`, 항목마다 입력값(`input`)이 되돌아옴. CLAUDE.md 의 "에러 응답은 공통 형식만"과 불일치 | `RequestValidationError` 핸들러 추가(입력값은 싣지 않기) | shared/errors |
| 8 | 낮음(환경 의존) | CORS | `test_cors_does_not_allow_arbitrary_origins_by_default` (xfail strict=False). `cors_origins` 기본값 `*`. 인증이 쿠키가 아니라 헤더 토큰이라 위험은 낮다. 운영 `.env` 값은 미확인 | `.env.example` 에 `CORS_ORIGINS` 명시, 운영 값 확인 | shared/config, 배포 |
| 9 | 낮음(문서) | `docs/contracts/permissions.md` | 코드와 어긋난 부분: "기존 인증 방식의 잔여 위험" 절(45~49행)이 "레이트 리밋·로그인 절차 없음, 토큰 만료 없음"으로 적혀 있으나 로그인 실패 제한·JWT·Refresh Token 이 있다(레거시 익명 토큰만 평문·무만료로 남음). `current_user(x_gyeot_token, db)` 시그니처(21행)도 오래됨. 용돈(부모/그룹 소유자), 할 일 삭제(만든 사람·관리자), 일정 삭제(본인), 정산 담당, AI 동의(관리자) 규칙은 문서에 없고 코드(시험)로만 확인됨 | 문서 갱신 | docs |

> 임시 방어: 팀원이 결함 1·4 를 고치기 전까지 `DISABLED_AI_ROUTES`(경로 스위치)와 고위험 입력 사전 차단(주민·카드·계좌·비밀번호 400)을 둔다. 전화·이메일·이름·주소는 못 막는다 — [LLM_EGRESS_TEMP_GUARDS.md](LLM_EGRESS_TEMP_GUARDS.md).

독립 검토 반영(2차 수정) 요약 — 시험을 약하게 하지 않고 더 정확하게 만든 내용:

- 달 고정 제거: 시드 지출·정산·가계 시험의 `2026-10` 고정값을 현재 달 계산(`this_month()`)으로 바꿨다(2026-11-01 부터 깨지던 문제).
- 격리 시험 헛통과 제거: 이전에는 82항목 중 7개(대기자를 구성원으로 가정한 1:1 방·역할 변경, 본문이 누구에게나 `unknown_transfer` 인 송금 완료, 지출 id 를 송금 id 자리에 쓴 삭제, txt 라 쪽이 없는 원본 쪽 조회, 신청자만 가능한 가입 취소)가 '어떤 사용자가 보내도 같은 오류'였다. 요청을 모두 유효하게 고쳤다
  (같은 가족 셋째와의 1:1 방·역할 변경, 정산 확정 후 실제 송금, 이전 달에 만든 송금 id, 글자 층이 있는 PDF 의 쪽 조회, 신청자 본인의 취소).
  **모든 82항목에 대조 시험**(`test_cross_request_is_valid_for_owning_family`)을 붙였다: 같은 요청을 리소스 주인 가족(대조 가족)의 해당 사용자가 보내면 2xx 여야 한다(소비되는 리소스는 요청마다 새로 만든다). 대조 불가 예외 목록(`CONTROL_EXEMPT`)은 비어 있다 — **'미검증'으로 뺀 항목은 없다**.
- AI 를 켠 가족이 타 가족 문서 id 로 요약·답변·채팅 도구를 써도 B 문서가 LLM 요청에 들어가지 않는 시험 추가(요약 404, 답변 LLM 0회, 채팅 도구는 '없음' 결과, 자기 문서는 정상).
- 가족 없는 사용자 시험의 허용 코드를 정확한 표로 좁힘(예외 2개(승인·거절, 404 `not_found`)를 뺀 모든 그룹 경로는 400 `no_group` — 개수를 하드코딩하지 않고 규칙으로 단언). 오류 형식 시험도 상태·코드를 정확히 단언(이전의 `... if False else ...` 잔재·이름과 다른 사례 정정).
- 사용량 집계 단언을 정확한 값으로(기본 묶음 1회, 따로 세는 묶음 0), 키 없음 시험은 Anthropic 뿐 아니라 모든 외부 호출 0 확인.
- xfail 구조 변경(`known_defect`): 사전 조건 단언이 xfail 마커에 가려지지 않게 분리. 검증 오류(422) 시험도 같은 방식.
- 외부 호출 정적 점검 정규식 확대: `httpx.get/put/request/stream/Client/AsyncClient`, `requests`, `urllib.request`, `aiohttp`, `socket.create_connection`, `smtplib` 까지. 허용 목록은 파일:사유로 명시(소셜 로그인 공급자·SMTP 메일 포함). 새로 드러난 외부 호출 파일은 없었다.
- 정리: 중복이던 1:1 방 시험 파라미터, 사용하지 않던 코드, 가입 신청 성공 단언 누락 보강. 이번 수정으로 **새로 드러난 결함은 없다**.


관찰(결함으로 분류하지 않음, 시험이 현황을 고정):

- 초대 코드 실패 제한(`invite_attempts`)이 IP 기준이라, 한 IP 에서 코드를 5번 틀리면 그 IP 의 다른 사용자의 올바른 가입도 15분간 `too_many_attempts` 로 막힌다(시험 중 실제로 겪음). 가정 공유기 뒤의 가족이 서로 영향을 줄 수 있고, 반대로 계정별 제한은 기대대로 동작.
- `/openapi.json`, `/docs` 는 인증 없이 열린다(`test_openapi_and_docs_are_public_observation`). 운영 노출 여부는 배포 설정 확인 필요(미확인).
- `POST /ai-assistant/knowledge/search` 의 `include_sensitive` 는 요청 값이라 같은 가족 구성원은 민감 문서를 직접 볼 수 있다. `CHAT_INCLUDE_SENSITIVE` 는 LLM 으로 나가는 경로만 막는다(`test_knowledge_search_include_sensitive_flag_is_client_controlled_but_group_scoped`). 다른 가족은 불가.
- `schedule_card` 한도 묶음은 등록만 되어 있고 호출하는 코드가 없다(시험 대상 없음).
- 타 가족의 메시지 id 와 존재하지 않는 id 에 대한 응답이 같아 id 존재 여부를 알아낼 수 없음(통과).

## 4. 통과한 주요 보안 속성(요약)

- 인증 없이 부르면 모든 비공개 경로(125개)가 401. 공개 허용 목록(14개)은 시험 파일에 사유와 함께 명시. 새 경로는 자동으로 걸린다. 틀린 Bearer 는 유효한 레거시 토큰이 있어도 401(우회 불가).
- 가족 B 의 id(메시지·방·1:1 방·사진·고정·할 일·일정·지출·구독·정산·용돈·돌봄·문서·파일·가입 요청·구성원)를 가족 A 가 쓰면 400/403/404 이고 응답에 B 표식이 없다. 격리 시험이 끝난 뒤 B 의 데이터가 그대로임도 확인.
- 1:1 방은 방 참여자가 아닌 같은 가족 구성원도 404(메시지·사진·검색·고정·읽음·모음), 방 목록에도 나타나지 않는다. 가족 채팅 AI 요청에 1:1 방·타 가족 메시지는 포함되지 않는다.
- 가족 없는 사용자는 모든 그룹 경로가 400 `no_group` 이고(가입 요청 승인·거절 2개만 404 `not_found`), 새 경로가 생기면 자동으로 이 규칙에 걸린다(남의 요청 숨김 — 허용 코드를 정확한 표로 고정). 승인 대기자는 400 `no_group`, `group_members` 행이 없는 사용자는 403 `not_member`. AI 어시스턴트 채팅은 안내문만(LLM 0).
- 역할표: 관리자만(AI 동의·초대·가입 승인), 소유자만(역할 변경), 용돈은 부모 역할 또는 그룹 소유자만(자녀는 본인 사용 기록·본인 요청만), 정산 담당 변경 제한, 할 일 삭제는 만든 사람·관리자, 일정은 본인 것만, 위치는 본인 동의 필요. 에이전트 확인 토큰은 본인·가족·탭 한정 1회용.
- AI 관문 10개 엔드포인트 전부 동의·한도·1회 호출 규칙 준수. 가족별 AI 캐시 격리, 동의 끄면 캐시 결과도 돌려주지 않음.
- 가족 채팅 AI(분석·답장·주제)와 미리보기는 전화·이메일·주소·주민번호·카드·계좌·구성원 실명 원문이 요청에 없음. 캐시에도 원문 없음. 일정 에이전트는 주민번호·카드·계좌가 든 문장을 400 `sensitive_content` 로 거절(AI 호출 0, 한도 소모 없음)하고 전화·이메일은 가려서 보낸다(최신 main 의 개선 — 시험을 이에 맞춰 고침). 탭 에이전트 질문 문장도 가려짐. 파일 업로드 문서도 가려진 상태로 LLM 에 감.
- `CHAT_INCLUDE_SENSITIVE`: false 면 민감 문서가 채팅 도구·요약·답변 근거에 들어가지 않고(요약 403), true 면 들어간다(양쪽 확인).
- 속도 제한: 검색 30/분, 고정·해제 30/분, 모음 60/분, 미리보기 20/분, 사진 20/분, 로그인 실패(아이디별 5회), 초대 코드 실패 — 모두 429 + `Retry-After`, 사용자별로 분리. 한도 값은 코드 상수를 읽어 비교.
- 로그: 채팅·검색·AI·가입·로그인 대표 호출 뒤 서버 로그(caplog)에 메시지 글자·검색어·전화·이메일·주민번호·카드·비밀번호·레거시 토큰·JWT·Refresh Token 이 없음.
- 401/403/404/429 는 `{code,message}` 공통 형식이고 스택·SQL·내부 경로 없음. NUL·매우 긴 문자열·잘못된 JSON·SQL 문자열·경로 조작 파일명·깨진 사진은 500 이 아님(정수 오버플로·NaN 제외 — 결함 3).

## 5. 확인하지 못한 것(미확인)

- **실제 Claude 호출**: 하지 않았다. 가짜 응답 기준이라 모델이 가명화 토큰을 지키는지, 프롬프트 인젝션에 실제로 따르는지는 미확인.
- **PostgreSQL 전용 경로**: 돌리지 않았다(`*_pg_e2e` 제외). NUL 문자(PostgreSQL 은 문자열에 NUL 을 허용하지 않아 SQLite 와 다르게 500 이 될 수 있음), 정수 오버플로의 정확한 오류 종류, 다중 워커에서의 속도 제한·동시 실행 제한은 SQLite 로만 확인. 속도 제한은 프로세스 메모리 기반이라 워커가 여러 개면 한도가 워커별로 센다(`shared/rate_limit.py` 문서 참고).
- **실기기·앱 쪽**: 앱(React Native)의 토큰 저장·화면 노출·딥링크는 시험하지 않았다.
- 메일 발송(인증·비밀번호 재설정)·소셜 로그인 공급자 호출·이메일 열거 방지, 비밀번호 변경 후 토큰 무효화 흐름은 이 묶음에서 다루지 않았다(기존 기능별 시험 참고).
- 파일 업로드의 OCR·PDF·이미지 분류 경로(로컬 모델)는 텍스트 파일만 시험. 악성 PDF·압축 폭탄 등은 미확인(채팅 사진의 깨진 파일·크기 방어는 기존 시험이 다룸).
- 운영 배포 설정(CORS_ORIGINS, 문서 페이지 노출, TLS, 프록시 뒤 IP 처리)은 미확인.
- 동시성 경합(같은 요청 동시 전송으로 한도 초과 등)은 순차 요청으로만 시험.
- `GET /ai-assistant/photos`·`POST /ai-assistant/photos` 는 가족 단위 목록만 확인(개별 id 조회 경로 없음). 돌봄 식단·기록(`/care/records`, `/care/meal-log`)의 개별 리소스 격리는 목록 응답만 확인.


## 6. 최신 main 병합 후 조정(#86·#89·#93 등)

- 그룹 경로가 늘어(링크 3종 등) 개수 하드코딩 시험이 깨져 규칙 단언으로 바꿨다.
- 로컬 모델(`local.py`)·이미지 설명(`caption.py`)이 main 에서 제거되어 외부 호출 허용 목록에서 뺐다. 병합으로 **새로 생긴 외부 호출 지점은 없다**.
- 일정 에이전트가 민감정보(주민번호·카드·계좌) 문장을 외부로 보내지 않고 거절하도록 바뀌어, '가려서 전송' 시험을 '거절(400) + 전화·이메일 가림'으로 나눴다. 가림이 사라진 것이 아니라 강화된 것이다.
- 새로 드러난 결함 없음. 결과: 689 통과, xfail 15, 건너뜀 0.
