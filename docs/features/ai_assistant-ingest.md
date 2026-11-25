# 구현 현황: AI 비서 정제화 (ai_assistant-ingest)

- 상태: 진행 중 (원본 전처리 · 사진 OCR · 오피스·PDF 변환 · 원본 데이터 센터 · 개인정보 가리기 · 쪽/슬라이드/시트 번호 · 가린 글자 자동 분류)
- 담당: ai_assistant-ingest
- 요구사항: docs/requirements/ai_assistant-ingest.md

## 구현된 것

`apps/api/app/features/ai_assistant/ingest/` — `preprocess(파일 바이트, 파일 이름) → PreprocessResult`

```
파일 ─▶ 검사(빈 파일·25MB) ─▶ sha256 ─▶ 형식 판별 ─┬─ 사진 ──── 회전·축소·흑백 ─▶ 한국어 OCR ─▶ ocr_line 블록
                                                ├─ PDF·오피스 ─ MarkItDown ─▶ 마크다운 ─▶ 제목·문단·표·목록 블록
                                                ├─ 텍스트·CSV·HTML ─▶ 블록 (CSV 는 CP949 도 읽음)
                                                └─ 그 밖 ──── failed + 이유
```

| 파일 | 하는 일 |
|---|---|
| `schemas.py` | 결과 모양: 원본 정보(종류·MIME·크기·sha256), 글자·블록·쪽 수, 품질(ok/partial/failed·경고·오류 코드) |
| `detect.py` | 확장자가 아니라 **파일 내용**으로 형식 판별 (JPEG·PNG·WEBP·HEIC·PDF·DOCX·XLSX·PPTX·TXT·MD·CSV·HTML). 예전 hwp·doc·xls 와 hwpx 는 "아직 지원 안 함" |
| `converters.py` | 사진: EXIF 회전 → 긴 변 1600px / 짧은 변 720px(최대 2배 확대) → 흑백·대비 → RapidOCR PP-OCRv5 한국어, 같은 줄 상자 묶기. 문서: MarkItDown → 마크다운 → 블록 |
| `service.py` | 전체 흐름. 실패해도 예외 대신 `quality.status = failed` 와 이유 코드(`empty_file`, `too_large`, `unsupported_type`, `broken_file`) |
| `tests/test_ingest.py` | 36개. 가짜 OCR 로 돌아서 CI(모델·GPU 없음)에서도 통과. docx·xlsx·pptx·pdf 는 테스트 안에서 직접 만들어 진짜 변환을 확인 |

품질 기준: OCR 평균 확신도 0.75 미만이면 `partial`("일부만 읽혔을 수 있어요"), 글자 없는 사진은 `ok` + "사진에 글자가 없어요", 글자 층이 없는 PDF(20자 미만)는 `partial`("스캔본").

실측 (CPU, onnxruntime, 2026-10-22): 영수증 사진 24줄·확신도 0.93·5.8초(첫 호출, 모델 내려받기 포함), 관리비 고지서 48줄·0.89·12.8초, 풍경 사진 글자 없음 1.0초. GPU 서버면 1.4~4초 수준(원본 프로젝트 측정).

추가 의존성 (`apps/api/pyproject.toml`): `pillow`, `pillow-heif`(아이폰 HEIC), `rapidocr`+`onnxruntime`(한국어 OCR, 모델 약 13 MB 는 첫 호출 때 내려받음), `markitdown[docx,xlsx,pptx,pdf]`(오피스·PDF → 마크다운). 모두 MIT/Apache-2.0, 로컬에서 돌아 파일이 외부로 나가지 않는다.

