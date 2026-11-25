# Agent 최대 출력 토큰 상한 (AGENT_MAX_OUTPUT_TOKENS)

2026-11-25 사용자 결정. 최종 dev108 통합 평가(B1·B2)에서 일정 Agent 호출이 출력 상한 1600 에서 잘려(`stop_reason=max_tokens` → `LLMUnavailable` → 503 `llm_failed`)
메인이 같은 Agent 를 반복 호출하고 단계 상한에 닿았다(7건, 전부 schedq-02·03). thinking 도 같은 출력 예산을 쓴다. 상한은 실제 사용량이 아니라 낼 수 있는 최대치다.

## 설정
- `apps/api/app/shared/config.py`: `agent_max_output_tokens: int = Field(default=10000, ge=1, le=128000)`, 환경변수 `AGENT_MAX_OUTPUT_TOKENS`.
- 상한 128000 은 현재 모델 `claude-haiku-5-5` 의 최대 출력이다(Models API `max_tokens` 확인, 2026-11-25). 범위 밖(0·음수·128001 이상·정수 아님)이면 서버가 시작할 때 설정 오류로 멈춘다.
- `apps/api/.env.example` 에 항목을 추가했다. 실제 값은 `apps/api/.env`(Git 제외)에 둔다. 개발용 `docker-compose.yml` 은 `AGENT_MAX_OUTPUT_TOKENS` 를 컨테이너로 넘기고(기본 10000),
  운영 배포(`deploy/`)는 이 PR 에서 건드리지 않았다: 환경변수를 주지 않으면 기본값 10000 이 적용되고, 바꾸려면 배포 환경변수에 추가한다.

## 적용 경로(모두 호출 시점에 `settings.agent_max_output_tokens` 를 읽는다)
| 경로 | 기존 | 위치 |
|---|---:|---|
| 메인 | 2048 | `ai_assistant/knowledge/rag_chat.py` |
| 메인 웹 검색 | 4096 | 같은 호출(웹 경로도 같은 값) |
| 소통 Agent | 2048 | `family_chat/agent.py` |
| 소통 Agent 대화 분석 | 4096 | `family_chat/ai_service.py` |
| 일정 Agent | 1600 | `schedule/agent/chat.py` |
| 정산 Agent | 1024 | `billing/agent.py` 가 `ask_agent(max_tokens=…)` 로 명시 |

## 바꾸지 않은 것
일반 `ANTHROPIC_MAX_TOKENS`(2048), `run_agent` 기본값 1024(돌봄 등 상한을 주지 않는 호출), 답 검증(2048), 일정 제안(2500), 답장 400·대화 주제 500, 통화 300, OCR·뉴스,
모델·effort·프롬프트·응답 스키마·단계 상한·타임아웃·개인정보·권한·쓰기 방어·PROJECT 비용 상한($40).

## 비용 게이트
- 호출 직전 검사(`usage.py`)는 원래 요청 본문의 `max_tokens` 로 최악 비용을 계산하므로 코드 변경 없이 10000 이 반영된다.
- 사전 점검(`evals/agent_eval/preflight.py`)은 `settings.anthropic_max_tokens` 만 보던 부분을 고쳤다: Agent 경로 본문은 허용 천장 `AGENT_OUTPUT_CEILING`(10000, 앱 기본값과 같은 값으로 고정하고 시험이 같은지 본다)까지 허용하고,
  답 검증 같은 Agent 경로 밖 본문은 일반 상한(2048)으로 본다. 환경변수로 천장보다 크게 올리면 본문 점검이 실패한다. 사전 거부 기준값은 Agent 상한(설정값)과 일반 상한 중 큰 값으로 계산한다(보수적).
- **승인액은 최대 사용 가능량 기준이라 커진다**(예: 입력 13k 토큰, 9 case-run 사전 거부 기준값 약 $0.28, 27 case-run 약 $0.85). 실제 지출은 실제 출력량에 비례한다.
  게이트를 풀지 않고 승인액을 올려야 한다. 예전 파일럿 $0.20 으로 9건을 시작하려던 시험은 거부되는 것이 맞아 상한 2048 구성으로 옮기고, 10000 에서는 거부됨을 확인하는 시험을 더했다.

## 기존 승인액·상한 시험을 올린 이유
Agent 요청 본문의 `max_tokens` 가 10000 이 되어 **호출 한 번의 최악 비용(입력 추정 + 출력 상한)이 약 $0.0053** 이 됐다(2048 일 때 약 $0.0011). 아래 시험은 "몇 번은 호출하고, 잔여 예산이 한 호출의 최악 비용보다 줄면 다음 호출 전에 멈춘다"를
보는데, 예전 값($0.0015·$0.0025)으로는 **첫 호출부터** 막혀 같은 동작을 볼 수 없었다. 게이트가 의도대로 더 일찍 막은 것이라, 게이트를 고치지 않고 시험의 상한만 새 최악 비용에 맞춰 올렸다(동작 검증은 그대로).
- `test_real_budget.py::test_only_calls_whose_worst_case_fits…`: $0.0015 → $0.006
- `test_cli.py::test_a_real_run_exhausting_the_approved_amount…`: $0.0015 → $0.0065
- `test_runner_budget.py::test_finished_cases_are_saved…`·`test_person_policy.py::test_a_budget_halt_is_counted…`: $0.0025 → $0.0065, 상한 탐색 시험은 훑는 범위를 넓힘
- 파일럿 9건 $0.20 시험: 10000 에서는 거부됨을 확인하는 시험으로 바꾸고, 예전 통과 동작은 상한 2048 구성으로 남김.
추가로 독립 확인: 첫 호출의 최악 비용을 못 감당하면 차단, 첫 호출 성공 뒤 잔여 부족 시 후속 차단, 실제 사용량 비용 집계, Agent 상한 변경 시 사전 거부 기준값 변경, 답 검증 2048 유지,
범위 밖 상한 유지, 비용 상한(RUN $2·BASELINE $5·LOOP $15·PROJECT $40) 불변.

## 성능 비교 시 유의
출력 상한 변경은 기존 기준선(bf3fb424)·최종 부분 평가(b669a036, 일정 Agent 1600)와 **실행 조건이 달라지는 변경**이다. 이후 비교에서 명시한다.
