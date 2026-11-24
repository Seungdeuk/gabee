# R11 NER 운영 교체 — 배포 담당자 인계 (2026-11-24)

**운영 상태: `READY_FOR_DEPLOY` 가 아니라 `BLOCKED` 로 본다.** 코드·이미지·비운영 검증은 끝났고, 운영 확인값(S4-1·S4-2·S4-6)과 운영 자원 조건 Docker 재현 S2b 는 통과했다. 남은 것은 Cloud Run 후보 리비전 검증, 이전 리비전 보존 확인, 위험 수용 서명, 배포 담당자 승인이다. 이 문서와 PR 은 운영 배포 승인이 아니다.
표시: 자동 검증 기반 · 사람 검수 미실시 · 합성 데이터 평가. 결정 배경은 `docs/adr/0023-ner-r11-replacement.md`.

## 1. 무엇을 바꾸나

| | 기존 S0 | 새 R11 |
|---|---|---|
| 모델 | koelectra-small-v2b | KoELECTRA-small B-new seed 21 (epoch 5) |
| `model.onnx` SHA256 | `46210943c45f01b6a9fa500894fb9821b1c130be63de8d8f7ef603d2d87ccf8e` | `3831601b7ffb6093a8d1b8c832e46ad140712c6e402f17b3054c3ec0f9ae4c94` |
| 지문(`ner_status()`) | `46210943c45f` | `3831601b7ffb` |
| 이미지 안 폴더 | `/srv/data/models/ner-koelectra-small-v2b` | `/srv/data/models/ner-koelectra-small-r11b-s21` |
| `PRIVACY_NER_MODE` | 이미지 기본값 없음(코드 기본 `auto`, 운영 실제 값은 **미확인**) | 이미지에 `required` 고정 |
| `PRIVACY_NER_MODEL_FILE` | `model.onnx` | `model.onnx` (`model.int8.onnx` 는 쓰지 않는다) |

R11 폴더 4개 파일의 SHA256(확정값, Dockerfile 이 빌드 때 검사한다):

| 파일 | SHA256 |
|---|---|
| model.onnx | `3831601b7ffb6093a8d1b8c832e46ad140712c6e402f17b3054c3ec0f9ae4c94` |
| tokenizer.json | `d5c7a9a8996aca4fee55a3664381b012bd7dbb3e190061b2591c02502b7171b6` |
| labels.json | `f5cf8bd55bf4c31df0da444131a7b68ff0ace3e482ca7dad6e2f55f3fd216fe4` |
| model_card.json | `0157e8bf854e3b492adead91332526ff09c4f2381208d711f9d7c3429ac2cc74` |

tokenizer·labels 는 S0 와 바이트 동일하다. `model_card.json` 의 `name` 은 옛 이름 `koelectra-small-v2b` 그대로이므로 폴더 이름과 지문으로 구분한다.

## 2. 모델 파일을 어디서 가져오나

모델은 Git 에 없다(`apps/api/data/` 는 `.gitignore`). 이 작업을 한 PC 의 아래 폴더가 확정본이다.

`C:\Users\403\venvs\ner-runs\r11\export\r11-B-s21-ep5` (4개 파일: model.onnx, tokenizer.json, labels.json, model_card.json)

빌드하는 PC 에서 `apps/api/data/models/ner-koelectra-small-r11b-s21/` 로 복사한 뒤 SHA256 을 위 표와 비교한다. 다르면 빌드하지 않는다(Dockerfile 이 빌드를 실패시킨다). 같은 폴더 안 다른 `r11-B-*` 폴더(다른 시드·에폭)는 모델 크기가 같아 눈으로 구분되지 않으니 해시로만 확인한다.

## 3. 변경 파일

