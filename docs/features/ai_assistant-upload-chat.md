# 구현 현황: AI 비서 파일 올리기 → 읽기 → 기록 → 채팅 (통합)

- 상태: 진행 중 (통합 완료, 공용 PostgreSQL 에서의 실제 시험은 아직)
- 담당: knowledge(임베딩·벡터 저장·채팅) + 앱 통합. 전처리(ingest)는 별도 담당자 작업을 합쳤다.
- 요구사항: docs/requirements/ai_assistant-ingest.md
- 결정 기록: [docs/adr/0010-upload-ingest-chat-integration.md](../adr/0010-upload-ingest-chat-integration.md) (이유와 한계가 자세히 있다)

## 한눈에 보기

가족이 채팅 `+` 버튼으로 **사진·PDF·워드·엑셀·PPT**를 올리면,

1. 서버가 **원본을 그대로** 원본 폴더(`RAW_DIR`)에 보관하고,
2. 글자를 읽어(OCR, 문서 변환) **개인정보를 가린 글**만 기록(knowledge)에 저장하고(벡터 DB),
3. 글자 없는 사진은 **로컬 이미지 모델**이 설명글을 붙이고,
4. 채팅으로 물으면 가려진 기록을 근거로 Claude 가 답하고, 답 아래 **출처 → 원본 보기**로 원본을 볼 수 있다.

```
앱 + → POST /ai-assistant/files (바로 received 응답)
        └ 뒤에서: 원본 보관 → OCR/문서 읽기 → 개인정보 가리기 → 분류(로컬 모델) → 사진 설명(로컬 모델)
                  → knowledge 저장(조각 + 임베딩) → 상태 analyzed / needs_review / failed
앱 채팅 → POST /ai-assistant/chat → (가족 AI 동의·쿨다운·하루 한도: ai_guard) → Claude 가 search_knowledge 도구로 기록 검색 → 답 + 출처
```

원본 사진·파일과 가리기 전 글자는 **서버 밖으로 나가지 않는다.** 외부(Claude)로는 **가린 글자**만 간다.

## 구현된 것

- 업로드/상태/원본/수정/삭제 API (`/ai-assistant/files*`, `/ai-assistant/knowledge/items*`), OpenAPI 는 `docs/contracts/openapi.json`
- 앱: `+` 올리기 시트(앨범·카메라·파일), 읽는 중 애니메이션과 걸린 시간, 확인이 필요하면 안내 문장과 "기록에서 확인하기" 버튼(2026-11-09, 흐린 줄 카드는 어느 글자인지 보여 줄 수 없어 뺐다), 기록 상세의 읽어 낸 내용은 접어 두고 "자세히 보기"로 펼침, 사이드바(대화 목록·기록 탭), 기록 상세(읽어 낸 글 보기·고치기·확인 완료·지우기), 원본 보기(사진, PDF 는 서버가 쪽별 그림으로 제공)
- 개인정보 가리기 확대(일반 문서도 카드·전화·이메일·계좌·라벨 있는 이름·주소), 민감 기록은 가린 상태로 채팅 근거에 사용(`CHAT_INCLUDE_SENSITIVE`)
- 스캔 PDF 는 글자 없는 쪽만 OCR, 같은 파일은 출처 하나로 합침
- 글자 없는 사진은 사용자가 한 줄 설명을 직접 단다(채팅 카드, 기록 상세에서 나중에도 가능). 문서 종류는 로컬 분류기(앱 임베딩 + 글자 TF-IDF)가 정하고 애매하면 Jev 또는 "확인 필요". qwen·Ollama 는 쓰지 않는다
- 임베딩 재색인(2026-11-10, T12 PR-1): `knowledge.service.reindex` 가 배치·진행률·이어하기를 지원하고, 점검·재계산 스크립트 `apps/api/scripts/reindex_embeddings.py`(`--check` 기본, `--apply --yes`)를 추가했다. 모델 폴더 이름이 바뀌어 옛 조각이 검색에서 빠지는 경우의 조치다("임베딩 모델 전달" 아래 절). 마이그레이션·API 변경 없음. 격리 PostgreSQL(pgvector 컨테이너)에서 `test_knowledge_pgvector.py` 의 재색인 시험(`vector_dims`=384, 모델 이름 갱신, 검색, 스크립트 `--check`·`--apply --yes --limit`)을 통과했다. 아직 없는 것: 시작 시 경고 로그·운영자 조회 API(PR-2), tokenizer 누락 처리(PR-3)
- 테스트: 서버 462개 통과(병합 후), 앱 린트·Android 번들 빌드 통과

## 남은 것