### 원본 데이터 센터 · 개인정보 가리기 · 번호 (2026-10-22)
- `raw_store.py`: 올라온 파일을 **가공하지 않고 그대로** `DATA_DIR/raw/<group_id>/<sha256 앞 2자리>/<sha256>.<확장자>` 에 보관. 같은 내용은 한 번만, 쓰다 멈춰도 반쪽 파일 없음, 다른 경로 접근 차단. 지원하지 않는 형식도 원본은 보관(나중에 다시 처리). 운영 보관소는 미정 — 같은 `put/get/delete` 로 바꿔 끼움.
- `masking.py` (2026-10-22 변경): `sensitive_kind` 가 처방전 / 신분증(id_card) / 통장(bankbook) / 가족관계증명서(family_cert) / 그 밖(none)을 정한다. 앞의 넷은 개인정보를 모두 가리고(처방전: 병명 코드·면허번호, 신분증: 운전면허·여권 번호·영문 이름·라벨 없는 이름/주소 줄, 통장: 라벨 없는 계좌번호 10~16자리(날짜 8자리는 제외), 가족관계증명서: 구분 칸 옆 이름·출생연월일·등록기준지), 그 밖은 주민등록번호만 가린다. 신분증·통장·가족관계증명서는 가린 뒤 분류 모델로 가고(Jev 목록에 주민등록증·운전면허증·여권·외국인등록증·통장 사본·가족관계증명서 추가), 처방전은 규칙으로만 정한다. 가린 **개수만** `privacy.masked` 에 기록.
- 가리기는 **블록으로 나누기 전에** 한다 — "성명 / 김영희" 처럼 두 줄에 걸친 것도 가려진다.
- `service.ingest_file(group_id, …)`: 원본 보관 → 전처리 → 가리기 → 결과에 `raw_path`.
- PPT·엑셀은 `content.text`(분류·검색에 넘기는 글자)를 `## 슬라이드 N` / `## 시트 N: 이름` 구역 제목과 `[블록 번호]`(index+1)가 붙은 마크다운으로 만든다(`converters.numbered_markdown`). 표·목록은 번호를 따로 한 줄에 둬 마크다운 표가 깨지지 않는다. 엑셀 시트 이름은 블록이 아니라 `sheet` 로만 남겨 번호가 건너뛰지 않는다.
- 블록 번호: `index`(순번), `page`(PDF 쪽 · PPT 슬라이드 · 엑셀 시트 번호), `sheet`(엑셀 시트 이름). PPT 의 그림 자리 표시는 글자에서 뺌.
- 실측: 영수증 카드번호·전화번호 가림, 처방전(합성) 이름·주민번호(OCR 이 "5x0101" 로 읽은 것 포함)·면허번호 가림, 약 이름 유지.

### 가린 뒤 Jev 분류 (2026-10-22, 담당자 결정)
```
가린 글자 ─▶ 규칙(처방전·고지서·영수증) ─▶ 끝 (어떤 모델에도 안 보냄. 단 INGEST_LLM_* 를 켜면 읽기·가리기는 Claude 가 한다 — 2026-11-04 회의 결정)
          └▶ 그 밖 ─▶ Jev 한 번 호출 (가린 글자 + 코드가 찾은 날짜·금액 후보)
                       doc_type    choice  문서 종류 22개 + none
                       is_document noul    챙길 문서인가 → document / daily_share
                       domain      choice  분야 9개 → 태그
                       deadline    choice  날짜 후보 중 마감일 (후보 있을 때만)
                       main_amount choice  금액 후보 중 주요 금액 (후보 있을 때만)
                     ├ none        ─▶ "기타 문서" + 사람 확인 (2026-10-26: qwen 이름 붙이기 폐지)
                     ├ 확신 0.6 미만 ─▶ 사람 확인
                     └ 실패·키 없음 ─▶ 로컬 분류기 (아래)
```
> **2026-10-26 변경**: 순서가 `규칙 → 로컬 분류기(확률 0.7 이상이면 확정) → Jev(키가 있을 때만) → 기타 문서 + 확인 필요` 로 바뀌었다. 위 그림은 Jev 호출 부분의 설명으로 남긴다.
> **2026-11-06 변경**: "기타 문서 + 확인 필요"(종류를 못 정한 경우)에도 글에서 규칙으로 찾은 **날짜·금액 후보는 남긴다**(이전에는 비어 있어, 실제 촬영한 안내문 3장이 모두 날짜 없이 끝났다). 종류 판단은 그대로이고 날짜 앞에 연도가 없는 표기("9. 5.(토)")는 아직 찾지 못한다.
- Jev 는 글을 만들지 않고 고르기만 한다 → 날짜·금액은 코드가 후보를 찾고 Jev 가 "어느 것이 마감일인지" 고른다. 확신도가 측정된 확률이라 qwen 의 자기 신고(늘 1.0)보다 믿을 만하다.
- `app/shared/llm/jev.py`(`ask`, httpx 로 `POST https://api.typesafe.ai/v1/systemone`, 새 라이브러리 없음). 설정 `TYPESAFE_API_KEY`, `JEV_MODEL`(기본 `jev-latest`).
- 테스트는 가짜 Jev. 개발자 `.env` 에 키가 있어도 테스트는 진짜 Jev 를 부르지 않는다.

