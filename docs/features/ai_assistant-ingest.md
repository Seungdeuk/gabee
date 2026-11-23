# 구현 현황: AI 비서 정제화 (ai_assistant-ingest)

- 상태: 진행 중 (원본 전처리 · 사진 OCR · 오피스·PDF 변환 · 원본 데이터 센터 · 개인정보 가리기 · 쪽/슬라이드/시트 번호 · 가린 글자 자동 분류)
- 담당: ai_assistant-ingest
- 요구사항: docs/requirements/ai_assistant-ingest.md

> **2026-11-23 변경(사용자 결정)**: 로컬 OCR(RapidOCR)을 서비스에서 제거했다. 사진 분류는 SigLIP2 ONNX 단독, 문서 속 글자는 Claude 만 읽는다.
> 아래 "구현된 것"·"사진 전처리" 등에 적힌 OCR 서술은 **이력**이다(코드에서 `KoreanOcr`·`default_ocr` 는 사라졌고 `rapidocr` 를 import 하지 않는다).
> 현재 구조는 "가족방 문서 사진 판별 — SigLIP2 단독" 절과 "Claude 로 외부 전송하는 갈래와 가족 AI 동의" 절을 본다.

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

## 가족방 문서 사진 판별 — SigLIP2 단독 (2026-11-23, 로컬 OCR 제거)
- **결정**: RapidOCR 로컬 OCR 모델은 서비스에서 제외한다. 사진 분류는 SigLIP2 ONNX, 문서 내용 추출은 Claude(`INGEST_LLM_OCR=true`)가 맡는다.
- **판정 규칙**(`ingest/siglip_margin.py::photo_status`): margin(= 문서 문장 6개 logit 최댓값 − 일반 문장 8개 logit 최댓값, `google/siglip2-base-patch16-224`)이 **5 보다 크면 `document`, 아니면 `unsure`**. 모델이 점수를 못 내면 `failed`(`Siglip…`). 일반 사진을 자동으로 `photo` 로 확정하지 않는다(D-13). 임계값 5 는 공개 데이터 평가의 `T_RESCUE` 를 재사용한 **초기 기준**이며 새로 맞춘 값이 아니다. 문장·모델은 평가 동결 설정(exp-1) 그대로다.
- **스위치**: `PHOTO_CLASSIFY_SIGLIP`(기본 꺼짐). **꺼져 있으면 판별 수단이 없어 모든 사진이 `unsure`** 이고 문서 자동 등록이 멈춘다(켜야 동작). 켜도 판별은 외부 전송이 없다. 이전의 Claude 판별 스위치 `PHOTO_JUDGE_LLM` 은 무시된다(`doc_ai.classify_photo` 와 `photo_judge.judge`(OCR 판별)는 서비스에서 부르지 않는다: 후속 정리 대상, `photo_judge.to_judge_jpeg` 는 놀이 기능이 쓰므로 남긴다).
- **모델**: ONNX 이미지 인코더(fp32 약 372MB)를 이미 의존성에 있는 `onnxruntime` CPU 로 서버 프로세스 안에서 돌린다(torch 없음, `PHOTO_CLASSIFY_THREADS`). 모델 폴더 `PHOTO_CLASSIFY_MODEL_DIR` 에 `siglip2_vision.onnx` 와 `head.json` 이 있어야 한다(`scripts/export_siglip2_onnx.py`, 저장소에 올리지 않고 `data/models` 와 같이 이미지 빌드 때 넣는다). 없거나 깨졌거나 메모리가 모자라면 `failed` 로 두고 문서·일반으로 확정하지 않는다(로드 실패는 30초 동안 다시 읽지 않는다). 문서로 판정되면 글자가 적어도 문서함에 남긴다(`keep_photo`).
- **정확도(공개 데이터 독립 Test 123장: 문서 42·일반 81, ONNX margin)**:

| 판정 | 문서 재현 | 일반→문서 오분류 |
|---|---|---|
| 이전 단계형(OCR + SigLIP2) | 42/42 | 0/81 |
| **SigLIP2 단독 margin > 5 (현재)** | **39/42 (93%)** | **0/81** |
| (참고) margin > 2 | 42/42 | 1/81 (이 세트를 보고 고른 값이라 독립 평가가 아니다) |

  놓친 3장은 글자가 적거나 평범한 문서(margin 2.14·2.89·3.21)로 `unsure` 가 되어 업로더가 직접 확인한다. Wilson 95% 하한은 재현율 약 81%, 일반 사진 구분 약 95%다(소표본, 내 계산).
- **검증되지 않은 한계(반드시 알아야 한다)**: ① **실제 한국어 문서**로는 평가하지 못했다(공개 영어·일반 이미지 중심). ② **실제 가족 사진**으로도 평가하지 못했다. ③ 소표본이라 임계값 5 는 초기 기준일 뿐이다 — 운영에서 "확인 필요" 비율과 업로더 수정 기록으로 다시 본다. ④ 글자가 적은 문서·영수증·메뉴판·간판 구분이 약하다.
- 시험: `ingest/tests/test_siglip_margin.py`(규칙·점수기), `ai_assistant/tests/test_photo_classify_siglip.py`(업로드 → 판별 → 상태 → 문서함, 동의, 대기열 상한), `ingest/tests/test_external_consent.py`(동의 없는 갈래 막기). 실제 모델이 있으면(`GABEE_TEST_SIGLIP_ONNX_DIR`) 합성 사진 추론 한 건도 돈다.