- 팀 공용 PostgreSQL(192.168.0.44)에서의 확인. **개인 로컬 Docker PostgreSQL(pgvector/pgvector:pg16)에서는 확인 완료**: 마이그레이션 head 적용, 스키마 일치, `vector(384)`·HNSW 인덱스, `pytest -k pgvector` 2개 통과, 시험 파일 34개를 올려 기록 30건·조각 35건 저장(벡터 길이 384, 모델 `onnx-e5-small-ft`), 검색은 HNSW 인덱스를 탐
- 워드·엑셀·PPT 안에 붙은 이미지, PDF 쪽 안의 그림 속 글자는 아직 읽지 않음
- 라벨 없는 이름과 동·호가 없는 주소는 가려지지 않는다(라벨이 붙은 번호·이름·주소·계좌는 2026-10-26 에 보강해 시험 파일 40개 값이 모두 가려짐). 워드/엑셀/PPT 원본은 앱에서 열 수 없음
- 기록은 **가족 그룹 단위로 공유**(누구나 보고 고치고 지울 수 있음), 수정·삭제 이력 없음
- 대화 목록은 **이 폰에만** 저장(서버 저장 안 함)

## 브랜치와 PR

- 저장소: `https://github.com/kangminhun/gabee.git`
- 브랜치: `ai_assistant-knowledge` (2026-10-23 기준 최신 `origin/main` 까지 병합함. 병합 충돌 3곳은 풀어 두었다)
- 변경 규모: main 대비 28커밋, 61파일, +7,178 / -150줄 → 팀 권장(400줄 이하)을 크게 넘는다. 리뷰어와 나눠 올릴지 정한다.
- DB: 이 브랜치에 **새 마이그레이션은 없다.** `c3a9f21d7e54`(knowledge 테이블)는 이미 main 에 있다. Alembic head 는 1개.
- API 형식이 바뀐 곳(앱도 같이 바꿈): `GET /ai-assistant/knowledge/items` 응답에 `needs_review` 추가, `GET /ai-assistant/files/{id}` 응답에 `doubts` 추가. 기존 필드는 그대로라 하위 호환이다.
- 2026-10-26 추가(브랜치 `feature/kang-user-description-classifier`): `POST /ai-assistant/files/{id}/description`(사진 설명 저장, 사진이 아니면 409, 다른 가족·없음은 404, 1~200자 밖은 422)과 파일 상태·기록 목록·상세 응답의 `needs_description`. 추가만 있어서 하위 호환이다. qwen 자동 설명과 로컬 언어 모델 분류는 없앴다.

## 팀원이 받아 가야 할 것 (깃에 없는 것)

`.env` 한 파일만으로는 부족하다. 아래 4가지가 필요하다.

| 무엇 | 왜 | 어떻게 |
| --- | --- | --- |
| **임베딩 모델 파일 2개** | 없으면 기본 임베더(해시)로 돌아가서 검색 품질이 크게 떨어지고, PostgreSQL 에서는 503 `embedding_model_missing` | 아래 "임베딩 모델 전달" |
| **`.env` 비밀 값** | Claude 키, DB 주소 등 | 깃·단체방 대신 안전한 방법으로 각자에게 전달. `.env.example` 에 항목 이름이 있다 |
| **문서 분류기 파일** | 문서 종류를 정한다. 없으면 분류기를 건너뛰고(Jev 키가 있으면 Jev, 없으면) "기타 문서 + 확인 필요"로 저장된다 | 아래 "문서 분류기 전달". Ollama·qwen 은 더 이상 쓰지 않는다 |
| **원본 보관 폴더** | 원본이 저장되는 곳 | `RAW_DIR` 폴더를 만들고 쓰기 권한·백업 계획을 정한다(없으면 서버가 `DATA_DIR/raw` 에 만든다) |

**얼굴 인식은 삭제했다.** 코드·테스트·설정(`FACE_MODEL_DIR`, `FACE_ENABLED`)을 모두 지웠으니 얼굴 모델을 받을 필요가 없다(생체정보라 가족 동의·삭제 연동이 정해지기 전에는 만들지 않는다).

### `.env` 에 새로 생긴 항목 (`apps/api/.env.example` 참고)

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `EMBED_MODEL_DIR` | `<DATA_DIR>/models/e5-small-ft` | 임베딩 모델 폴더 |
| `RAW_DIR` | (비움 → `DATA_DIR/raw`) | 원본 보관 폴더 |
| `DOC_CLASSIFIER_DIR` | `<DATA_DIR>/models/doc-classifier` | 문서 분류기 폴더(`.env.example` 에는 없고 환경변수로만 쓴다) |
| `CHAT_INCLUDE_SENSITIVE` | `true` | 가린 민감 기록(처방전·신분증 등)을 Claude 근거에 넣을지. `false` 면 채팅 검색·`get_item`·`list_items` 에서 제외. 서버 전체에 적용되는 값이고 가족·사용자별 설정이 아니다 |
| `TYPESAFE_API_KEY` | (비움) | 있으면 로컬 분류기가 확신하지 못한 문서만 외부 Jev 로 분류한다(가린 글만 보냄). 없으면 "기타 문서 + 확인 필요" |

**삭제된 설정**: `LOCAL_LLM_URL`·`LOCAL_LLM_MODEL`·`LOCAL_LLM_TIMEOUT`·`CAPTION_ENABLED`·`CAPTION_MODEL`·`CAPTION_TIMEOUT`·`OLLAMA_KEEP_ALIVE`. 예전 `.env` 에 남아 있어도 무시된다.
| `ANTHROPIC_API_KEY` | (비움) | 채팅 답변. 없으면 검색 결과만 보여 준다 |

