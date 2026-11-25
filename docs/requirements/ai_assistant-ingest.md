# 기능: AI 비서 정제화 (ai_assistant-ingest) — 원본 전처리 · 자동 분류

> **2026-11-26 갱신:** 로컬 OCR(RapidOCR)은 서비스에서 제거했고 가족방 사진 판별은 로컬 SigLIP2 단독이다([ADR 0025](../adr/0025-local-ocr-removed-siglip-only-photo-judge.md)). 가족 채팅방 자동 처리의 외부 AI 전송은 가족 AI 동의가 있을 때만이다([ADR 0024](../adr/0024-family-chat-external-ai-consent.md)). 이 문서에서 로컬 OCR·Claude 사진 판별(PHOTO_JUDGE_LLM)을 현재 동작처럼 적은 부분은 그 이전 기록이다.

브랜치: `ai_assistant-ingest` · 서버 폴더: `apps/api/app/features/ai_assistant/ingest/`
다음 단계(데이터화·벡터 DB)는 `ai_assistant-knowledge` 가 맡는다. 이 기능은 그 앞까지다.

## 목적
가족이 올린 파일(사진 외 다른 형식 포함)을 **검색할 수 있는 글자와 정보로 정제**해서 넘긴다.
- 사진 이외 확장자도 받아서 글자로 바꾼다(나중에 언제든 검색 가능하게).
- 분류를 **미리 정한 목록이 아니라 자동으로** 붙인다(처음 보는 문서 종류도 이름을 붙인다).
- 결과는 knowledge(벡터 DB·데이터화)가 그대로 가져다 쓸 수 있는 한 가지 모양으로 저장한다.

```
업로드 ─▶ ① 원본 전처리: 형식 확인·깨진 파일 거르기 → 회전·크기 맞추기 → 글자로 바꾸기 → 구조(제목·표·쪽) 살리기
       ─▶ ② 자동 분류:  문서 종류(자유 문구)·태그·날짜·사람·금액·장소 추출, 종류별 폼 칸, 화면 이동 값(route)
       ─▶ 처리 결과 저장 ─▶ (knowledge) 조각내기·임베딩·검색
```

## 화면
- 이 기능은 서버 처리다. 앱 화면은 바꾸지 않는다.
- 앱이 쓰는 값: 업로드 뒤 처리 상태(`status`)와 결과(`route`, `doc_type`, 폼 칸). 사진 확인 화면 연동은 앱 담당과 별도 협의.

## API
기존 `POST /ai-assistant/photos` (사진 업로드)를 넓히거나 옆에 새로 둔다(미정 4).

| 메서드 | 경로 | 하는 일 |
|---|---|---|
| POST | `/ai-assistant/files` | 파일 업로드 → 받음(`received`) 응답 후 백그라운드로 전처리·분류 |
| GET | `/ai-assistant/files/{file_id}` | 처리 상태와 결과(아래 "처리 결과") |
| POST | `/ai-assistant/files/{file_id}/review` | 사람이 종류를 고침(`needs_review` → `analyzed`) |
| POST | `/ai-assistant/files/{file_id}/reprocess` | 분류 개선 후 다시 처리 |

모든 요청은 `current_user` + `current_group_id` 를 거치고, 다른 가족 그룹의 파일은 보이지 않는다.

### 처리 결과 (knowledge 에 넘기는 모양)
```json
{
  "file_id": "a1b2c3d4e5f6",
  "group_id": "g01",
  "status": "analyzed",
  "source": {"filename": "가정통신문.pdf", "content_type": "application/pdf", "size": 482113, "sha256": "…"},
  "content": {
    "text": "# 현장체험학습 안내 …",
    "blocks": [{"type": "heading", "level": 1, "text": "현장체험학습 안내", "page": 1}],
    "pages": 2
  },
  "classification": {
    "doc_type": "학교 가정통신문", "route": "document", "confidence": 0.92,
    "tags": ["학교", "현장체험학습"], "people": ["지민"], "dates": ["2026-10-15"],
    "amounts": [{"label": "버스비", "value": 12000}], "places": ["OO초등학교"],
    "fields": {"제출 기한": "2026-10-20"}
  },
  "quality": {"status": "ok", "warnings": []},
  "processor_version": "ingest/2"
}
```

## 데이터
- `photos`(기존) → 사진뿐 아니라 파일 전반으로 쓸지, 새 표 `files` 를 둘지 미정(미정 4).
- 새 표 `ingest_results` (파일 하나당 한 줄): `file_id`, `group_id`, `status`(received/analyzed/needs_review/failed), `content`(JSON), `classification`(JSON), `quality`(JSON), `processor_version`, `processed_at`.
- 원본 파일은 `DATA_DIR` 아래(운영은 Supabase Storage, 미정 5). 같은 `sha256` 은 다시 처리하지 않는다.
- 스키마 변경은 `supabase/migrations` 에 SQL 로, `docs/contracts/db.md` 갱신.

## 개인정보 (담당자 결정 2026-10-22)