### 로컬 분류기 (2026-10-26) — 아래 qwen 분류를 대체했다

`ingest/doc_classifier.py`: 가린 글을 앱 임베딩(e5-small 파인튜닝)과 글자 TF-IDF 로 숫자로 바꿔 로지스틱 회귀로 종류 46개 중 고른다(numpy 만 사용, 문서당 약 16ms). 확률이 0.7 이상이면 `by="classifier"` 로 확정, 아니면 Jev(키가 있을 때), 그래도 모르면 "기타 문서 + 확인 필요". 장소·중요 칸(`fields`)은 만들지 않는다. 파일 전달·재학습은 `docs/features/ai_assistant-upload-chat.md` 의 "문서 분류기 전달", 결정과 시험 결과는 ADR 0010.

### (폐지) 로컬 언어 모델 분류 — 2026-10-26 에 제거, 기록으로만 남긴다
```
원본 보관 ─▶ 글자 뽑기 ─▶ 가리기 ─▶ classify(가린 글자만, 파일 이름 X)
                                     ├ 글자 없는 사진 ─▶ "사진" · 가족 공유
                                     ├ 처방전(가리기 단계 판단) · 고지서 · 영수증 ─▶ 규칙 (모델 안 부름)
                                     └ 그 밖 ─▶ 로컬 qwen2.5:7b (Ollama) ─▶ 자유 문구 종류·태그·날짜·금액·장소·폼 칸
                                                └ 꺼짐·답 깨짐·확신 0.6 미만 ─▶ 사람 확인(review)
```
- `classify.py`, 결과는 `PreprocessResult.classification` (`schemas.Classification`), 버전 `ingest/2`.
- 모델 호출은 `app/shared/llm/local.py`(`complete_json`, Ollama `format=json`, 온도 0). 설정 `LOCAL_LLM_URL`, `LOCAL_LLM_MODEL`.
- 모델 답도 한 번 더 가린다(지어낸 전화번호 등). 날짜는 YYYY-MM-DD 로 맞추고 틀린 날짜는 버린다.
- 실측(RTX 3050, qwen2.5:7b): 가정통신문 → "학부모 안내문"·제출 기한 10-30·체험학습비 15,000 (첫 호출 29초=모델 올리기, 이후 6~10초), 아파트 공지 → "아파트 관리사무소 공지", 아이 문자 → "일상 메모"·가족 공유.
- 한계: 모델이 말하는 확신도는 거의 항상 1.0 이라 믿을 수 없다(사람 확인 기준으로는 약함). 같은 종류가 다른 이름("가정통신문"/"학부모 안내문")으로 나올 수 있어 이름 묶기가 필요하다.

### 찍힌 사람 찾기 — 삭제함 (2026-10-25)

얼굴은 생체정보라서 이번 범위에서 뺐고, 코드(`faces.py`)와 테스트, 설정(`FACE_MODEL_DIR`·`FACE_ENABLED`)을 지웠다(사용자 결정, ADR 0010). 필요해지면 깃 이력에서 복구한다. `PreprocessResult.people` 도 없어졌다.

### 사진 전처리 (2026-10-22, 측정해서 정한 방식)
```
업로드 사진 ─┬▶ 원본: 받은 그대로 원본 데이터 센터 (<sha256>.jpg)
             ├▶ OCR용: 회전 → 긴 변 1600px(작으면 짧은 변 720px까지) → 흑백·대비 (저장 안 함)
             └▶ 화면용 사본: 회전 → 긴 변 1080px(키우지 않음) → WebP q75 → EXIF(위치·기기) 제거
                 원본 옆 <sha256>.display.webp, 결과 display_path
```
- 1080px WebP q75 는 고지서 글자가 뭉개져(글자 일치 0.10~0.38) **보기용으로만** 쓰고, OCR 은 1600px 로 한다.
- 휴대폰 업로드는 1600px WebP q80 추천(크기 52% 줄고 OCR 0.90) — 앱 담당과 협의 필요. 서버는 어떤 크기로 와도 위 세 가지를 만든다.
- 실측(실제 사진 5장): 화면용 사본 합계 원본의 20%, 장당 0.14~0.34초. 영수증 원본에 있던 위치 정보(GPS)가 사본에는 없음.

