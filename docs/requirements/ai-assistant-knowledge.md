# 기능: AI 비서 최적화 (데이터화 + 벡터 DB)

브랜치: `ai_assistant-knowledge`
범위: 서버 `apps/api/app/features/ai_assistant/knowledge/`
상태: **저장·검색 뼈대 구현됨(가짜 기록으로 테스트). 전처리 연결, 실제 모델, pgvector 전환은 남아 있다.**

## 목적
채팅 LLM 이 "이번 주 공과금 알려줘", "엄마 처방전 어디 있어?" 같은 질문에 맞는 가족 기록을 찾아 근거로 쓰게 한다.
기록을 임베딩해 저장하고, 질문과 가까운 기록을 출처(원본 경로, 쪽 번호)와 함께 돌려준다.

## 확정된 전제
- 전처리(`ai_assistant-ingest`)가 맡는 일: OCR, 용량 제한, 원본 저장(서버 PC), 개인정보 마스킹, PDF/PPT → 글 변환(쪽·슬라이드 번호 포함, 긴 건 잘라서), 자동 분류(마크다운).
- 문서는 **마크다운 글**로 온다. 글자 없는 사진은 분류 이름과 저장 경로만 온다(설명글 없음).
- 읽기 실패 부분은 "읽지 못한 부분"으로 표시되어 온다(형식은 협의 전, 지금은 `[읽지 못한 부분]`으로 가정).
- 중복 처리와 삭제 기능은 이번 범위에서 제외한다.
- 벡터 저장소는 서버 PC 의 PostgreSQL + pgvector. 임베딩과 검색은 외부 AI 없이 서버 PC 에서 돈다.
- 저장·검색은 이 브랜치 코드가 하고, LLM 은 이 코드의 함수를 부른다.

## 이번 범위
- 마크다운 기록 저장: 제목·`분류:` 줄은 모든 조각 앞에 붙이고, `[p.N]` 쪽 표시와 `## ` 제목(슬라이드)으로 나눠 조각내고, 길면 줄 단위로 더 자른다.
- 조각마다 임베딩해서 저장하고, 검색은 조각 단위로 한 뒤 **기록 단위**로 묶어 돌려준다.
- 필터: 가족 그룹(항상), 분류 이름, 기간, 민감 기록 제외.
- LLM 이 부르는 함수 3개: `search_knowledge`, `get_item`, `list_items`(정의는 `tools.py` 의 `TOOL_SPECS`).
- 가짜 기록 시드(`seed.py`)로 전처리 없이 검색·채팅을 시험한다.

## 하지 않는 것 (지금)
- 글자 없는 사진을 내용으로 찾는 사진 모델. 설명글을 받을지 사진 모델을 쓸지는 전처리 쪽 계획과 서버 사양이 정해진 뒤 결정한다.
- 얼굴 인식. 사진 위치(EXIF) 저장.
- 삭제, 중복 처리, 원본 파일 저장·마스킹·OCR(전처리 몫).

## API
모든 경로는 토큰이 필요하고 가족 그룹이 다르면 보이지 않는다. 에러는 `{code, message}`.

| 경로 | 설명 |
|---|---|
| `POST /ai-assistant/knowledge/items` | 기록 한 건 저장(`kind_label`, `title`, `body_md`, `source_path`, `occurred_on`, `sensitivity`) |
| `GET /ai-assistant/knowledge/items` | 기록 목록(분류 이름 필터) |
| `GET /ai-assistant/knowledge/items/{id}` | 기록 상세(마크다운 전체) |
| `POST /ai-assistant/knowledge/search` | 질문으로 찾기(`query`, `top_k`, `kind_label`, `date_from/to`, `include_sensitive`) |
| `POST /ai-assistant/knowledge/ask` | 시험용 채팅: LLM 이 검색 함수를 불러 기록을 근거로 답(키가 없으면 검색 결과만) |