공용 PostgreSQL 로 서버를 켜려면 `JWT_SECRET`(로그인 서명 키)도 필요하다. `.env.example` 의 로그인 항목을 따른다.

## 임베딩 모델 전달

**파일 (폴더 `e5-small-ft` 안에 2개)**

| 파일 | 크기 | SHA-256 |
| --- | --- | --- |
| `model.onnx` | 118,073,663 바이트 (약 113MB) | `5c63185a7d8990f09b97954574232a8d8f12d8e7277e8a97835b8c89f7e0085a` |
| `tokenizer.json` | 17,082,988 바이트 (약 16MB) | `fb02bfe42ffe0fe115de5c74f76c6480d730e60cc1f6ae567ff4d82cb305a113` |

- e5-small 계열을 가족 문서 검색에 맞게 파인튜닝해 ONNX(int8)로 낸 것. CPU 에서 질문 한 건 약 4ms.
- 원본 위치: 만든 사람 PC 의 `apps/api/data/models/e5-small-ft/` (`apps/api/data/` 는 `.gitignore` 라 깃에 올라가지 않는다).

**주는 방법 (택1)**

1. 폴더를 압축(`e5-small-ft.zip`, 약 130MB)해서 팀 공유 드라이브나 USB 로 전달 — 가장 간단하다.
2. 같은 네트워크면 `scp e5-small-ft.zip 사용자@서버PC:/경로/` 로 서버 PC 에 바로 복사.
3. 용량이 큰 파일을 깃에 올리는 것은 피한다(Git LFS 를 쓰기로 팀이 정했다면 그때 올린다).

**받은 사람이 하는 일**

1. 압축을 풀어 `model.onnx`, `tokenizer.json` 이 들어 있는 폴더를 만든다.
2. 기본 위치에 두거나(`apps/api/data/models/e5-small-ft/`), 다른 곳이면 `.env` 에 `EMBED_MODEL_DIR=그 폴더 경로` 를 쓴다.
3. 해시가 같은지 확인한다.
   - PowerShell: `Get-FileHash .\model.onnx -Algorithm SHA256`
   - bash: `sha256sum model.onnx`
4. 서버를 켜고 확인한다: 모델이 있으면 `model.onnx` 를 읽고, 없으면 해시 임베더로 조용히 대체된다. 파일을 올려 검색했을 때 "저장했어요"가 나오고 비슷한 말로 물어도 찾아지면 정상이다.

**서버 PC(공용 PostgreSQL)에서는 반드시 필요하다.** 벡터 칸이 384차원으로 고정이라 모델이 없으면 저장·검색이 503 으로 막힌다. 모델을 바꾸면 기존 기록은 다시 색인해야 한다(`knowledge.service.reindex`, 아래 "모델 폴더 이름이 바뀌면").

**폴더 이름은 `e5-small-ft` 로 유지한다.** 저장된 벡터의 모델 이름은 `onnx-<폴더 이름>` 이라, 폴더 이름만 바꿔도 다른 모델로 취급된다.

## 모델 폴더 이름이 바뀌면 (임베딩 재색인)

**증상**: 서버가 오류 없이 켜지는데 "문서는 있는데 @가비·채팅이 못 찾는다". 검색은 지금 모델 이름과 같은 조각만 쓰므로(`embedding_model` 일치), 모델 폴더 이름이나 모델을 바꾸면 PostgreSQL 에서 옛 조각이 의미 검색에서 조용히 빠진다(SQLite 도 같다).

### 안전한 순서 (이 순서를 지킨다)

1. **모델 폴더를 먼저 고친다**(`model.onnx`, `tokenizer.json`이 있는 폴더).
2. **서버를 재시작**해 서버가 새 폴더로 모델을 불러오게 한다.
3. **서버와 같은 `EMBED_MODEL_DIR`·`DATA_DIR` 로** `--check` 를 실행한다(아래 "실행 위치").
4. `--check` 의 "현재 설정의 모델 이름"이 **서버가 최근에 올린 조각의 모델 이름과 같을 때만** `--apply --yes` 를 실행한다. 서버가 최근에 쓴 이름은 DB 에서 확인한다(가장 최근 조각의 모델이 서버의 현재 이름이다).

   ```sql
   SELECT embedding_model, count(*), max(id) AS newest_chunk_id
   FROM knowledge_chunks GROUP BY embedding_model ORDER BY max(id) DESC;
   ```

   첫 줄(`newest_chunk_id` 가 가장 큰 모델)이 서버가 쓰는 이름이다. 서버 재시작 뒤 **이미 올린 적 없는 새 문서**를 하나 올려서 그 조각이 생긴 다음에 본다(같은 파일을 다시 올리면 새 조각이 생기지 않을 수 있다, 확인 필요).

**경고: 이름이 서버와 어긋난 채 `--apply` 하면 모든 조각이 서버가 검색하지 않는 이름으로 바뀌어, 오류 없이 의미 검색이 0건이 된다.** 스크립트는 `--apply` 실행 전에 "서버와 같은 설정에서 실행하는지 확인하세요" 경고를 한 줄 출력하지만, 서버가 쓰는 이름을 스크립트가 알 수는 없으므로 위 4번 확인은 사람이 한다. 이 경우 다시 맞추려면 서버 이름으로 `--apply` 를 한 번 더 해야 한다(본문은 그대로라 데이터가 사라지지는 않는다).