| 파일 | 변경 |
|---|---|
| `apps/api/Dockerfile` | NER 폴더·`MODEL_FILE`·`MODE=required`, 빌드 때 4개 파일 SHA256 검사 |
| `apps/api/scripts/check_ner_deploy_mode.py` (+ test) | 배포 전 게이트: 운영 설정이 `required`·기대 폴더·기대 지문이 아니면 종료 코드 1 |
| `docs/security/NER_R11_OPS_*.md` 4개 | 런북·확인표·명령 모음·위험 수용 결정서(서명 전) |
| `docs/security/r11_validation/ops_final/` | 이번 비운영 검증 증거 |
| `docs/adr/0023-…`, `docs/adr/README.md` | 결정 기록 |

서비스 코드(`app/`)는 바꾸지 않았다. 가명화 규칙·PERSON/ADDRESS 정책·고위험 탐지·대응표 저장·복원·API 계약은 그대로다.

## 4. 빌드·배포 순서

런북 `NER_R11_OPS_CLOUDRUN_RUNBOOK.md` 를 따른다. 단 런북 2절 1번의 `stage_build_context_nonprod.sh` 는 저장소에 없으므로 이 문서 2절의 복사·해시 확인으로 대체한다. 병합된 `release/1.4` 커밋으로 빌드하고 고유 태그와 digest 를 기록한다. 이전 리비전·이미지는 삭제하지 않는다.

## 5. 이번에 한 검증 (개발 PC Docker, 운영 아님)

이미지: `gabee-api:r11-nonprod`(R11), `gabee-api:s0-rollback-nonprod`(S0 롤백용). 둘 다 위 Dockerfile(S0 쪽은 `release/1.4` 원본)로 같은 PC 에서 빌드했다.

| 검증 | 결과 |
|---|---|
| 빌드 중 해시 검사 | 4개 파일 OK. 파일 1바이트 변조 시 `FAILED`, 종료 코드 1(빌드 실패) |
| 이미지 안 설정 | `PRIVACY_NER_MODEL_DIR`·`MODEL_FILE=model.onnx`·`MODE=required`, 컨테이너 `sha256sum` = 확정값 |
| `ner_status()` | `{"mode": "required", "active": true, "fingerprint": "3831601b7ffb"}` |
| 서버 부팅 | `/health` 200, 기동 약 47초(모델 로드 포함, 개발 PC) |
| 롤백 시험 | R11 컨테이너 제거 → S0 이미지 기동, `/health` 200, 전환 약 8.9초, 지문 `46210943c45f` 로 복귀 |
| fail-closed 8가지(`--network none`, 연결 시도 계수) | 아래 표. 전부 차단, 연결 시도 0 |
| 개인정보·NER 단위 시험(R11 실모델 사용) | 586 통과 / 3 건너뜀(실모델 없는 환경용), 실모델 51건 통과 |
| 서비스 회귀(소통·AI 도우미·일정·가계·주간 뉴스·개인정보·보안·멤버십, `required` + R11) | **3,677 통과, 9 xfail(기존 예상 실패), 실패 0** |
| `check_ner_deploy_mode` 시험 | 20 통과. 이미지 지문 증명(`--image-status-json`)이 **없으면 설정이 required 여도 실패**(처음 버전은 설정만으로 통과하던 허점이라 고쳤다). 지문·active·mode 중 하나라도 틀리면 실패. `--config-only` 는 참고 점검이며 통과해도 종료 코드 3 |
| 실제 HTTP 응답 | `weekly_news` 생성 라우트에서 실제 `ner` 모듈을 required + 모델 없음으로 두고 호출: **HTTP 503 `privacy_unavailable`, LLM 호출 0건, DB 행 없음**(`test_required_ner_down_is_real_http_503_and_never_calls_the_llm`). 모드를 `auto` 로 바꾸면 이 시험이 실패하는 것도 확인했다. 컨테이너 시험의 `status_code: null` 은 가명화 입구 예외만 본 값이다 |
| `ruff check` / `ruff format --check` (apps/api) | 통과 |

