# 0025. 로컬 OCR(RapidOCR)을 서비스에서 제거하고, 가족방 사진 판별은 로컬 SigLIP2 단독으로 한다

- 날짜: 2026-11-26
- 상태: **결정됨(사용자 2026-11-26).** 코드 변경은 이 ADR 의 PR 이 한다. **운영 활성화(`PHOTO_CLASSIFY_SIGLIP=true`)는 별도 승인 대상**이다.
- 근거 자료: Draft PR #520(참고용, 병합하지 않음)의 B(로컬 OCR 제거)·C(SigLIP2 단독 판정) 변경과 ADR 초안. 이 ADR 은 그중 B·C 만 옮긴다.
  가족 AI 동의(외부 전송 통제)는 [0024](0024-family-chat-external-ai-consent.md) 가 정한다(#520 의 처리 목적·`external` 인자 구현은 옮기지 않았다).
- 대체 관계(역사 기록은 그대로 두고 이 ADR 이 대체한다):
  - [0015](0015-family-room-photo-to-library.md) 의 "판별은 로컬 OCR(+ 동의한 가족은 Claude haiku)" → 로컬 SigLIP2 단독. Claude 사진 판별(`PHOTO_JUDGE_LLM`·`PHOTO_JUDGE_MODEL`)은 지웠다.
  - [0014](0014-upload-llm-ocr-masking.md) 의 "Claude 가 실패하거나 꺼지면 로컬 OCR 로 읽는다" → 로컬 OCR 대체 경로 없음(읽을 수단이 없으면 실패).

## 결정
1. **로컬 OCR(RapidOCR PP-OCRv5 한국어)을 서비스에서 완전히 제거한다.** 코드(`converters.KoreanOcr`·`default_ocr`·줄 묶기)와 의존성(`rapidocr`)을 지웠고, 첫 호출 때 외부(modelscope)에서 모델을 내려받던 경로도 없어졌다.
2. **문서 글자 추출은 Claude 로만 한다**(`INGEST_LLM_OCR=true` 가 서비스에서 필수). 꺼져 있으면 사진·글자 없는 스캔 PDF 는 `ocr_unavailable` 로 실패한다(빈 자리표시 기록을 만들지 않는다).
3. **가족방 사진 판별은 로컬 SigLIP2 ONNX 단독**이다: margin > 5 → `document`, 아니면 `unsure`, 점수를 못 구하면 `failed`. **`photo` 는 만들지 않는다**(D-13). 사진을 외부로 보내지 않는다.
   - 가중치·문장·전처리·임계값은 바꾸지 않았다. 5 는 공개 데이터 독립 평가(exp-1)의 `T_RESCUE` 를 재사용한 값이다.
   - `PHOTO_CLASSIFY_SIGLIP` 이 꺼져 있으면 판별 수단이 없어서 모든 사진이 `unsure` 다(문서 자동 등록이 멈춘다).
4. **배포**: 모델(`siglip2_vision.onnx` sha256 `52e01513b5b98b80056f10bcce72e9568e050070e296ea6d557afb5b06d61949`, `head.json` sha256 `2a177cbe0fdd815447bcf2e089dbc96dbf906242e0d07d4c7831f90bd7bd8e87`)은
   저장소에 없고, 빌드하는 PC 의 `apps/api/data/models/siglip2-onnx/` 에 두면 Dockerfile 이 해시를 검증한 뒤 이미지에 넣고 `PHOTO_CLASSIFY_MODEL_DIR` 을 정한다(다르면 빌드 실패, 없으면 경고 후 모델 없이 빌드).
   서버는 시작할 때 `photo model status=present|missing|not_configured` 를 로그로 남긴다(모델 없는 이미지를 정상 배포로 오인하지 않게).
5. **메모리 보호**: 사진 판별 대기열에 인스턴스 전체 상한(40장·96MB)을 둔다(가족별 20장 상한에 더해).

## 이유
- 로컬 OCR 은 사진 한 장에 6~200초가 걸리고 큰 이미지 메모리를 쥐어서, 2GiB·1 vCPU 에서 SigLIP2 와 함께 돌릴 때 동시 업로드로 OOM 이 났다(2026-11-23 로컬 Docker 측정: OCR+SigLIP2 동시 12장에서 OOMKilled 2회, OCR 을 뺀 뒤 0회. 합성 이미지·n=1·Cloud Run 아님, #520 기록).
- OCR 한국어 인식 모델은 패키지에 없고 첫 호출 때 외부에서 내려받는다(외부망이 없으면 모든 사진이 실패).

## 감수하는 것·잔여 위험
- **정확도 기준이 바뀐다.** 공개 독립 Test 123장(문서 42·일반 81)에서 margin > 5: 문서 39/42(재현율 93%)·일반→문서 0/81. 이전 단계형(OCR+SigLIP2)은 42/42·0 이었다.
  놓친 문서 3장(margin 2.14·2.89·3.21)은 `unsure` 가 된다. **실제 한국어 문서·실제 가족 사진으로는 평가하지 않았다**(합성 한국어 문서의 margin 이 5.48~6.55 로 기준 바로 위에 몰려 있다).
- **margin ≤ 5 는 "일반 사진"이라는 보장이 아니다**(문서를 놓칠 수 있다). 그래서 `unsure` 를 자동으로 공개하는 정책은 이 ADR 이 정하지 않는다(타임라인은 [0026](0026-date-timeline-vs-ai-memory.md)).
- 문서 자동 등록은 가족 AI 동의가 있을 때만 Claude 로 읽는다(0024). 동의가 없으면 판별 상태(`document`)만 남고 등록은 보류된다.

## 운영 활성화 조건(별도 승인)
- 모델 포함 이미지(해시 일치)와 `PHOTO_CLASSIFY_SIGLIP=true`·`INGEST_LLM_OCR=true` 를 **같은 리비전**으로 배포한다.
- 운영 `INGEST_LLM_MASK` 값 확인(꺼져 있으면 0024 에 따라 채팅 문서 등록이 막힌다), Claude 읽기 비용·한도 확인, 실제 한국어 문서로 확인 필요 비율을 다시 본다.
