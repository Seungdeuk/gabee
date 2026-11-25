# 평가 Runner 보안 위반 즉시 중단 — 구현 기록 (2026-11-25)

계획은 `agent-eval-runner-immediate-halt-plan.md`(docs 브랜치)에 있다. **#540·Main Agent 이중 호출 개선과 독립된 변경 단위**다(평가 도구만 바꾸고 운영 코드는 건드리지 않는다).

## 동작
- `RunOptions.stop_on_security`(기본 False, 실제 호출 `--real` 에서만 CLI 가 True). 켜면 case-run(반복 하나)이 끝나고 **기존 보안 판정**(`record.security_violations`: 금지 문자열·승인 없는 쓰기 시도 등)에 위반이 있으면 후속 case-run 을 시작하지 않는다. 새로 판정하지 않으므로 채점기·정답지·보안 판정은 그대로다.
- 일반 Task Success 실패(`answer_mismatch`·`missing_tool` 등)는 중단하지 않고 평가 결과로 남는다. 예산 중단(`halted`)은 기존 동작 그대로다(별도 `halt_kind` 로 섞지 않는다).
- 위반이 난 case-run 까지 보존한다: 끝난 사례는 `cases.jsonl` 등 기존 구조로 저장하고, 반복이 남은 사례(위반 사례)의 끝난 반복은 **지표 입력과 분리해** `halted_partial.jsonl`(행+궤적)에 저장한다. `runner_report.json` 의 반복 기록에는 위반 행이 그대로 있다.
- manifest(중단 실행에만): `halt_kind=security`, `halt_reason`, `halt_case_id`, `halt_repeat`, `runs_planned`, `runs_completed`, `runs_not_started`, `security_violations`, 그리고 기존 `cost_usd`·`calls`. 키는 모두 있거나 모두 없어야 하고 값은 검증된다(`store._check_halt`). `runner_report.json` 에 `security_halt` 객체, `summary.csv` 에 `runner.security_halted`·`runs_planned`·`runs_completed`·`runs_not_started` 행(중단 실행에만).
- 미실행 case-run 은 통과도 실패도 아니다(반복 기록·`counts()` 에 없다). 완료분 Task Success 와 전체 평가 상태(`security_halt`)는 따로 보인다. `all_counted_passed` 는 중단이면 False, CLI 종료 코드는 기존 `HALTED`(7)이고 남은 분할도 실행하지 않는다.
- 정상 완료 평가의 결과 파일 구조·집계는 그대로다(시험이 옵션 켠 깨끗한 실행과 끈 실행의 파일 목록·counts 가 같음을 확인).

## 한계(보장 범위)
보장은 **후속 case-run 차단**이다. 위반이 난 요청 안에서 이미 나간 모델·도구 호출은 막지 못한다(위반은 요청이 끝난 뒤 채점에서 나오므로 그 case-run 의 지출은 이미 발생). 승인 없는 일정 쓰기는 기존 `write_guard` 가 요청 중에도 막는다.

## 검증(실호출 0회)
`tests/agent_eval/test_security_halt.py`: 위반 뒤 가짜 모델 전송 0회·사용 기록 없음, 완료분 저장·위반 행 보존·manifest/report/summary 기록, 승인 없는 쓰기도 중단, 일반 실패는 계속, 옵션 끔=기존 동작, 깨끗한 실행의 파일 동일, 예산 중단 유지, manifest 키 검증, CLI 는 real 에서만 켬. 비용 게이트·채점기·정답지는 변경하지 않았다.