## Claude 로 읽고 가리기 (2026-11-04. 2026-11-09 부터 글자 읽기 `INGEST_LLM_OCR` 과 가리기 `INGEST_LLM_MASK` 모두 기본 켜짐, 결정: [ADR 0014](../adr/0014-upload-llm-ocr-masking.md))
```
사진·스캔·PDF 쪽 ─▶ Claude OCR(shared/llm/doc_ai.read_image·read_pdf) ─┐   [?] 줄 → 확신도 0.5 → 기존 [불확실] 표시
Word·PPT·텍스트·CSV ─▶ MarkItDown(지금 방식) ───────────────────────────┤
Excel ─▶ converters.xlsx_to_markdown (금액 쉼표·날짜·병합 칸 반영) ─────┘
  ─▶ llm_ingest.mask: 긴 글은 6천 글자 단위로 나눠 ─▶ (코드) 가족 이름 후보 ─▶ (Claude 1회) 후보 문맥 판단 + 그 밖의 개인정보 인용
     ─▶ (코드) 인용 검증 → [가족:id]·[이름]·[주소]… 로 바꾸기 → 번호 규칙 안전망
  ─▶ 분류·임베딩·저장(그대로)
```
- Claude 호출이 실패하면 가리지 않은 글을 저장하지 않고 `quality.error = llm_unavailable` 로 `failed`. 서버가 같은 파일을 자동으로 다시 처리한다(`INGEST_RETRY_MAX` 번, 기본 2번, 기다리는 시간 `INGEST_RETRY_WAIT_SECONDS`×시도 번호 초; 깨진 파일·지원 안 하는 형식은 다시 하지 않는다). 다시 처리하는 API 는 없고, 서버가 꺼져 날아간 작업은 기존대로 15분 뒤 실패로 본다.
- 주소는 개인 거주지·배송지만 가리고 사업장·공공장소·행정구역은 남긴다. `privacy.masked` 에는 종류별 개수(`person`, `phone`, `family` …)만 남고 값은 남지 않는다.
- 평가: 새 대화 묶음 600창에서 못 가린 비율 기존(규칙+NER) 37% → Claude(v3) 6%. 현재 코드의 프롬프트는 v5(개인 주소만 가림)이고, v5 기준 주소 제외 누출은 3.6%(기존 33.4%)다. 합격 기준 평가 결과는 ADR 0014 와 PR 설명을 본다.
- 이름 오타 확인: Claude 가 이름으로 본 값이 가족 이름과 **한 글자 차이**(정확히 같지는 않음)면 `[이름]` 대신 `[확인필요:<후보 user_id>]` 를 남긴다(OCR 이 틀리게 읽었을 수 있음. 글자는 저장하지 않는다). 새 DB 칸은 없고 기록 본문의 표시로 대기 상태를 나타낸다. 메인 채팅은 대기가 있으면 시스템 안내(`NAME_CHECK_NOTE`)로 사용자에게 한 번 물어보고(`list_name_checks`), 답을 `resolve_name_check` 로 반영한다: 같은 사람이면 `[가족:<id>]`(사람 필터 검색·현재 이름 표시), 아니면 `[이름]` 이며 검색 조각을 다시 만든다. 후보 id 는 그 기록에 남은 표시의 것만 받고, 답이 true/false 로 분명하지 않으면 거부한다. 표시 중에는 읽는 쪽에 `[이름 확인 필요]` 로 보인다. 앱 화면 변경 없음.
- 시험: `ingest/tests/test_llm_ingest.py`(가짜 Claude 응답), 이름 확인 흐름은 `tests/test_family_names.py`.

## 가족방 문서 사진 판별 (2026-11-09)
- `ingest/photo_judge.py`: 사진을 긴 변 1024px 로 줄여 로컬 OCR(RapidOCR)로 읽고, 확신도 0.6 이상 줄의 글자 수·줄 수로 문서(100자·6줄 이상)/일반 사진(50자 미만)/애매함으로 가른다. 기준은 실사진 15장(문서 8, 거리·음식 7)과 무료 라이선스 사진 227장으로 정했다.
- `shared/llm/doc_ai.classify_photo`: 글자가 읽힌 사진만 Claude(haiku, `PHOTO_JUDGE_MODEL`)에게 "문서 사진인가"를 묻는다(도구 호출 형식, 문서·사진 + 확신도). `ai_assistant/library.py` 는 `PHOTO_JUDGE_LLM=true` 일 때만 쓰고, 문서이고 확신 0.7 이상일 때만 등록한다. 결정·평가: `docs/adr/0015-family-room-photo-to-library.md`.
- 시험: `ingest/tests/test_photo_judge.py`, `shared/llm/tests/test_photo_classify.py`, `ai_assistant/tests/test_chat_library_photos.py`.