### 실행 위치

- `apps/api/Dockerfile` 은 `app`·`alembic` 만 복사하고 **`scripts/` 는 이미지에 들어 있지 않다.** 컨테이너 안에서는 이 스크립트를 돌릴 수 없고, 저장소를 받은 호스트의 `apps/api` 에서 돌린다.
- 서버 이미지는 `EMBED_MODEL_DIR=/srv/data/models/e5-small-ft`, compose 는 `DATA_DIR=/data` 로 설정한다. **호스트의 값은 이와 다를 수 있다.** 호스트에서 돌릴 때 `DATABASE_URL`(점검할 DB)과 `EMBED_MODEL_DIR`·`DATA_DIR`(서버가 쓰는 모델 폴더와 같은 폴더·같은 이름)을 서버와 맞춘다. 폴더 **이름**이 모델 이름(`onnx-<폴더 이름>`)을 정하므로 이름이 다르면 안 된다.
- 운영 서버를 Docker 로 띄우는지 직접 실행하는지는 **담당자 확인 필요**. 어느 쪽이든 위 순서와 이름 확인은 같다.

### 1. 점검(읽기 전용) — `apps/api` 에서

```bash
python -m scripts.reindex_embeddings            # --check 와 같다
```

모델별 조각 수, 현재 설정의 모델 이름, 현재 모델과 다른 조각 수, 영향받는 기록 수, 의미 검색에서 완전히 빠진 기록 수를 **개수만** 보여 준다(본문·id 는 찍지 않는다). 모델을 불러오지 않고 폴더만 보므로 모델 폴더가 깨져 있어도 점검은 된다. PostgreSQL 인데 이름이 `hashing-512` 면(모델 폴더를 찾지 못함) "모델 폴더를 찾지 못했어요" 경고를 한 줄 더 보여 준다(데이터는 바뀌지 않는다). 스크립트는 `DATABASE_URL` 이 가리키는 DB 를 쓰므로 어느 DB 인지 첫 줄에서 확인한다.

### 2. 조치 — 위 안전 순서의 4번까지 확인한 뒤

```bash
python -m scripts.reindex_embeddings --apply --yes --batch-size 128
```

`--yes` 가 없으면 개수만 보여 주고 다시 만들 조각이 있을 때 종료 코드 2 로 끝난다(없으면 0, 모델도 불러오지 않는다). 배치마다 commit 하고 `reindex 128/1,340 (9%)` 처럼 진행률을 찍는다. 중간에 멈추거나 실패해도 끝난 배치는 남고, 다시 실행하면 남은 조각만 한다. ONNX 모델을 불러오지 못해 해시 임베더인 상태에서는 거부한다. `--group-id`(한 가족만), `--limit`(시험용)도 있다.

**공용 DB 는 DB 담당자만** 실행한다(먼저 `--check`). Claude Code·개발자는 공용 DB 에 실행하지 않는다.

**이름만 바뀌고 가중치가 같을 때**: `model.onnx` 의 SHA-256 이 위 표의 `5c63185a7d8990f09b97954574232a8d8f12d8e7277e8a97835b8c89f7e0085a` 와 같다면 다시 계산하지 않고 `embedding_model` 값만 새 이름으로 바꾸는 `UPDATE` 한 줄로도 옮길 수 있다. 이것은 공용 DB 데이터를 직접 바꾸는 일이라 **DB 담당자의 승인이 필요**하고, 해시 확인 없이는 하지 않는다(이 문서가 그 SQL 을 정해 두지 않는다).

## 문서 분류기 전달

문서 종류를 정하는 작은 분류기다(앱 임베딩 e5-small + 글자 TF-IDF → 로지스틱, 종류 52개, 폴더 약 7MB). qwen 을 대신한다.

| 파일(폴더 `doc-classifier` 안) | 설명 |
| --- | --- |
| `classes.json` `coef.npy` `intercept.npy` `vocab.json` `idf.npy` `config.json` | numpy 만으로 읽는다(scikit-learn 불필요). 확률이 0.7 이상이면 확정 |

- 압축본: `doc-classifier.zip`(4,823,602바이트, SHA-256 `A3BB41B506657B79BF8EA157804762D727DD1BC9B59815A43736F71C89FFA82A`). 풀어서 `apps/api/data/models/doc-classifier/` 에 둔다(다른 곳이면 `DOC_CLASSIFIER_DIR`). `apps/api/data/` 는 `.gitignore` 라 깃에 올라가지 않는다.
- 없거나 깨져도 서버는 죽지 않는다. 분류기를 건너뛰고 Jev(키가 있을 때) → "기타 문서 + 확인 필요" 순서로 간다.
- 다시 학습하려면 `apps/api/scripts/train_doc_classifier.py`(개발용, scikit-learn 필요, 프로젝트 의존성에는 넣지 않았다)를 쓴다. 학습 데이터는 저장소에 없고 `--data` 로 넘긴다.
- 한계: 새로 직접 쓴 독립 문서 30개에서 28개(93%)를 맞혔지만 작은 시험이라 실제 사용 점수는 아니다. 처음 보는 종류와 학습 글과 다른 모양은 "확인 필요"가 된다. 새 종류가 생기면 예시를 모아 다시 학습해야 한다(자료와 방법: ADR 0010 "정정과 개선"). 기존 qwen 이 만들던 장소·중요 칸(`fields`) 추출은 사라졌다(날짜·금액은 그대로 규칙이 한다).