fail-closed 케이스(`ops_final/failclosed_results.json`): ONNX 없음, 해시 불일치, tokenizer 손상, labels 불일치(카드 해시 갱신 후), ONNX 로딩 실패(손상 파일), 로드 이후 추론 예외, 시간 상한 초과, 동시 추론 상한. 모두 가명화 입구가 `PrivacyUnavailable`(503 `privacy_unavailable`)이고 소켓 connect 시도는 0건이다. 정상 케이스는 통과하고 원문 이름·전화번호가 가명화 결과에 남지 않았다.
이 시험은 가명화 입구에서 외부 호출 이전에 막히는 것을 본 것이다. 이전에 보고된 "503 이후에도 Claude 호출" 재현은 가명화 입구 기준으로 나타나지 않았다. 실제 서비스 라우트·실 LLM 경로에서 같은 결과인지는 후보 리비전에서 확인해야 한다(런북 4절).

### S2b — 운영 자원 조건을 Docker 로 재현한 교차 측정 (2026-11-24)

**판정: S2b-Docker PASS (사전 등록 기준 그대로). Cloud Run 자체 측정은 하지 않았다 — 아래 한계 참고.**

운영 확인값(담당자가 Cloud Run 리비전 `gabee-00022-faj` 에서 직접 확인): 1 vCPU, 2GiB, Cloud Run 요청 동시성 80, `PRIVACY_NER_MODE=required`, `PRIVACY_NER_THREADS`·`PRIVACY_NER_MAX_CONCURRENCY`·`MODEL_DIR`·`MODEL_FILE` 환경변수 없음(코드 기본값 스레드 2·NER 동시 추론 2). 운영 이미지 digest `sha256:1d8208076f6ae34f9d192077860784d14945b5dd63060d6979a65b15288cac78` 에서 S0 해시 `46210943c45f01b6…`·`ner_status()` required·active·지문 `46210943c45f` 확인(담당자 Cloud Shell 확인 값, 이 PC 에서 재확인한 것이 아님).

측정 조건: `docker run --cpus 1 --memory 2g --network none`, `PRIVACY_NER_MODE=required`(S0·R11 모두), 스레드·동시성은 환경변수 없이 코드 기본값, ONNX Runtime 1.32.0(Python 3.12). S0·R11·R11·S0·S0·R11 순서로 컨테이너 6회(사전 등록 교차 순서), 모델별 3회 중앙값. 문장은 개발 검증셋 `r11_val`(봉인 평가셋 아님), 문장 캐시는 끔. 도구·원자료: `ops_final/s2b_ops/`(`s2b_ops_bench.py`, `run*.json`, `s2b_ops_summary.json`).

**사전 등록 기준(S2, 변경 없음): 토큰 일치 ≥ 99.9%, p50 지연·모델 크기·RSS 모두 S0 대비 ≤ +30%**

| 기준 | S0 | R11 | R11/S0 | 한도 | 판정 |
|---|---:|---:|---:|---:|---|
| p50 지연(1줄, 동시성 1) | 4.77ms | 4.76ms | 0.998× | ≤1.30× | PASS |
| 부하 구간별 p50 최대 비율(아래 표 8개 중) | | | 1.134× | ≤1.30× | PASS |
| RSS(로딩 직후 / 부하 후 최대) | 178.8 / 238.6MB | 177.8 / 241.5MB | 0.994× / 1.012× | ≤1.30× | PASS |
| 모델 크기 | 53.84MB | 53.84MB | 1.00× | ≤1.30× | PASS |
| 토큰(구간) 일치 | | 컨테이너(ORT 1.32.0) vs 호스트(ORT 1.31.0) 300문장 100%(S0도 100%). ONNX vs PyTorch 일치는 이번에 재측정하지 않았고 S2a 의 100% 를 인용 | | ≥99.9% | PASS(주의: 후자는 S2a 값) |

참고(기준 밖): 모델 로딩 시간(첫 `ner_status()`: 세션 생성·워밍업 포함) S0 0.72s / R11 0.63s(0.87×), 이 시간은 컨테이너·이미지 pull 시간을 포함하지 않는다. p95(1줄)는 S0 56.1ms / R11 56.4ms로 같다.

