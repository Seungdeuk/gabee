# 문서 검색 섞기(임베딩 + 글자 TF-IDF)

- 담당: knowledge 검색. 결정 기록은 `docs/adr/0019-hybrid-document-search.md`.
- 구현: `apps/api/app/features/ai_assistant/knowledge/hybrid.py`(글자 2·3개 묶음 TF-IDF, RRF), `service.search`(후보 가져오기 → 섞기 → 기록당 대표 조각).
- 설정(`app/shared/config.py`): `chat_hybrid_search`(기본 true), `chat_hybrid_candidates`(100), `chat_hybrid_text_weight`(1.0).

## 오프라인 측정(2026-11-10, dev, API 비용 0, `eval/rag/hybrid_candidates_check.py`)

공개 PDF(OCR 색인, 문항 209): 정답 문서·쪽(대표 조각 기준) Hit@k, %

| 방식 | 문서 Hit@1 | 문서 Hit@3 | 쪽 Hit@1 | 쪽 Hit@3 |
| --- | --- | --- | --- | --- |
| 임베딩만(지금) | 85.6 | 93.8 | 55.5 | 59.8 |
| 전체 조각 섞기(실험 상한) | 92.8 | 95.7 | 67.9 | 68.9 |
| 후보 50 | 90.9 | 95.7 | 64.1 | 66.0 |
| 후보 100(채택) | 90.4 | 95.7 | 64.1 | 67.0 |
| 후보 200 | 90.9 | 95.7 | 65.1 | 67.5 |

가족 v2(문항 354): 정답 문서 Hit@1 / Hit@3: 임베딩 95.5 / 98.6, 전체 섞기 96.6 / 99.4, 후보 50·100·200 은 96.0·95.8·96.0 / 99.4.

성능: 질문당 TF-IDF 계산(후보 100, 조각이 긴 공개 PDF) 첫 계산 약 32ms, 같은 조각이 캐시된 뒤 약 14ms(후보 200은 약 27~70ms).

## 동작 메모

- `Hit.score` 는 임베딩 코사인, 결과 순서는 섞은 순서다. `hybrid=False` 로 부르면 예전처럼 점수 순이다(첫 호출 검색 강제가 이렇게 부른다).
- 필터(가족·종류·날짜·민감)와 `per_item`, 임베딩 모델 불일치 제외는 후보를 가져오는 `repository.search_chunks` 에서 그대로 적용된다.
- 후보 안에 글자가 하나도 겹치지 않으면 임베딩 순서 그대로다.
- 남은 일: 임베딩 모델을 바꾸면 후보 수·효과 재측정. 평가 스크립트는 현재 작업 폴더가 `apps/api` 일 때만 임베딩 모델 파일을 찾는다(`eval/rag` 안에서 돌리면 다른 벡터가 나온다).