## 받아서 테스트하는 방법

### 0. 준비

```bash
git fetch origin
git checkout ai_assistant-knowledge
cd apps/api && pip install -e ".[dev]"      # 새 의존성(pypdfium2, rapidocr 등) 설치
cd ../mobile && npm install                  # image-picker, document-picker, async-storage 추가됨
```

### 1. 자동 테스트 (모델·인터넷 없이 돈다)

```bash
cd apps/api
ruff check . && ruff format --check .
pytest -q                                    # 462개 통과, 일부는 건너뜀(PostgreSQL 전용)
cd ../mobile && npm run lint
```

업로드 → 가리기 → 저장 → 검색 → 채팅 → 원본/수정/삭제 흐름은 가짜 OCR·가짜 모델로 `app/features/ai_assistant/tests/test_files_flow.py` 에서 검사한다.

### 2. 내 PC 에서 직접 써 보기 (로컬 SQLite, 팀 DB 를 건드리지 않음)

서버:

```bash
cd apps/api
# (선택) 임베딩 모델·분류기를 기본 위치가 아닌 곳에 두었다면 환경변수로 지정
#   PowerShell: $env:EMBED_MODEL_DIR="C:\경로\e5-small-ft"; $env:DOC_CLASSIFIER_DIR="C:\경로\doc-classifier"
#   bash:       export EMBED_MODEL_DIR=/경로/e5-small-ft DOC_CLASSIFIER_DIR=/경로/doc-classifier
uvicorn app.features.ai_assistant.knowledge.dev_app:app --host 0.0.0.0 --port 8001
```

`dev_app` 은 `apps/api/data/knowledge_dev.db`(로컬 SQLite)만 쓴다. 폰에서 붙으려면 `--host 0.0.0.0` 이 필요하다.

시험용 사용자·가족 만들기와 토큰 받기 (개발용 익명 계정):

```bash
curl -s -X POST http://127.0.0.1:8001/family-group/users -H "Content-Type: application/json" -d '{"name":"시험","role":"child"}'
# 응답의 token 을 TOKEN 으로 쓴다
curl -s -X POST http://127.0.0.1:8001/family-group/groups -H "X-Gyeot-Token: TOKEN" -H "Content-Type: application/json" -d '{"name":"시험 가족"}'
```

앱:

```bash
cd apps/mobile
# 폰에서 붙을 서버 주소(PC 의 LAN IP)와 방금 받은 토큰
#   PowerShell: $env:EXPO_PUBLIC_API_URL="http://192.168.0.xx:8001"; $env:EXPO_PUBLIC_DEV_TOKEN="TOKEN"
#   bash:       export EXPO_PUBLIC_API_URL=http://192.168.0.xx:8001 EXPO_PUBLIC_DEV_TOKEN=TOKEN
npx expo start --lan
```

폰은 같은 와이파이에서 Expo Go 로 QR 을 스캔한다. 로그인 화면이 있는 최신 앱에서는 정식 계정으로 로그인하는 방법도 있다(개발용 토큰은 로그인 세션이 없을 때만 쓰인다).

### 3. 앱에서 확인할 순서

1. `+` → 앨범에서 영수증 사진 → "읽는 중(통통 튀는 가비, 지난 시간)" → "저장했어요 (걸린 시간 N초)".
2. 글이 흐리면 채팅에 안내 문장과 **기록에서 확인하기** 버튼이 뜬다 → 기록에서 원본과 비교해 고친다.
3. 채팅에 "방금 올린 영수증 합계 얼마야?" → 답과 출처 → **원본 보기**.
4. 글자 없는 풍경·동물 사진을 올리면 채팅에 "이 사진은 어떤 사진인가요?" 카드가 뜬다 → 한 줄 설명을 쓰고 저장(또는 "나중에 할게요") → 설명 낱말로 질문하면 그 사진이 찾아지는지. 건너뛴 사진은 기록 목록에 "설명 없음"이 보이고, 기록 상세의 "설명 추가"로 나중에 달 수 있다.
5. `+` → 파일 → PDF/워드/엑셀 올리기. 스캔 PDF 는 "확인 필요"로 표시된다.
6. ☰ → **기록** 탭: 목록, "확인 필요" 표시, 기록 눌러서 고치기/확인 완료/지우기(길게 누르기도 가능).
7. ☰ → **대화** 탭: 새 대화(+) 후 이전 대화가 목록에 남고 다시 열리는지.
8. 개인정보: 주민번호·전화·카드가 기록 화면에서 `******-*******`, `010-****-****` 처럼 가려져 보이는지(원본 보기에서는 그대로).

### 4. PostgreSQL 에서 확인 (개인 테스트 DB 전용, 팀 공용 DB 에 쓰지 않는다)

