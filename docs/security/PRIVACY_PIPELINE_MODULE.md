# 가명화 파이프라인 모듈 (`app/shared/privacy`)

외부 LLM(Claude)으로 보내는 가족 대화에서 개인정보를 줄이는 서버 기준 모듈이다. 표준 라이브러리만 쓰고 DB 모델·기존 기능 코드에 의존하지 않는다(독립 패키지). 가족 채팅 AI(분석·답장·주제·미리보기, `app/features/family_chat/ai_service.py`)에 연결되어 있다.

**하지 않는 말**: 이 모듈은 종단간 암호화(E2EE)가 아니다. 서버는 원문을 읽는다. 탐지는 정규식·검증 규칙이라 한국어 이름·주소를 놓칠 수 있고, 마스킹이 완전한 보호를 보장하지 않는다. 성능은 `docs/security/PII_EVALUATION.md` 를 본다.

## 구성

| 파일 | 역할 |
|---|---|
| `types.py` | `Kind`(PHONE, EMAIL, RRN, CARD, ACCOUNT, SECRET, ADDRESS, PERSON), `Risk`, `Span` |
| `detectors.py` | `detect(text, known_names=()) -> list[Span]` 탐지·겹침 정리(전각·대시 변형은 반각으로 접어서 본다) |
| `policy.py` | `Policy`, `Action`(KEEP/MASK/BLOCK), `ANALYSIS`/`REPLY`/`TOPICS` |
| `pseudonymizer.py` | 요청 단위 `Pseudonymizer`: `apply`, `restore`, `clear` |
| `gateway.py` | `prepare_transcript`, `restore_value`, `restore_json` (통합 지점, 순수 함수) |
| `eval/` | 합성 평가 데이터 2종과 생성기, 평가 스크립트는 `apps/api/scripts/eval_pii.py` |

## 정책 표

| 종류 | 위험도 | 동작 (ANALYSIS / REPLY / TOPICS 공통) | 응답 복원 |
|---|---|---|---|
| PHONE, EMAIL | 중간 | MASK (`[PHONE_1]`, `[EMAIL_1]`) | 복원하지 않고 `(연락처)`, `(이메일)` 로 대체 |
| ADDRESS | 중간 | MASK (`[ADDR_1]`) | ANALYSIS 만 복원(일정 장소), REPLY·TOPICS 는 `(주소)` |
| PERSON | 낮음 | MASK (`[PERSON_1]`), 발화자 이름도 같은 토큰 | 복원(담당자 연결). 가족 호칭이 표시 이름이면 토큰화하지 않음 |
| ACCOUNT, SECRET, RRN, CARD | 높음 | BLOCK: 점수 >= `block_min_score`(0.7)이면 그 **메시지 전체**를 `[민감정보가 있어 제외된 메시지]` 로 대체. 점수가 낮으면 값만 `[RRN]` 등 복원 불가 토큰으로 가림 | 복원 불가 |

정책은 `Policy.actions`·`block_min_score`·`restore_kinds` 필드라서 값을 바꾸면 동작이 바뀐다. 표에 없는 종류는 KEEP. REPLY(15줄)·TOPICS(30줄)의 `max_context_lines` 는 호출부가 문맥 줄 수를 정할 때 참고하는 값이다.

복원 범위를 좁힌 이유: 요약 문장에 실제 전화·이메일이 되살아나면 AI 결과 캐시(DB)와 모든 구성원 화면에 그대로 들어간다. 연락처는 필요하면 사용자가 채팅 원문에서 본다.

## 사용법

```python
from app.shared.privacy import ANALYSIS, prepare_transcript, restore_json

rows = [(msg.id, speaker_name, msg.text) for msg, speaker_name in db_rows]   # DB 모델에 의존하지 않는다
with prepare_transcript(rows, member_names, ANALYSIS) as prep:
    for line in prep.lines:            # line.id, line.speaker(토큰), line.text(가명화됨), line.blocked
        ...                            # 이것만 LLM 프롬프트에 넣는다
    llm_result = call_llm(prep.lines)  # dict (구조화 출력)
    restored = restore_json(prep, llm_result)
    data, unknown = restored.value, restored.unknown_tokens
# with 블록이 끝나면(예외 포함) 대응표 참조가 지워진다
```