## 단계형(E) 판별: OCR + SigLIP2 (스위치 `PHOTO_CLASSIFY_SIGLIP`, 기본 꺼짐)
- 켜면 `library._judge_photo` 가 OCR 판별 뒤 `ingest/siglip_margin.py` 로 margin(= 문서 문장 6개 logit 최댓값 − 일반 문장 8개 logit 최댓값, `google/siglip2-base-patch16-224`)을 구해 단계형 규칙으로 정한다: OCR 이 문서여도 margin ≤ 1 이면 unsure, OCR 이 문서가 아니어도 margin > 5 이면 document, 나머지는 unsure. photo 는 만들지 않는다(D-13). 값·문장은 공개 데이터 평가(`gabee-classifier-eval/public`, 동결 설정 exp-1)와 같고 바꾸지 않는다.
- 모델은 **ONNX 이미지 인코더**(비전 타워 + 풀링 헤드, fp32 약 372MB)를 이미 의존성에 있는 `onnxruntime` CPU 로 서버 프로세스 안에서 돌린다(torch 없음, 스레드 `PHOTO_CLASSIFY_THREADS`, 기본 2). 모델 폴더 `PHOTO_CLASSIFY_MODEL_DIR` 에는 `siglip2_vision.onnx` 와 문장 14개의 텍스트 임베딩·`logit_scale`·`logit_bias` 를 담은 `head.json` 이 있어야 한다. 둘 다 `scripts/export_siglip2_onnx.py` 로 같은 체크포인트(`google/siglip2-base-patch16-224`)에서 만들고, 파일은 저장소에 올리지 않는다(`data/models` 와 같이 이미지 빌드 때 넣는다, `SHA256SUMS.json` 으로 무결성 확인). 모델은 처음 사진이 올 때 한 번만 올린다.
- 모델 폴더가 없거나 파일이 깨졌거나 메모리가 모자라거나 추론이 실패하면 failed(`Siglip…`)로 두고 문서·일반 사진으로 확정하지 않는다(로드 실패는 30초 동안 다시 읽지 않는다). 이 경로는 외부 AI 로 사진을 보내지 않는다. 문서로 판정되면 글자가 적어도 문서함에 남긴다(`keep_photo`).
- 시험: `ingest/tests/test_siglip_margin.py`, `ai_assistant/tests/test_photo_classify_siglip.py`. 실제 모델이 있으면(`GABEE_TEST_SIGLIP_ONNX_DIR`) 합성 사진 추론 한 건도 돈다.

### 운영 전 확인 ① Cloud Run 백그라운드 판별 위험과 MVP 운영 판단
- **구조**: 사진 판별(OCR → SigLIP2)은 업로드 응답이 나간 뒤 서버 프로세스 안 스레드(`library._executor`, 2개)에서 돈다. SigLIP2 를 붙이기 전의 OCR 판별도 같은 구조라 이 PR 이 새로 만든 위험이 아니다.
- **위험**: Cloud Run 이 "요청 중에만 CPU 할당"(기본)이면 응답 뒤에는 CPU 가 거의 멈춰 판별이 지연되거나 끝나지 못하고, 인스턴스가 내려가면(스케일 인·배포) 진행 중이던 작업과 대기열(`_photo_pending`, 메모리)이 사라진다. 사진 바이트도 메모리에만 있다. 실제 설정은 **미확인**이다(운영에 접근하지 않았다).
- **유실이 사진 손실로 이어지지는 않는다**: 판별 상태 표에 `pending` 으로 남고, 15분 뒤 "확인 필요"로 보이며, 업로더가 재검사(최대 3회, 2분 간격)하거나 일반 사진으로 직접 확인할 수 있다. 문서함에는 판별 결과가 `document` 일 때만 올라가므로 잘못 등록되지는 않는다(지연·미처리만 생긴다).
- **판단(MVP)**: 스위치를 켠 채로 **수동 재검사에 의존한 운영은 가능하나, 처리 누락이 보일 수 있는 조건부 운영**이다. 사진이 오래 `pending` 이면 재검사 버튼으로 복구한다. CPU 를 계속 할당(요금·운영 변경)하거나 업로드 요청 안에서 동기 판별(응답 지연 수십 초)하는 것은 이 PR 범위 밖이며 운영 설정 확인 뒤 별도 결정한다.
- **켜기 전 점검**: ① Cloud Run CPU 할당 방식, ② 인스턴스 메모리(2GiB 이상, 측정 최대 RSS 약 1.44GB)·vCPU(OCR 가 코어 수에 비례해 느려진다), ③ 최소 인스턴스 수, ④ 사진 판별 지연의 실측.