```bash
PGVECTOR_TEST_DATABASE_URL=postgresql+psycopg://사용자:비밀번호@127.0.0.1:5433/gabee pytest -k pgvector
```

저장 → 검색 → 가족 간 분리를 PostgreSQL+pgvector 에서 검사한다. 직접 SQL 로 보려면:

```sql
SELECT count(*) FROM knowledge_items;
SELECT item_id, seq, embedding_model, vector_dims(embedding) AS dim, left(text, 40) FROM knowledge_chunks ORDER BY item_id, seq LIMIT 10;
\d knowledge_chunks   -- embedding 이 vector(384), ix_knowledge_chunks_embedding_hnsw 인덱스
```

`dim` 이 384 이고 `embedding_model` 이 의도한 모델이면 정상이다.

## 자주 만나는 문제

| 증상 | 원인과 해결 |
| --- | --- |
| 503 `schema_not_ready` | DB 마이그레이션이 아직 적용되지 않음. 담당자가 `c3a9f21d7e54` 까지 적용 |
| 503 `embedding_model_missing` | PostgreSQL 인데 임베딩 모델 폴더가 없음. 위 "임베딩 모델 전달" |
| 문서는 있는데 @가비가 못 찾음 | 모델 폴더 이름·모델이 바뀌어 옛 조각이 검색에서 빠졌을 수 있음. `python -m scripts.reindex_embeddings`(`--check`)로 "현재 모델과 다른 조각"을 보고, 있으면 "모델 폴더 이름이 바뀌면" 절대로 조치(공용 DB 는 DB 담당자) |
| 글자 없는 사진이 "설명 없음"으로 남음 | 정상. 사용자가 설명을 달 때까지 분류·날짜로만 검색된다(자동 설명은 없앴다) |
| 문서가 계속 "기타 문서 + 확인 필요"가 됨 | 분류기 폴더가 없거나 `DOC_CLASSIFIER_DIR` 이 틀림, 또는 아직 배우지 않은 종류. "문서 분류기 전달" 확인 |
| 채팅이 "찾지 못했어요"만 함 | 글자가 흐려 값이 `[불확실]`/없음. 기록 상세에서 원본과 비교해 고친다 |
| 폰이 접속 못 함 | 같은 와이파이인지, PC 방화벽이 8001·8081 을 막는지 확인(방화벽 설정은 각자 PC 에서) |
| 기록에 `******-*******` 가 보임 | 정상(주민번호 가림). 원본은 원본 보기로 확인 |

## 채팅·기록 질문의 동의·한도 (ai_guard)

`POST /ai-assistant/chat`(기능 `assistant_chat`)과 `POST /ai-assistant/knowledge/ask`(`knowledge_ask`)는 가족 채팅 AI 와 같은 `ai_guard.run` 을 거친다. 가족 그룹이 AI 를 켜야 하고(소유자·관리자), 결과는 캐시하지 않는다. 그룹이 없는 사용자의 chat 은 외부 AI 를 부르지 않고 고정 안내(200, `source="fallback"`)만 돌려준다. 키가 없으면 외부 호출 없이 검색 결과만 보여 준다.

| 상황 | 응답 |
|---|---|
| 가족 AI 동의 꺼짐 | 403 `ai_not_enabled` |
| 가족 구성원이 아님(`active_group_id` 만 남음) | 403 `not_member` |
| 쿨다운 안(기본 없음) | 429 `ai_cooldown` |
| 사용자 하루 한도 | 429 `ai_daily_limit_user` |
| 가족 하루 한도 | 429 `ai_daily_limit_group` |
| 같은 가족의 다른 AI 요청 처리 중 | 409 `ai_busy` |
| 외부 AI 호출 실패 | 503 `llm_failed` (사용 기록 `status="error"`, 한도에는 센다) |

- 한도 값: 어시스턴트는 가족 채팅 AI 의 기본 한도(사용자 10회/일, 가족 30회/일, 쿨다운 30초)와 **따로** 센다(`ai_guard.register_bucket`, `ai_assistant/limits.py`). 예전 값을 유지해 사용자 **100회/일**, 쿨다운 **없음**이고, 가족 상한은 예전에 없던 새 값 **300회/일**이다(`AI_ASSISTANT_MAX_CALLS_PER_USER_PER_DAY`, `AI_ASSISTANT_MAX_CALLS_PER_GROUP_PER_DAY`, `AI_ASSISTANT_COOLDOWN_SECONDS`). 동시 실행은 가족당 1건 그대로(409 `ai_busy`). 예전 문서 요약·답변 엔드포인트(`doc_summary`·`doc_answer`)는 메인 에이전트가 같은 일을 하므로 없앴다(`@가비` 도 메인 채팅과 같은 한도를 쓴다).
- 질문 1건이 도구 루프로 Anthropic 을 1~4번 부르고, 실제 호출 수를 한도에 센다.
- 한도 초과 폭: 요청 시작 때는 1회만 예약하고 끝나면 실제 횟수로 고치므로, 한도 직전의 마지막 요청은 최대 3회(4-1)까지 더 셀 수 있다.

## 앱 안내 화면 (AI 채팅 탭)