**부하 구간별 비교(3회 중앙값 비율 R11/S0, 503 은 3회 합계)**

요청 한 건은 실제 경로처럼 `batch_scope` 로 한 번에 추론한 뒤 줄마다 `detect_with_ner` 를 부른다. "일반" 은 문장 1줄 요청을 도착률로 넣은 열린 루프(Cloud Run 동시성 상한 80 모방, 초과분은 shed), "NER 집중" 은 동시 요청 수만큼 워커가 쉬지 않고 요청하는 닫힌 루프다(20초).

| 부하 | p50 | p95 | 처리량 | 503(S0 / R11) |
|---|---:|---:|---:|---:|
| 일반 5 rps, 1줄 | 0.91× | 0.85× | 1.00× | 0 / 0 |
| 일반 10 rps | 1.07× | 1.09× | 1.00× | 0 / 0 |
| 일반 20 rps | 1.02× | 1.13× | 1.00× | 0 / 0 |
| 집중 동시 2, 40줄 | 1.13× | 1.08× | 0.91× | 0 / 0 |
| 집중 동시 8, 40줄 | 1.13× | 0.93× | 0.91× | 27 / 30 |
| 집중 동시 80, 40줄 | 1.00× | 0.94× | 0.97× | 638 / 638 |
| 집중 동시 2, 200줄 | 1.00× | 1.01× | 1.01× | 0 / 0 |
| 집중 동시 8, 200줄 | 1.07× | 1.00× | 0.96× | 3 / 2 |

**`required` 모드의 대기·타임아웃·503 (R11 만의 문제가 아니라 현재 운영 구성의 성질)**
- 일반 요청(1줄, 20 rps 까지)은 지연 p99 가 30ms 안팎이고 503·shed 가 없다.
- NER 집중 요청(40줄 분석형)이 동시 8개만 넘어도 동시 추론 슬롯(2개) 대기가 길어져 p95 가 약 5~7초, **동시 8 에서 요청의 약 11%, 동시 80 에서 약 75% 가 503 `privacy_unavailable`**(대기 8초 상한 초과)이다. 이 비율은 S0 와 R11 이 같다(R11 이 새로 만든 문제는 아니다). 즉 `required` 를 켠 지금 운영도 같은 조건에서는 같은 503 을 낸다.
- 동시 2·40줄에서 R11 처리량이 S0 의 약 0.91배, p50 이 1.13배다(3회 일관). 기준 안이지만 유일하게 일관된 열세이므로 기록한다.
- 1 vCPU 에서 NER 스레드·동시 추론을 늘려도 처리량은 늘지 않는다. 운영에서 분석형 요청이 몰리면 Cloud Run 인스턴스 수(오토스케일)·요청 동시성 설정이 503 비율을 좌우한다.

**한계 (운영 검증 완료로 읽지 말 것)**
1. 이 측정은 Cloud Run 이 아니라 개발 PC 의 Docker 다. CPU 모델·클럭이 다르고 `--cpus 1` 은 CFS 쿼터라 Cloud Run 의 1 vCPU(스로틀링·"요청 중에만 CPU 할당"·startup CPU boost·gen1/gen2 샌드박스)와 같지 않다.
2. NER 모델만 올린 측정이다. 운영 컨테이너는 같은 프로세스에 `doc-classifier`·`e5-small-ft` 등을 함께 올리므로 **2GiB 한도 대비 실제 RSS 는 이 측정보다 높다**. OOM 여유는 후보 리비전에서 Cloud Monitoring 으로 확인해야 한다.
3. 이 PC 의 S0 이미지는 `release/1.4` 로 다시 빌드한 것이고 운영 digest 이미지가 아니다(운영 이미지는 이 PC 에서 받아 실행하지 못했다). 운영 이미지의 ONNX Runtime·Python 버전은 확인하지 못했다(`pyproject` 는 `onnxruntime>=1.20` 이라 빌드 시점 버전이 다를 수 있다). 모델 파일 해시는 같다.
4. 부하는 합성 요청(개발셋 문장)이며 실제 트래픽 분포·콜드 스타트·인스턴스 간 분산·오토스케일은 재현하지 못했다. 문장 캐시는 일부러 껐다(운영에서는 같은 대화 재가명화 때 캐시 적중이 있어 더 빠를 수 있다).
5. 각 구성은 3회 반복(모델별)이라 작은 차이(±10% 안팎)는 노이즈다. 동시 8·80 의 503 건수는 대기 상한(8초)·측정 시간(20초)에 민감하다.
6. 사람 검수·실제 개인정보는 쓰지 않았다.