### 로컬 OCR 이 쓰이던 곳 조사와 `INGEST_LLM_OCR` 필수 여부
| 쓰이던 곳 | 이전 | 지금 |
|---|---|---|
| 사진 판별 `library._judge_photo` | OCR 글자 수·줄 수 + SigLIP2 | **SigLIP2 단독**(OCR 호출 제거) |
| 사진 읽기 `service._from_image` | `INGEST_LLM_OCR=false` 면 로컬 OCR | Claude 만. `INGEST_LLM_OCR=false` 이고 읽기 구성 요소(`files.processors.ocr`, 시험·개발용)도 없으면 `failed`(`ocr_unavailable`) |
| 스캔 PDF 쪽 `service._read_pdf` | Claude 를 끄면 로컬 OCR | 동의 + `INGEST_LLM_OCR` 면 Claude, 아니면 글자 층만 쓰고 스캔 쪽은 읽지 못한 채 노트로 알린다 |
| `converters.KoreanOcr`·`default_ocr` | RapidOCR 첫 호출 때 모델 내려받기(약 13MB) | **삭제**. 코드는 `rapidocr` 를 import 하지 않는다(import 를 막아도 시험이 돈다) |

**`INGEST_LLM_OCR=true` 는 서비스에서 필수**다(사진 속 글자를 읽을 수단이 Claude 뿐). 검증: 켠 채 동의 있는 가족은 Claude 읽기, 동의 없는 가족은 보내지 않고 `consent_required`, 끈 채 읽기 구성 요소가 없으면 `ocr_unavailable`(`test_external_consent.py`). `rapidocr` 의존성은 `pyproject.toml` 에서 제거했다(전체 회귀 확인 뒤 별도 커밋).

### Claude 로 외부 전송하는 갈래와 가족 AI 동의 (2026-11-23 전수 점검)
원칙: **외부로 보낸 뒤 마스킹하는 것으로는 동의 문제가 풀리지 않는다.** 그래서 동의(`ai_guard.is_enabled`)가 없으면 보내기 **전에** 막는다. `files._process_once` 가 시도마다 동의를 읽어 `ingest_file(external=…)` 로 내려보내고, False 면 아래 갈래를 쓰지 않는다.

| 경로 | Claude 로 가는 것 | 동의 없을 때 |
|---|---|---|
| 가족방 사진 자동 등록 (`library.register_chat_photo`) | 문서로 판정된 사진 전체(글자 읽기) | 판별은 로컬로 하되 `document` 를 `unsure` 로 낮춘다. **사진은 채팅에 남고 문서함 자동 등록은 보류**(숨기지 않는다, 업로더가 확인). |
| 사진 "문서로 저장" (`photo_service.save_to_library`) | 사진 전체 | **403 `ai_consent_required`**. 판별 상태도 바꾸지 않고 보내지 않는다. 이미 등록된 사진은 `already`. |
| 직접 올리기 `/ai-assistant/files` — 사진 | 사진 전체 | **403 `ai_consent_required`**(저장도 전송도 하지 않는다). |
| 직접 올리기 — PDF·문서·글 파일, 채팅 문서 자동 등록 | PDF 쪽 읽기, 글 가리기(`llm_ingest.mask`) | 받는다. 글자 층·텍스트만 읽고 로컬 규칙으로 가린다. 스캔 쪽은 읽지 못한 채 노트로 알린다. |
| `process_file` 안의 나머지 갈래 | PPT 그림 설명, 분류(Jev), 챙길 일 뽑기(`reminders.plan`) | 모두 건너뛴다(분류는 규칙·분류기로 못 정하면 사람 확인). |
| 메인 채팅·knowledge ask, 주간 뉴스, 놀이 사진 추천 | (기존) | 기존 동의 검사 유지, 이번에 바뀐 것 없음 |

- **행동 변화**: 동의 없는 가족도 지금까지는 문서·글 가리기가 Claude 로 갔다. 이제는 로컬 규칙으로 가려 저장한다(더 보수적). 사진은 동의가 있어야 문서함에 들어간다.
- **앱 영향**: 서버가 403 `ai_consent_required` 를 돌려주는 경로가 둘 늘었다. 앱에서 이 코드를 안내 문구("가족 AI 사용에 동의해 주세요")로 보여 주는 변경은 이번 범위가 아니다(서버 메시지가 그대로 노출된다).
- **남은 정책 결정**: 가족 동의 문구·개인정보처리방침의 기재 범위(사진이 Claude 로 전송되어 읽힌다는 점), 동의 없는 가족에게 문서 사진을 어떻게 안내할지.