- 서버 오류 코드를 말풍선 안내로 바꾼다(`features/ai-assistant/errors.js`, 시험 `apps/mobile/tests/assistanterrors.test.js`): `ai_cooldown`·`ai_busy` "조금 뒤에 다시 물어봐 주세요", `ai_daily_limit_*` "오늘 AI 사용 한도에 도달했어요", `llm_failed` "AI 연결에 문제가 있어요", `not_member` 가족 참여 안내, 그 밖에는 서버 문구.
- `ai_not_enabled` 는 말풍선 대신 안내 카드(`AiOffCard`): "AI 도우미가 꺼져 있어요", 질문하면 관련 가족 기록 일부가 외부 AI(Anthropic)로 전송된다는 설명(민감 기록은 기본 제외). 설정은 `GET /family-chat/ai/settings` 로 확인하고, `can_manage` 이면 "AI 사용 켜기" 버튼(`PUT /family-chat/ai/settings {enabled:true}`, 누를 때만 호출), 아니면 소유자·관리자에게 요청하라는 안내. 켜면 카드가 "AI를 켰어요. 방금 질문을 다시 보내 주세요." 로 바뀌고 질문은 자동으로 다시 보내지 않는다.
- 오류 말풍선과 그 오류를 부른 질문은 다음 요청의 `history` 에서 빠진다(오류 문구가 외부 AI 로 실려 가지 않는다).

## 팀이 정해야 할 것

1. **외부로 나가는 글**: 가린 글자는 Claude(외부 API)로 전송된다. ingest 문서의 "어떤 모델에도 보내지 않는다" 문구를 고칠지, 민감 기록은 기본 제외(`CHAT_INCLUDE_SENSITIVE=false`)로 할지, 동의 절차를 둘지.
2. **일반 문서의 가리기 확대**: 전처리 담당자의 기존 정책("일반 문서는 주민번호만")을 바꿨다. 확인이 필요하다.
3. **공유 범위**: 기록을 가족이 모두 보고 고치고 지울 수 있다. 본인만 보게 하려면 DB 컬럼(소유자·공개 범위)이 필요하다.
4. **대화 저장**: 지금은 기기에만. 서버 저장은 테이블·마이그레이션·보관/삭제 정책이 필요하다.
5. **원본 보관**: 보관 기간, 삭제 요청 시 일괄 삭제, 건강정보 별도 동의, 14세 미만 자녀 동의.
6. **PR 나누기**: 한 번에 크다.

## 원본 경로 보안 수정

`LocalRawStore.get_for_group`/`delete_for_group` 는 경로 첫 칸이 그룹 id 인지만 보고 `<내그룹>/../<남의그룹>/…` 를 통과시켰다. 이제 `..`·`.`·빈 칸·절대경로·백슬래시·널 문자를 거부하고, 해석한 결과가 그 그룹 폴더(`raw/<group_id>`) 안일 때만 읽고 지운다. 또 `POST /ai-assistant/knowledge/items` 의 `source_path` 는 클라이언트가 임의로 넣을 수 없다. 요청 필드는 호환을 위해 남겨 두되 값은 **무시**하고(400 으로 깨지지 않음) 원본 참조는 업로드 처리(`files.py`)가 서버에서 만든 것만 쓴다.

## 보안 점검에서 아직 열린 것 (이 브랜치에서 고치지 않음)

압축·화소 폭탄 상한, 원본 동시 저장 오류(같은 파일 동시에 올릴 때), 업로드 대기 상한, 처리 중 서버 재시작 시 재처리. 팀에 공개하기 전에 우선순위를 정하는 것이 좋다.

## 가족 이름 메타데이터화 (2026-11-02, ADR 0012)

- 업로드 글의 가족 이름(이름·표시 이름, 조사·성 뗀 이름자 포함)은 가리기 전에 `[가족:<user_id>]` 로 바뀌어 저장되고, `knowledge_items.family_user_ids` 에 등장한 가족이 남는다. 읽을 때(상세·목록·검색·파일 상태·기록 도구) 현재 표시 이름으로 되돌린다. 동명이인은 치환하지 않는다.
- (RAG 개선 라운드 5) `search_knowledge` 결과는 기록 단위 그대로이되 위쪽 3개 기록에는 `more`(같은 기록의 다음으로 가까운 조각 최대 2개, `page` 포함, 추가 글 합계 2000자 상한)를 싣는다. 출처·`ref`·`_renumber` 는 기록 단위라 그대로이고 출처 칩의 쪽은 가장 가까운 조각의 쪽이다. 라우터 `/knowledge/search`·`lookup` 은 `service.search` 기본값(기록당 1조각)이라 동작이 같다. `get_item` 은 앞 12000자(약 8000토큰)에서 자르고 `note` 로 알린다(최대 6만 자 문서가 입력을 키우는 것을 막음). 메인 프롬프트는 관련 기록이 있는데 조각에 답이 안 보이면 `get_item` 으로 읽어 본 뒤에 못 찾았다고 하도록 한다.
- `search_knowledge` 에 `member`(이름·별칭) 필터, 도구 결과에 `family`(등장한 가족의 현재 이름) 추가. 메인 채팅(`rag_chat._run_tool`)의 허용 인자 목록에 `member` 를 넣어야 AI 가 쓸 수 있다(1팀 작업 파일).
- 기존 기록은 백필하지 않는다(`강**` 그대로).

