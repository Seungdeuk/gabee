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
가린 글자 ─▶ 규칙(처방전·고지서·영수증) ─▶ 끝 (어떤 모델에도 안 보냄)
          └▶ 그 밖 ─▶ Jev 한 번 호출 (가린 글자 + 코드가 찾은 날짜·금액 후보)
                       doc_type    choice  문서 종류 22개 + none
                       is_document noul    챙길 문서인가 → document / daily_share
                       domain      choice  분야 9개 → 태그
                       deadline    choice  날짜 후보 중 마감일 (후보 있을 때만)
                       main_amount choice  금액 후보 중 주요 금액 (후보 있을 때만)
                     ├ none        ─▶ 로컬 qwen 이 이름 붙임 + 사람 확인
                     ├ 확신 0.6 미만 ─▶ 사람 확인
                     └ 실패·키 없음 ─▶ 로컬 qwen (아래)
```
- Jev 는 글을 만들지 않고 고르기만 한다 → 날짜·금액은 코드가 후보를 찾고 Jev 가 "어느 것이 마감일인지" 고른다. 확신도가 측정된 확률이라 qwen 의 자기 신고(늘 1.0)보다 믿을 만하다.
- `app/shared/llm/jev.py`(`ask`, httpx 로 `POST https://api.typesafe.ai/v1/systemone`, 새 라이브러리 없음). 설정 `TYPESAFE_API_KEY`, `JEV_MODEL`(기본 `jev-latest`).
- 테스트는 가짜 Jev. 개발자 `.env` 에 키가 있어도 테스트는 진짜 Jev 를 부르지 않는다.

### 로컬 언어 모델 분류 (Jev 대체 경로)
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

얼굴은 생체정보라서 이번 범위에서 뺐고, 코드(`faces.py`)와 테스트, 설정(`FACE_MODEL_DIR`·`FACE_ENABLED`)을 지웠다(사용자 결정, ADR 0007). 필요해지면 깃 이력에서 복구한다. `PreprocessResult.people` 도 없어졌다.

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

## 남은 것
- 업로드 통로·DB 저장(`photos` 확장 또는 `files` 표)·백그라운드 처리 연결 — 요구사항 미정 4·5
- 스캔 PDF 쪽별 OCR, 복잡한 표 PDF(Docling) — v2
- 한글(hwp·hwpx)·음성 — v3, 요구사항 미정 3
- 사진 모양 분류(로컬 CLIP) — family 코드에서 옮기기 (torch 의존성 승인 필요)
- 문서 종류 이름 묶기("가정통신문"·"학부모 안내문" → 하나), 확신도를 모델 자기 신고 대신 측정값으로
- 쪽·슬라이드별 점검으로 빠진 쪽 찾기 → 빠진 쪽만 OCR
- OCR 후처리(숫자 오타 교정 "6O,OOO" → "60,000")는 자동 분류의 폼 채우기 단계에서
- 실제 한국 문서(가정통신문 PDF, 관리비 엑셀 등)로 형식별 3~5개 품질 측정