> **개정 (2026-11-04, 회의 결정, [ADR 0014](../adr/0014-upload-llm-ocr-masking.md)).** 아래의 "어떤 모델에도 보내지 않는다"는 개인정보가 외부 API 로 나가는 것을 막으려던 규칙이었다. 회의에서 외부 API(Claude)로 나가는 내용은 사용자 공지로 처리하고 **우리 DB 에 저장되는 내용만 보호**하기로 해서 이 규칙은 더 적용하지 않는다. 설정 `INGEST_LLM_OCR`·`INGEST_LLM_MASK` 를 켜면: ① 문서 종류와 상관없이 Claude 가 문맥으로 이름·개인 주소·번호를 가린다(사업장 주소·행정구역은 남김). ② 처방전도 Claude 로 읽고 가린다. 설정은 기본 꺼져 있고, 아래 내용은 설정이 꺼진 기존 동작이다.
- 원본은 **원본 데이터 센터**에 그대로 보관하고 접근을 제한한다. DB·검색·다음 단계로는 **가린 글자만** 넘긴다.
- 가리는 것 (담당자 결정 2026-10-22): **처방전·신분증(주민등록증·외국인등록증·운전면허증·여권)·통장·가족관계증명서**는 개인정보를 모두 가린다(이름·전화·카드·계좌·이메일·주소, 처방전은 병명 코드·면허번호, 신분증은 면허·여권 번호와 영문 이름, 통장은 라벨 없는 계좌번호, 가족관계증명서는 가족 이름·출생연월일·등록기준지). **그 밖의 문서는 주민등록번호만** 가린다. 가린 뒤 신분증·통장·가족관계증명서는 분류(Jev, 없으면 로컬)로 보내고, **처방전은 어떤 모델에도 보내지 않는다.**
- 분류는 가린 뒤에, 가린 글자로만 한다. 파일 이름도 분류기에 넣지 않는다(이름이 들어 있을 수 있음). 외부(Jev)로는 가린 글자와 날짜·금액 후보만 나가고, 처방전·고지서·영수증은 나가지 않는다(미정 1 참고).

## 완료 조건
- [ ] 사진(JPEG·PNG·HEIC), PDF, 워드(docx), 엑셀(xlsx), 텍스트를 올리면 `content.text` 와 `blocks` 가 채워진다.
- [ ] 영수증·고지서·처방전 사진은 `doc_type` 이 맞고 `fields`(가게·금액·날짜 / 금액·납기일 / 처방일·약)가 채워진다.
- [ ] 미리 정한 목록에 없는 문서(예: 가정통신문)도 `doc_type`·`tags` 가 붙는다.
- [ ] 깨진 파일·지원 안 하는 형식은 `failed` 와 이유를 남기고 서버가 멈추지 않는다.
- [ ] 확신이 낮으면 `needs_review`, 사람이 고르면 `analyzed`.
- [ ] 다른 가족 그룹의 파일은 조회되지 않는다.
- [ ] 테스트는 가짜 OCR·가짜 분류기로 돌아간다(CI 는 GPU·모델 없음). `ruff check`, `ruff format --check`, `pytest` 통과.

## 미정
1. **자동 분류에 쓸 AI**: (담당자 결정 2026-10-22) **사진 종류 판별은 로컬 모델(CLIP)**. **분류는 반드시 마스킹 뒤에 가린 글자로만** 한다(파일 이름도 넣지 않음). 가린 글자의 문서 종류는 **Jev(TypeSafe)** 가 목록에서 고르고(종류·문서인지·분야·기한·주요 금액), 목록에 없는 종류는 로컬 언어 모델(qwen2.5:7b)이 이름을 붙인 뒤 사람이 확인한다. Jev 키가 없거나 호출이 실패하면 로컬 언어 모델로 대신한다. **처방전·고지서·영수증은 규칙으로 정해 어떤 모델에도 보내지 않는다.** 남은 미정: 로컬 CLIP 의존성(torch) 추가 승인, Jev 비용(입력 토큰 과금)·팀 키 관리.
2. **추가 라이브러리 승인**: 1·2단계 구현에 `pillow`, `pillow-heif`, `rapidocr`+`onnxruntime`, `markitdown[docx,xlsx,pptx,pdf]` 를 `apps/api/pyproject.toml` 에 **제안으로 넣었다**(모두 MIT/Apache-2.0, 로컬 처리). PR 리뷰에서 승인받아야 한다. 무거운 `docling`(torch 포함, 스캔·복잡한 PDF)은 v2 로 미룸.
3. **지원 형식 범위**: 한글(hwp)·음성 파일을 이번에 넣을지.
4. **업로드 통로**: 기존 `/ai-assistant/photos` 를 넓힐지, `/ai-assistant/files` 를 새로 둘지. `photos` 표를 쓸지, `files` 표를 새로 둘지.
5. **원본 보관 위치와 기간**: 로컬 `DATA_DIR` / Supabase Storage.
6. **knowledge 와의 경계**: 사용자가 데이터화·벡터 DB 를 같은 담당으로 합친다고 했다. README 의 브랜치 구분(`ai_assistant-knowledge`)과 맞춰야 한다.