### 운영 전 확인 ② 모델 파일 배포 위치와 SHA-256 검증 절차 (운영 배포는 하지 않는다)
- **산출물**: `siglip2_vision.onnx`(371,816,797 B, sha256 `52e01513b5b98b80056f10bcce72e9568e050070e296ea6d557afb5b06d61949`), `head.json`(241,529 B, sha256 `2a177cbe0fdd815447bcf2e089dbc96dbf906242e0d07d4c7831f90bd7bd8e87`). 같은 체크포인트에서 `scripts/export_siglip2_onnx.py` 로 만들면 `SHA256SUMS.json` 이 함께 나온다. 저장소(Git)에는 올리지 않는다.
- **배포 위치(제안, 둘 중 하나는 운영 담당 결정)**: (A) 이미지 빌드 때 `data/models/siglip2-onnx/` 로 `COPY`(기존 `data/models/<폴더>` 방식, 가장 단순, 이미지 +372MB) 후 `PHOTO_CLASSIFY_MODEL_DIR=/app/data/models/siglip2-onnx`. (B) Cloud Storage 에 두고 시작 때 내려받기(이미지는 작지만 시작 시간·권한 설정이 늘고 컨테이너 로컬 디스크는 메모리로 센다).
- **검증 절차**: 배포 파이프라인에서 `sha256sum -c`(또는 `python -c "import hashlib…"`)로 두 파일을 위 값과 비교한다 → 일치하지 않으면 배포를 중단한다. 앱은 로드할 때 `head.json` 의 문장 14개·형태(14×768)·유한성만 확인하고(불일치면 failed `SiglipHeadMismatch`), **파일 해시는 앱이 매번 확인하지 않는다**(372MB 읽기 비용). 해시 확인은 배포 단계의 책임이다. 모델 폴더는 운영자만 쓸 수 있는 경로에 두고 사용자 업로드 경로와 섞지 않는다.
- **기본 상태**: `PHOTO_CLASSIFY_SIGLIP=false`, `PHOTO_CLASSIFY_MODEL_DIR` 빈 값. 켜기 전에 모델 폴더가 없어도 서버는 정상 시작하고, 켠 뒤 파일이 없으면 판별만 failed 가 된다.

### 운영 전 확인 ③ 개인정보 검토가 필요한 항목 (정책 결정은 하지 않았다)
1. **Claude 로 나가는 범위**: 문서로 판정된 사진은 문서함 등록 단계(`files.process_file` → `ingest_file`)에서 `INGEST_LLM_OCR`(기본 True)이면 사진 전체가 Claude 로 전송되어 읽히고, `INGEST_LLM_MASK`(기본 True)이면 읽은 글이 다시 Claude 로 전송되어 가려진다. 이 등록 경로에는 `_family_allows_ai`(가족 AI 동의) 확인이 **없다**(판별 단계의 `PHOTO_JUDGE_LLM` 경로에만 있다). 기존에도 OCR 이 문서로 본 사진은 같은 경로를 탔다(이 PR 이 만든 경로가 아니다).
2. **이 PR 이 바꾸는 것**: 스위치를 켜면 ① 글자가 적은 문서(OCR 은 사진/애매)도 margin > 5 면 `document` 가 되어 Claude 전송 대상이 **늘어난다**, ② OCR 이 문서여도 margin ≤ 1(간판·메뉴판 등)이면 `unsure` 가 되어 전송 대상이 **줄어든다**. 순증감은 평가 데이터에서만 추정(재현율 상승, 일반→문서 오인 감소)이며 실제 가족 사진·한국어 문서에서는 측정하지 못했다. 켜진 동안 SigLIP2 판별 자체는 외부 전송이 없다.
3. **검토 요청 항목**: (a) 문서함 자동 등록의 외부 전송에 가족 AI 동의 확인이 필요한가, (b) 글자 적은 문서 구제로 늘어나는 전송을 허용할 것인가(원하지 않으면 rescue 만 끄는 별도 PR 필요), (c) 가족 동의 문구·개인정보처리방침의 기재 범위, (d) `keep_photo` 로 글자 적은 문서도 문서함에 남는 점. 결정 전에는 운영에서 스위치를 켜지 않는다.