## 문서 목록 날짜 조건

`GET /ai-assistant/knowledge/items` 에 선택 파라미터 `created_from`, `created_to`(`YYYY-MM-DD`)를 더했다. `created_at` 을 한국 시간(KST) 달력 날짜로 보고 양끝을 포함해 거른다(`settings.ai_day_utc_offset_hours` 로 UTC 경계 변환). 한쪽만 줘도 되고, 안 주면 기존과 같다. `created_from > created_to` 면 400 `invalid_range`. 하위 호환 추가다.

- 날짜 범위를 줘도 `limit`(최대 200)이 그대로 걸리고 정렬은 문서 날짜(`occurred_on`) 최신순이다. 한 주에 올라온 문서가 200건을 넘는 경우는 현실적으로 드물다고 보고 한계로 둔다(넘으면 문서 날짜가 오래된 것부터 빠진다). 날짜가 표현 범위를 넘는 값(예: `9999-12-31`)과 시작이 끝보다 늦은 범위는 400 `invalid_range` 이다.

## 문서 읽음 기록

문서(KnowledgeItem)를 **구성원마다** 읽었는지 기록한다. `GET /ai-assistant/knowledge/items/{id}` 상세를 열면 그 사용자의 읽음이 자동으로 남는다(테이블 `knowledge_item_reads`, 이미 있으면 그대로 두는 멱등 저장). 다른 가족 문서라 404 가 나면 남기지 않는다. 읽음은 **본인 것만** 조회된다: 목록(`GET /items`)·상세 응답의 `seen`(bool, 하위 호환 추가)은 요청한 사용자 기준이고, 다른 구성원의 읽음 여부를 알려 주는 API 는 없다.

- 내가 올린 문서(`created_by` 가 나)는 별도 기록 없이 처음부터 `seen=true` 다. 상세 응답의 `seen` 은 방금 열었으므로 항상 true 다. 생성·수정 응답은 기본값 true 다.
- 읽음은 이 상세 GET 에서만 기록한다. 목록·검색·AI 도구·`service.get_item` 내부 호출은 기록하지 않는다.
- 문서를 지우면(`knowledge/repository.delete_item`, 파일 삭제 경로 포함) 그 문서의 읽음 행도 함께 지운다.

## 사진 크게 보기·확대 (2026-11-06)
- **메인 화면(AI 채팅)**: 올린 사진 썸네일(내 말풍선 위)을 누르면 전체 화면 뷰어(`OriginalViewer`)가 열린다. 올린 직후의 폰 사진을 그대로 보여 주므로 앱을 닫았다 열면 그 경로가 사라져 "사진을 불러오지 못했어요"가 보일 수 있다(기록 탭에서는 서버의 원본을 본다).
- **확대**: 폰 갤러리처럼 동작한다(`ZoomableImage`, 계산은 `zoomMath.js`). 두 손가락은 손가락 사이 지점을 기준으로 1배~5배 확대·축소하고 벌린 채 움직이면 사진도 따라온다. 한 손가락은 확대한 사진을 끌어 옮기고 튕기듯 놓으면 관성으로 더 움직이며, 사진 가장자리가 화면 안으로 들어오지 않는다(실제 보이는 사진 크기 기준). 두 번 누르면 누른 곳을 중심으로 2.5배 ↔ 원래 크기. 안드로이드의 `ScrollView` 는 핀치 확대가 없어(iOS 만 `maximumZoomScale` 이 동작) `react-native-gesture-handler`·`reanimated` 로 직접 만들었다.
- **제스처 구성 주의**: 두 번 누르기와 핀치·드래그는 `Gesture.Race` 로 묶는다. `Exclusive` 로 묶으면 두 번 누르기가 실패할 때까지 핀치·드래그가 시작되지 못해 빠른 동작이 씹힌다. 제스처는 움직이지 않는 바깥 뷰에 붙인다. Modal 안에서는 안쪽에 `GestureHandlerRootView` 가 있어야 안드로이드에서 제스처를 받는다.
- **기록 탭의 원본 보기**도 같은 뷰어라 사진은 바로 확대된다. PDF 처럼 여러 쪽이면 쪽을 위아래로 이어서 보여 주다가 **쪽을 누르면 그 쪽을 전체 화면에서 확대**해 보고(이전·다음 쪽 버튼, 왼쪽 위 뒤로 가기로 목록), 한 쪽짜리면 바로 확대된다.
- 시험: 순수 계산은 `tests/zoommath.test.js`. 손가락 제스처는 자동 시험이 어려워 폰(Expo Go)에서 직접 만져 확인한다.
- **문서 검색 섞기(2026-11-10)**: `search_knowledge` 는 임베딩 상위 100개 조각을 글자 2·3개 묶음 TF-IDF 와 RRF 로 섞어 정렬한다(설정 `chat_hybrid_search`). 자세한 측정은 `docs/features/ai_assistant-knowledge-hybrid.md`, 결정은 ADR 0019.