## 6. 운영 반영 전 남은 조건 (현재 미충족)

| 조건 | 상태 |
|---|---|
| S4-1 운영 S0 실제 해시 | **확인됨(담당자 보고)**: 운영 digest `sha256:1d8208076f6ae34f9d192077860784d14945b5dd63060d6979a65b15288cac78` 이미지에서 S0 ONNX 전체 해시 `46210943c45f01b6…`·`ner_status()` required·active·지문 `46210943c45f`. 이 PC 에서 재확인한 값은 아니다 |
| S4-2 운영 `PRIVACY_NER_MODE` 실제 값 | **확인됨(담당자 보고)**: 리비전 `gabee-00022-faj` 에서 `required`. `PRIVACY_NER_MODEL_DIR`·`MODEL_FILE` 환경변수는 없다(덮어쓰기 없음). 후보 리비전에서도 게이트로 재확인 필요 |
| S4-6 운영 자원 조건 | **확인됨(담당자 보고)**: 1 vCPU, 2GiB, 요청 동시성 80, 스레드·NER 동시 추론은 코드 기본값 2·2 |
| S2b 성능 | **Docker 재현 PASS**(위 5절). **Cloud Run 후보 리비전에서의 측정은 미완료**: 실제 RSS(다른 모델 포함)·OOM 여유·503 비율은 0% 트래픽 후보 리비전에서 확인해야 한다 |
| 이전 리비전·이미지(digest) 보존 확인 | 운영 확인 필요. 개발 PC 롤백 시험만 통과 |
| 위험 수용 결정서 서명(`NER_R11_OPS_RISK_ACCEPTANCE.md`) | **서명 전**. 서명란 비어 있음. 작업 지시서는 교체 결정을 알렸지만 서명·승인은 따로 필요하다 |
| 배포 담당자 승인 | **미확보** |
| 후보 리비전(0% 트래픽)에서 실제 서비스 경로 스모크 | 운영 접근·승인 후. 게이트는 **후보 리비전 JSON + 같은 digest 이미지의 `ner_status()` JSON** 두 개를 모두 넣어 종료 코드 0 이어야 하고, 현재 S0 서비스 설정은 `--config-only` 로만 본다(S0 를 잘못 차단하지 않기 위함) |
| 라우트별 HTTP 503 | `weekly_news` 만 실제 모듈로 확인. 소통·일정 등 다른 NER 연결 입구는 후보 리비전 스모크에서 확인 |

사전 등록 판정은 `KEEP_S0`(P1~P3 FAIL)이고 바꾸지 않았다.

## 7. 알려진 위험과 롤백

- `required` 라서 모델 로딩 실패 시 NER 연결 입구(가족채팅 AI·일정 에이전트 등)가 503 이다. 롤백 조건·절차는 결정서 4절·런북 6절: 이전 리비전으로 트래픽을 되돌린다(재빌드 없음).
- 일반명사 형태 이름(D1P) 노출은 개선되지 않는다. NER 미적용 경로(메인 AI 채팅·문서 OCR·사진 판별 등)는 이 교체로 보호되지 않는다. 자세한 내용은 결정서 3절.
- 이미지에는 현재 `/health` 로 모델 상태가 보이지 않는다. 지문 확인은 런북 4절의 일회성 Job 으로 한다.
