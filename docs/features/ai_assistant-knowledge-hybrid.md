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

## 한 문서 안에서만 찾기(search_knowledge item_id)

- 구현됨: `search_knowledge` 에 선택 인자 `item_id` 를 추가했다. 주면 그 기록의 조각 안에서만 같은 하이브리드(임베딩 후보 + TF-IDF) 순위로 찾아 `top_k`(기본 5, 최대 8)개를 쪽 순서가 아니라 순위 순으로 돌려준다(`service.search_in_item`, `repository.search_chunks(item_id=)`, 후보는 문서 조각 전부 최대 300). 결과 모양은 기존과 같고 `more` 는 없다.
- 그룹 격리: `search_chunks` 가 항상 `group_id` 로 거르므로 다른 그룹·없는 `item_id` 는 빈 결과와 안내가 나온다. 민감 기록은 `include_sensitive=False` 이면 빈 결과다. 이 모드에서는 `kind_label`·날짜·`member` 필터는 쓰지 않는다.
- 배경: 모델이 낱말을 바꿔 검색해도 긴 문서 뒤쪽 정답이 안 나오고 `get_item` 은 앞 12,000자만 주던 문제. `get_item` 절단 안내와 시스템 프롬프트 한 줄이 `item_id` 로 다시 찾도록 안내한다.
- 시험: `knowledge/tests/test_search_in_item.py`. 서버 API(openapi) 변경 없음(채팅 도구 정의만 바뀜).

## 기권 초안 뒤 강제 재검색(chat_retry_not_found)

- 구현됨(기본 꺼짐, 설정 `chat_retry_not_found`, 평가에서만 환경변수로 켬): 프롬프트 한 줄로는 모델이 `item_id` 검색을 쓰지 않아서, 코드가 단계를 강제한다. 문서 검색(search_knowledge/get_item)만 쓴 답의 초안이 `rag_chat.NOT_FOUND_DRAFT`("찾지 못", "확인되지 않", "확인할 수 없" 등, 500자 이하)에 맞고 이 대화에 search_knowledge 결과가 있으면, 결과의 서로 다른 상위 3개 기록 안을 원래 사용자 질문으로 다시 찾아(기록마다 상위 3조각, 합쳐서 6,000자 상한) 도구 결과 형식으로 모델에 주고 한 번 더 답하게 한다(최대 1회, 도구 없이 답만, 모델 호출 +1). 두 번째 답도 기권이면 그대로 최종 답이다. 호출 실패·빈 답이면 초안을 쓴다.
- 기권이 아닌 초안, 웹 검색·탭 에이전트를 쓴 답, 설정이 꺼진 경우는 기존과 같다. 검색은 `tools.search_knowledge(item_id=)` 를 거쳐 `group_id` 로 거르므로 다른 그룹 기록은 들어가지 않고, 새로 외부로 나가는 데이터는 없다(같은 LLM 호출 안에서 같은 그룹 기록만 쓴다). 재검색 뒤 답도 기존 verify 단계를 그대로 거친다.
- 평가 기록: `AskResult.tool_calls` 에 `retry_search` 가 남아 `eval/rag/answer_eval.py` 의 `tools` 목록에서 실행 여부를 알 수 있다(harness 수정 없음).
- 시험: `knowledge/tests/test_retry_not_found.py`.

## 답 최대 출력 토큰은 2048 그대로, 대신 답을 핵심 위주로 짧게 (2026-11-18)

- 답이 중간에 끊기거나 글 없이 끝나는 원인은 2048 토큰 상한을 모델의 숨은 생각이 다 쓰는 것이다(빈 답 재현: stop_reason=max_tokens, 생각 블록만 옴). 상한을 3072 로 올리면 해소되지만(15라운드 잘림·빈 답 0건), 사용자 결정으로 2048 로 되돌리고 답을 핵심 위주로 짧게 쓰게 했다(프롬프트 한 줄 추가).
- 답이 길고 장황하다는 지적: dev 답 글자 수 중앙값 342자(정답표 중앙값 142자), 29/170은 제목, 59/170은 목록이 있었다.
- 빈 답 재시도(모델이 글 없이 끝나면 한 번 더 묻기)는 항상 켜져 있고, 기권 초안 재검색(`chat_retry_not_found`)은 기본 꺼짐이다.