- `prep.blocked_ids`, `prep.blocked_count`, `prep.counts_by_kind` (예: `{"PHONE": 2, "SECRET": 1}`)는 사용량·화면 안내용이다. 값은 담지 않는다.
- `restore_json` 결과: `.value`(복원된 JSON), `.restored_tokens`, `.generalized_tokens`(정책상 복원하지 않고 `(연락처)` 로 바꾼 것), `.unknown_tokens`(이 요청이 만들지 않은 토큰 모양). `generalize_unknown=True` 를 주면 unknown 자리를 `(알 수 없는 항목)` 으로 바꾼다(기본은 그대로 두고 호출부가 결정).
- `prepare_transcript` 의 `member_names` 원소는 이름 문자열이거나 **같은 사람의 표기 묶음** `(실제 이름, 표시 이름, ...)` 이다(첫 번째가 대표). 묶음의 어느 표기로 불러도 발화자(실제 이름)와 같은 `[PERSON_n]` 이 되고 복원하면 대표 이름이 나온다. 가족 채팅 AI 는 구성원마다 `(User.name, display_name)` 을 넘긴다.
- `restore_json(..., scrub=True)` 는 복원 뒤에도 남은 무력화 토큰(`‹PERSON_2›`, 사용자가 대화에 직접 쓴 토큰 모양)을 `(알 수 없는 항목)` 으로, 복원 불가 고정 토큰(`[RRN]`·`[CARD]`·`[ACCOUNT]`·`[SECRET]`)을 `(민감 정보)` 로 바꾼다(`scrub_leftovers`). 가족 채팅 AI 는 이 옵션을 켠다.
- 낱개 글자는 `Pseudonymizer().apply(text, policy, known_names)` -> `MaskResult(text, counts_by_kind, blocked)`, `restore(text, kinds=None, generalize_unknown=False)` -> `RestoreResult`.

## 실제 연결 방식 (가족 채팅 AI, 구현됨)

- 서버가 DB 에서 읽은 줄 `(id, 발화자 이름, 글자)` 와 그 가족 구성원의 실제 이름·표시 이름(`ai_repository.member_names`)으로 `prepare_transcript` 를 부른다. 글자 수 한도(`AI_ANALYSIS_MAX_CHARS`)는 **가명화된 줄 기준**이고, 오래된 메시지를 뺀 뒤에는 남은 메시지만으로 다시 가명화해 대응표와 개수가 보내는 줄과 맞게 한다.
- 호출 단위 정책: 분석 `ANALYSIS`(최대 200줄), 답장 `REPLY`(15줄), 주제 `TOPICS`(30줄). `max_context_lines` 는 쓰지 않고 호출부가 줄 수를 정한다.
- **캐시에는 토큰 상태의 결과를 저장**한다(이 문서 아래 4번의 '복원된 값을 저장하지 않는다'를 그대로 따른다). 응답 직전에 같은 범위를 다시 `prepare_transcript` 해(결정적: 같은 입력이면 같은 토큰 번호) `restore_json(prep, 결과, generalize_unknown=True)` 로 복원한다. 캐시 키에는 프롬프트 버전, `MODULE_VERSION`(`app/shared/privacy/__init__.py`), 정책 이름·`block_min_score`·`restore_kinds`, 가명화된 줄의 해시가 들어간다. 규칙을 바꾸면 `MODULE_VERSION` 을 올린다.
- 순서: 아래 1번(복원 먼저 후 검증)과 달리 **검증(`clean_analysis`)을 토큰 상태에서 먼저** 하고 캐시에 저장한 뒤 복원한다. 담당자 검증은 '대화에 나온 `[PERSON_n]` 토큰 또는 가명화하지 않은 발화자(엄마·아빠)'인지로 하고, 복원된 이름은 응답에만 들어간다. 이 요청이 만들지 않은 토큰(unknown)은 일정·할 일 후보에서 해당 후보를 버리고, 나머지 문장은 `(알 수 없는 항목)` 으로 바꾼다.
- 차단된 메시지의 id 는 `important_messages`·`source_message_ids` 에서 뺀다. 응답 `meta.privacy = {masked: {종류: 개수}, blocked_messages: 개수}` 에 개수만 담는다(사용 기록 `ai_usage_logs` 에는 컬럼이 없어 남기지 않는다).
- `POST /family-chat/ai/preview` 는 같은 `prepare_transcript(ANALYSIS)` 결과의 줄을 그대로 보여 준다. AI 를 부르지 않는다.
- 차단 조건: 차단되지 않은 메시지가 3개 미만이면(전부 차단된 대화 포함) 분석·답장·주제는 AI 를 부르거나 한도를 쓰지 않고 400 `too_few_messages` 이다. 미리보기는 `sendable` 로 알린다. 차단된 줄은 시각도 보내지 않는다(빈 문자열).
- 알려진 한계: 이름 사전은 구성원의 이름·표시 이름뿐이다(개인별 별명 `member_nicknames` 는 보는 사람마다 달라 쓰지 않는다). 가명화 후에도 가족 호칭·문맥으로 사람을 추측할 수 있다.