시험 도구(로컬 SQLite 만 사용, 팀 DB 에는 접속하지 않는다): `python -m app.features.ai_assistant.knowledge.dev_chat "질문"`(터미널),
`uvicorn app.features.ai_assistant.knowledge.dev_app:app --port 8001`(라우터까지 붙인 서버, `/docs` 에서 시험).
LLM 키는 `apps/api/.env` 의 `ANTHROPIC_API_KEY`.

## 데이터
- `knowledge_items`: 그룹, 올린 사람, 분류 이름, 제목, 마크다운 전체, 원본 경로, 기록 날짜, 읽지 못한 부분 여부, 민감도.
- `knowledge_chunks`: 기록, 순서, 쪽/슬라이드 이름, 조각 글, 벡터, 벡터를 만든 모델 이름.
- 모델을 바꾸면 이전 벡터는 검색 후보에서 빠지고 `reindex` 로 다시 만든다.
- 민감도: 전처리가 주면 그 값, 없으면 분류 이름(가족관계·주민등록·여권·병원·처방 등)으로 정한다.

## 모델 (측정 결과)
- 글 임베딩: multilingual-e5-small 을 전처리 출력 모양의 가짜 기록으로 파인튜닝. 학습에 없는 기록 3위 안 98.9%, 처음 보는 종류 95.2%, 사람이 쓴 질문 98.0%(원본 80.4% / 82.2% / 91.8%).
- 이 점수는 가짜 데이터 기준이다. 실제 전처리 출력이 오면 다시 잰다.
- 사진 검색: 영어 CLIP 파인튜닝은 사진 100장 안팎·영어 질문에서만 95% 이상. 한국어 직접 검색은 미달. 지금은 만들지 않는다.

## 완료 조건 (이번 범위)
- [x] 기록 저장, 조각내기, 임베딩, 검색, 필터, 가족 그룹 격리(테스트로 확인)
- [x] LLM 함수 3개와 시드 기록으로 전처리 없이 시험
- [x] 파인튜닝 모델을 서버용(ONNX int8, 118MB)으로 바꾸고 점수 재측정(3위 안 97.9% / 96.6% / 100%). 모델 파일은 저장소에 넣지 않고 서버 PC 의 EMBED_MODEL_DIR 에 둔다.
- [x] **Alembic 리비전**(c3a9f21d7e54)으로 knowledge_items·knowledge_chunks(벡터는 pgvector Vector(384)) 추가하고 lembic/env.py 가 모델을 알도록 import_all_models() 에 knowledge 등록. 공용 DB(gabee)에는 담당자가 gabee_migrator 로 승인 후 적용. 로컬에서는 SQL 생성(lembic upgrade 6304cb91e46a:head --sql)까지 확인했고, 실제 PostgreSQL 실행 확인(PGVECTOR_TEST_DATABASE_URL 통합 테스트)은 도커가 있는 곳에서 한다.
- [ ] 전처리와 입력 방식 합의 및 연결
- [x] 채팅(`POST /ai-assistant/chat`)이 가족 그룹의 기록을 검색해서 답하고, 답에 쓴 기록을 `sources: [{n, title, item_id, source_path}]` 로 돌려준다(그룹이 없으면 기록 없이 답). 앱 출처 칩 연결(`api.js`)은 남아 있다.

## 협의·미정
1. 전처리가 knowledge 로 넘기는 방식(함수 호출 / HTTP / DB 테이블 공유)과 필드, 새 기록 알림 방식.
2. 긴 문서를 전처리가 이미 자르는지, 여기서 자르는지.
3. "읽지 못한 부분" 표시의 실제 형식.
4. 서버 VM 사양(사진 모델 크기 결정에 필요).
5. 의존성 추가(`pgvector`, `onnxruntime`, `tokenizers`, `numpy`)와 `ai_assistant/router.py` 연결, 개발용 DB 이미지(pgvector 포함) — 승인 대기.