### 운영 전 확인 ① Cloud Run 백그라운드 작업과 MVP 운영 판단
- **구조**: 판별(SigLIP2)은 업로드 응답 뒤 서버 프로세스 안 스레드(`library._executor`, 2개)에서 돈다. OCR 이 빠져 사진 한 장 판별이 약 0.3~0.5초로 짧아졌지만, **문서 등록(Claude 읽기, 수 초~수 분)은 여전히 응답 뒤 작업**이다.
- **위험**: Cloud Run 이 "요청 중에만 CPU 할당"이면 응답 뒤에는 CPU 가 거의 멈춘다. 로컬 Docker 시험은 이 문제를 재현하지 못하므로 **해결됐다고 볼 수 없다**. 인스턴스가 내려가면(스케일 인·배포) 진행 중 작업과 대기열(`_photo_pending`)이 사라진다. 판별 상태 표의 `pending` 이 15분 뒤 "확인 필요"로 보이고 재검사(최대 3회)로 복구된다.
- **선택지**:

| 선택지 | 비용 | 구현량 | 작업 유실 위험 |
|---|---|---|---|
| A. CPU 항상 할당(최소 인스턴스 1과 함께) | 상시 CPU 과금으로 증가(콘솔 계산기로 확인) | 0줄(운영 설정) | 스케일인·배포·충돌 때만 |
| B. 응답 전에 동기 처리 | 증가 없음 | 중간 | 없음. 단 문서 등록이 수 초~수 분이라 응답 지연·타임아웃으로 부적합 |
| C. Cloud Tasks·Jobs + 원본 저장소 | 소액 + 저장소 | 큼(큐·GCS·상태 관리, 새 서비스 금지 조건과 충돌) | 가장 낮음 |
| D. 현행 + 수동 재검사 | 0 | 0 | 높음(요청이 올 때만 진행, 멈춘 사진은 15분 뒤 복구) |

  **권고**: MVP 는 A. A 를 못 쓰면 D 로 운영하되 "사진 분류는 앱을 열어 둔 동안 진행된다"고 안내한다. C 는 사용량이 늘 때 별도 설계. 운영 설정 변경은 이 작업에서 하지 않았다.

### 운영 전 확인 ② 모델 파일 배포와 SHA-256, NER 모델 확인 (운영 배포는 하지 않는다)
- **SigLIP2 산출물**: `siglip2_vision.onnx`(371,816,797 B, sha256 `52e01513b5b98b80056f10bcce72e9568e050070e296ea6d557afb5b06d61949`), `head.json`(241,529 B, sha256 `2a177cbe0fdd815447bcf2e089dbc96dbf906242e0d07d4c7831f90bd7bd8e87`). 이미지 빌드 때 `data/models/siglip2-onnx/` 로 `COPY` 하고 컨테이너 경로는 `/srv/data/models/siglip2-onnx`(작업 폴더가 `/srv`)다. 배포 파이프라인에서 `sha256sum -c`(모델 폴더의 `SHA256SUMS.txt`)로 확인하고 다르면 배포를 중단한다. 앱은 파일 해시를 매번 확인하지 않는다(372MB 읽기 비용).
- **운영 NER 모델 확인(비밀값을 출력하지 않는다)**: ① 배포 리비전의 이미지 주소만 조회한다(`gcloud run revisions describe <리비전> --format="value(spec.containers[0].image)"` — yaml 전체 출력은 환경변수가 섞이므로 쓰지 않는다). ② 그 이미지로 `docker run --rm --entrypoint sh <이미지> -c "sha256sum /srv/data/models/ner-koelectra-small-v2b/model.onnx; head -c 600 /srv/data/models/ner-koelectra-small-v2b/model_card.json"`. ③ 해시를 후보와 대조한다: `46210943c45f01b6…`(KLUE 10% 학습, 2026-10-27), `901642391c50f129…`(AI Hub 10% 학습, 2026-11-03). 이미지를 받을 권한이 없으면 이미지를 만든 PC 의 `data/models/ner…` 해시를 확인한다. 이 작업에서는 운영에 접근하지 못해 일치 여부를 **확인하지 못했다**(로컬 이미지는 `46210943…`).
- **기본 상태**: `PHOTO_CLASSIFY_SIGLIP=false`, `PHOTO_CLASSIFY_MODEL_DIR` 빈 값. 켜기 전에 모델 폴더가 없어도 서버는 정상 시작한다.

### 대기열 상한 (사진 바이트가 메모리에 있다)
- 가족당 20장(`PHOTO_QUEUE_LIMIT`)에 더해 **인스턴스 전체 40장·96MB**(`PHOTO_QUEUE_INSTANCE_LIMIT`·`_BYTES`, 사진 한 장 최대 8MB)를 넘으면 이번 사진은 건너뛴다(`pending` 으로 남아 15분 뒤 확인 필요·재검사로 복구). 직접 누른 "문서로 저장"은 버리지 않는다. 숫자는 시험으로 정했고 운영 실측으로 조정한다.

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