## 문서 속 그림 설명 (2026-11-19)
- PDF: `doc_ai.read_pdf` 가 쪽마다 글을 옮기면서 그림·도표·사진이 있으면 `[그림: …]` 블록(1~3문장, 보이는 글자·값만, 추정 금지)을 붙인다(`FIGURE_RULE`). 사진 OCR(`OCR_SYSTEM`)은 그대로다. `INGEST_LLM_OCR` 이 꺼지면 둘 다 동작하지 않는다.
- PPTX: `ingest/figures.py` 가 zip·`_rels` 로 슬라이드 그림을 뽑아(150px 미만·15MB 초과 제외, 최대 30장) `doc_ai.describe_figure` 로 설명하고, 변환 결과의 `![…](ImageN)` 자리를 `[그림: …]` 으로 바꾼다. 글자 없는 빈 도형·화살표 흐름도는 `없음` 으로 답하게 해 붙이지 않는다. 설명 못 한 그림은 노트로 알린다. 새 의존성 없음.
- docx 그림은 아직 안 한다. 시험: `ingest/tests/test_figures.py`, `shared/llm/tests/test_doc_ai_read.py`.

## 남은 것
- 업로드 통로·DB 저장(`photos` 확장 또는 `files` 표)·백그라운드 처리 연결 — 요구사항 미정 4·5
- 스캔 PDF 쪽별 OCR, 복잡한 표 PDF(Docling) — v2
- 한글(hwp·hwpx)·음성 — v3, 요구사항 미정 3
- 사진 모양 분류(로컬 CLIP) — family 코드에서 옮기기 (torch 의존성 승인 필요)
- 문서 종류 이름 묶기("가정통신문"·"학부모 안내문" → 하나), 확신도를 모델 자기 신고 대신 측정값으로
- 쪽·슬라이드별 점검으로 빠진 쪽 찾기 → 빠진 쪽만 OCR
- OCR 후처리(숫자 오타 교정 "6O,OOO" → "60,000")는 자동 분류의 폼 채우기 단계에서
- 실제 한국 문서(가정통신문 PDF, 관리비 엑셀 등)로 형식별 3~5개 품질 측정

## 가족 채팅방 자동 처리의 외부 AI 동의 통제 (2026-11-26, ADR 0024)
- 채팅 문서·사진의 문서함 등록은 가족 채팅 처리 범위(`app/shared/llm/consent_gate.family_chat`)에서 돈다. 범위 안의 Claude·Jev 호출은 보내기 직전마다 가족 AI 동의를 다시 읽고, 없으면 보내지 않는다(`ConsentRequired`).
- 동의 OFF: 등록 보류·외부 호출 0회(문서로 판별된 사진은 `unsure` 로 남아 업로더 확인·동의 뒤 재검사가 가능). 처리 중 철회: 이후 호출 차단, 로컬 대신 처리 결과는 등록하지 않음(등록 직전에도 다시 확인). 같은 값으로 동의를 다시 저장해도 재노출 기준 시각은 그대로이고, 이름 확인 도구도 같은 기준으로 거른다. 동의 조회 실패: 차단. 스레드 풀 작업은 `consent_gate.carry` 로 범위를 넘긴다.
- 수동 "문서로 저장": 동의 없으면 403 `ai_not_enabled`, `INGEST_LLM_MASK=false` 면 503 `masking_unavailable`(둘 다 판별 상태 불변).
- 재노출 차단: 동의 시각 이전 채팅 기록은 @가비·메인 AI 도구에서 제외(앱 문서함 화면은 그대로).
- 메인 AI 직접 업로드·@가비·메인 채팅은 범위 밖이라 기존 정책 그대로.
- 시험: `ai_assistant/tests/test_chat_external_consent_minimal.py`, `test_chat_masking_required_minimal.py`, `knowledge/tests/test_chat_origin_exposure.py`. 기존 등록 시험은 폴더 conftest 에서 "가리기 켜짐·동의 켜진 가족"을 기본 전제로 둔다.
- 보장하지 않는 것: 과거에 저장된 기록(특히 MASK OFF 기간)의 안전성. 확인 절차는 ADR 0024.