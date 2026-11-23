# 0023. 로컬 OCR(RapidOCR)을 서비스에서 제거하고, 사진 분류는 SigLIP2 단독·문서 읽기는 Claude 만 쓴다

- 날짜: 2026-11-23
- 상태: 유효. [0015](0015-family-room-photo-to-library.md) 의 "판별은 로컬 OCR + Claude(haiku)" 부분을 대체한다(가족방 문서 사진을 문서함에 자동 등록한다는 큰 결정은 그대로).
- 결정(사용자):
  - **로컬 OCR 모델(RapidOCR PP-OCRv5 한국어)을 서비스에서 제외한다.** 사진 분류는 SigLIP2 ONNX, 문서 내용 추출은 Claude(`INGEST_LLM_OCR=true` 필수)가 한다.
  - 사진 판정은 **SigLIP2 margin > 5 → `document`, 아니면 `unsure`**(`failed` 는 점수를 못 낸 경우). 일반 사진을 자동으로 `photo` 로 확정하지 않는다(D-13). 임계값 5 는 평가의 `T_RESCUE` 를 재사용한 초기 기준이다.
  - **가족 AI 동의가 없으면 문서 이미지를 Claude 로 보내지 않는다.** 사진은 채팅에 남고 문서 자동 등록은 보류하며, 직접 저장·사진 직접 업로드는 403(`ai_consent_required`)이다. 글자를 외부로 보낸 뒤 마스킹하는 것으로는 동의 문제가 풀리지 않는다고 본다.
  - 사진 판별에 Claude 를 쓰던 `PHOTO_JUDGE_LLM` 은 쓰지 않는다(값 무시).
- 이유:
  - 로컬 OCR 은 사진 한 장에 6~200초가 걸리고 큰 이미지 메모리를 쥐어서, 2GiB·1 vCPU 에서 SigLIP2 와 함께 돌릴 때 동시 업로드로 OOM 이 났다(2026-11-23 로컬 Docker 시험: OCR+SigLIP2 동시 12장에서 OOMKilled 2회, OCR 만 쓰면 OOM 없음).
  - OCR 한국어 인식 모델은 패키지에 들어 있지 않고 첫 호출 때 외부(modelscope.cn)에서 내려받는다 — 외부망이 없으면 모든 사진이 실패한다.
  - 운영의 읽기·가리기가 이미 Claude 중심이라 로컬 OCR 은 사진 판별에만 남아 있었다.
- 감수하는 것:
  - 정확도 기준이 바뀐다. 공개 독립 Test 123장에서 문서 재현율 42/42 → 39/42(93%), 일반→문서 오분류 0/81 은 같다. 놓친 문서는 `unsure` 로 남아 업로더가 확인한다. **실제 한국어 문서·가족 사진은 평가하지 못했다.**
  - `PHOTO_CLASSIFY_SIGLIP` 가 꺼져 있으면 모든 사진이 `unsure` 가 되어 문서 자동 등록이 멈춘다(켜야 동작).
  - 동의 없는 가족의 문서 사진은 문서함에 자동으로 들어가지 않는다.
- 후속: ① 전체 회귀 확인 뒤 `rapidocr` 의존성 제거(이 PR 에서 별도 커밋), ② `photo_judge.judge`(OCR 판별)·`doc_ai.classify_photo` 미사용 코드 정리, ③ 운영 전 확인(요청 기반 CPU, 운영 NER 모델 해시, 동의 문구·처리방침) — [구현 현황](../features/ai_assistant-ingest.md).