## 통합 가이드 (`ai_service.py` 에 연결할 때)

1. **순서**: 가족 채팅 AI 는 `clean_analysis` 를 **토큰 상태로 먼저** 하고(담당자는 '대화에 나온 `[PERSON_n]` 토큰'인지, 날짜·id 검증), 그 결과를 캐시에 토큰 상태로 저장한 뒤, 사용자에게 돌려줄 때 `restore_json` 으로 복원한다. 복원된 값은 캐시에 들어가지 않는다. 복원 뒤에는 담당자 이름이 그 가족 구성원의 이름·표시 이름과 일치하는지 한 번 더 본다(아니면 담당자만 비움). 호출부가 복원된 값 기준으로 검증하려면 `restore_json` 을 먼저 부르면 되지만, 그러면 복원된 값을 저장하지 않도록 따로 신경 써야 한다. 별칭("민수")은 대표 이름("김민수")으로 복원된다.
2. **프롬프트**: 시스템 프롬프트를 바꿔야 한다. "토큰(`[PERSON_1]`, `[ADDR_1]` 등)은 글자 그대로 복사하고 바꾸거나 새로 만들지 않는다. 전화번호·이메일 토큰은 응답에 쓰지 않는다"를 넣고, 기존 "사람 이름은 대화에 나온 이름 그대로" 문구를 토큰 기준으로 고친다. 토큰이 깨지면 복원되지 않는다. `PROMPT_VERSION` 도 올린다.
3. **글자 수 자르기**: `max_chars` 한도는 **가명화 후 토큰화된 줄 기준**으로 자르는 것을 권장한다(실제로 외부에 나가는 길이). 오래된 메시지부터 빼는 규칙은 그대로 둔다. 가명화 전에 자르면 한도를 잘못 센다.
4. **캐시**: `ai_result_cache.result` 에 **복원된 값을 저장하지 않는다**. 복원은 응답 직전에 요청 메모리에서만 하고, 캐시에는 복원 범위 정책을 적용한 결과(전화·이메일은 이미 `(연락처)` 로 일반화됨)만 넣는다. 이름·주소가 들어가는 일정/할 일 후보를 캐시에 둘지는 별도로 결정해야 한다(감사 M3). 캐시 키에는 정책 이름·`block_min_score` 가 영향을 주므로 `PROMPT_VERSION` 으로 구분한다.
5. **차단 메시지**: `prep.blocked_ids` 의 메시지는 AI 가 보지 못한다. `source_message_ids`·`important_messages` 에 그 id 가 들어오면 버릴지 정한다. 화면에 "민감정보가 있어 N개 메시지는 제외했어요"를 안내할 수 있다(`blocked_count`).
6. **`restore_json` 의 범위**: dict 의 **값과 키**, list·tuple·set 의 원소 안 문자열을 복원한다. 문자열이 아닌 값은 건드리지 않는다. 사용자 정의 객체(Pydantic 모델 등)는 `model_dump()` 한 dict 로 넘긴다. 문자열 안에서 토큰이 쪼개져 있으면(`[PERSON_` + `1]`) 복원하지 못한다.
7. **로그**: 모듈은 `logging` 을 쓰지 않는다. 호출부도 `prep`·`MaskResult`·복원 전 응답을 로그에 찍지 않는다(`counts_by_kind` 만 사용량 기록용으로 안전).
8. **두 군데로 갈라진 마스킹 규칙**: `app/features/ai_assistant/ingest/masking.py`(`mask_text`)가 문서 저장용으로 따로 정규식 마스킹을 한다. 이 모듈과 규칙(전화·카드·주민번호·계좌·이메일·주소·라벨 이름)이 겹치지만 목적이 다르다(저장 시 영구 치환 vs 요청 시 가역 가명화). 통합 계획만 적는다: (a) 당장은 코드를 합치지 않고, (b) 중복되는 탐지 규칙(`detect`)을 `masking.mask_text` 가 재사용하도록 다음 단계에서 정리하며, (c) AI 어시스턴트 질문(`/ai-assistant/chat`)에도 같은 `ANALYSIS`/별도 정책을 적용할지는 요구사항 확인 후 정한다. 이번에는 기존 코드를 수정하지 않았다.
9. **성능**: 200줄×2,000자는 1초 안팎이라 요청 경로에서 동기로 돌려도 된다. 반복 입력 같은 최악 조건도 10만 자에 0.1~0.2초 이하다(선형).

## 약속(코드로 지킨 것, 시험이 있다)

- 대응표(원본 <-> 토큰)는 `Pseudonymizer` 인스턴스의 메모리에만 있다. 이 모듈은 `logging` 을 쓰지 않는다. DB·캐시·응답에 넣지 않는다.
- 같은 원본 값은 같은 토큰, 번호는 등장 순서. 전화번호는 숫자만 비교해 표기가 달라도 같은 토큰이다. 이름 사전의 별칭("민수" -> "김민수")은 같은 토큰이고 복원하면 대표 이름이 나온다.
- 복원은 **이 요청이 만든 토큰만** 한다. `[PHONE_9]`, `[phone_1]`, `[PHONE_ 1]`, `[PHONE_01]`, 전각 괄호 `【PHONE_1】` 같은 지어내거나 변형된 토큰은 그대로 두고 `unknown_tokens` 에 적는다. 사용자가 대화에 직접 쓴 토큰 모양(변형 포함)과 대응표에 넣는 값(발화자 이름 등)이 토큰 모양이면 `‹PHONE_1›` 로 바꿔 복원 대상이 되지 않게 한다(이중 복원 방지).
- BLOCK 대상 값(SECRET·RRN·CARD·ACCOUNT)은 대응표에 넣지 않는다(복원 불가). 정책이 MASK 여도 번호 없는 `[SECRET]` 같은 고정 토큰으로만 바꾼다.
- `repr`/`str` 은 값을 보이지 않고(`Span.canonical` 도 repr 에서 제외), `pickle`·`copy` 는 `TypeError`. `clear()` 와 `__exit__` 는 참조를 지운다(파이썬 객체 참조 정리이며 메모리에서 물리적으로 완전히 지워진다고 보장하지 않는다). 단 `Pseudonymizer` 내부 필드(`vars`/슬롯)를 코드가 직접 읽는 것까지 막지는 못한다.
- 토큰 복원·탐지 정규식은 입력 길이에 선형이다(길이 제한 후보 + 코드 검사, 반복 입력 시험 포함).

## 한계

- 한국어 이름·주소 탐지는 불완전하다(사전에 없는 이름, 호칭 없는 이름, 붙여 쓴 주소 미탐 가능). 가족 호칭(엄마·아빠)은 마스킹하지 않는다.
- 한글 숫자·띄어쓰기 오타 전화번호, 공백 구분 계좌, 키워드 없는 비밀번호, 건강·종교 같은 의미 기반 민감정보는 찾지 못한다. 전각 숫자·대시 변형은 찾는다.
- 차단은 메시지 단위라 요약 품질이 떨어질 수 있다. 이름 토큰화로 AI 가 관계 추론을 잃을 수 있다. 전화·이메일은 응답에서 일반화되어 요약에 구체 값이 나오지 않는다.
- 토큰 모양이 응답에서 깨지면 복원되지 않는다. 호출부는 `unknown_tokens` 가 있으면 해당 값을 쓰지 않거나 일반화해야 한다.
- 차단된 메시지도 **발화자 토큰은 Claude 로 간다**(시각은 비운다). 누가 민감 정보를 보냈는지의 패턴(차단 줄이 몇 번, 누구에게서)은 전달된다. 설계상 허용했다.
- 이름 + 공백 1칸 + 호칭('홍길동 선생님', '김철수 씨', '박영희 님께')은 이제 찾는다. 공백이 있는 '군'·'양'은 일반 문장과 구분되지 않아 제외하고, '사용자 님'·'모두 님'·'정대표 님' 같은 역할·직함 말(끝이 '자', 직함 불용어)은 거른다. 그 밖의 일반어가 성씨로 시작하면 오탐할 수 있다.
- 법적 판단(국외 이전·동의 등)은 이 모듈의 범위가 아니다.
