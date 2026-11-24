# R11 NER 운영 교체 — 배포 담당자 인계 (2026-11-24)

**운영 상태: `READY_FOR_DEPLOY` 가 아니라 `BLOCKED` 로 본다.** 코드·이미지·비운영 검증은 끝났다. 운영 환경이 필요한 S2b·S4 와 위험 수용 서명, 배포 담당자 승인이 비어 있다. 이 문서와 PR 은 운영 배포 승인이 아니다.
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
| `check_ner_deploy_mode` 시험 | 13 통과 |
| `ruff check` / `ruff format --check` (apps/api) | 통과 |

fail-closed 케이스(`ops_final/failclosed_results.json`): ONNX 없음, 해시 불일치, tokenizer 손상, labels 불일치(카드 해시 갱신 후), ONNX 로딩 실패(손상 파일), 로드 이후 추론 예외, 시간 상한 초과, 동시 추론 상한. 모두 가명화 입구가 `PrivacyUnavailable`(503 `privacy_unavailable`)이고 소켓 connect 시도는 0건이다. 정상 케이스는 통과하고 원문 이름·전화번호가 가명화 결과에 남지 않았다.
이 시험은 가명화 입구에서 외부 호출 이전에 막히는 것을 본 것이다. 이전에 보고된 "503 이후에도 Claude 호출" 재현은 가명화 입구 기준으로 나타나지 않았다. 실제 서비스 라우트·실 LLM 경로에서 같은 결과인지는 후보 리비전에서 확인해야 한다(런북 4절).

### 성능(참고용, S2b 로 인정하지 않음)

운영 CPU·메모리 제한·스레드·동시성 값을 확인하지 못해 임의 조건(`--cpus 1 --memory 2g`, 스레드 2, 동시성 2, 개발 검증셋 r11_val 300문장 5회 반복, S0·R11·R11·S0·S0·R11 교차 6회)으로 쟀다. 값은 `ops_final/s2b_PLUMBING_ONLY_summary.json`.

| 지표 | S0 | R11 | R11/S0 |
|---|---:|---:|---:|
| p50 지연 | 9.54ms | 10.58ms | 1.11× |
| p95 지연 | 79.0ms | 80.1ms | 1.01× |
| RSS | 180.4MB | 179.2MB | 0.99× |
| 모델 크기 | 53.8MB | 53.8MB | 1.00× |

R11 6번째 측정이 다른 측정보다 느린 이상값이라(p50 17.2ms) 중앙값 기준 1.11배이며 변동이 크다. 기준(+30% 이내)은 충족하지만, **운영 환경 조건이 아니므로 S2b 는 UNVERIFIED** 다.

## 6. 운영 반영 전 남은 조건 (현재 미충족)

| 조건 | 상태 |
|---|---|
| S4-1 운영 S0 실제 해시 | **미확인**(운영 접근 불가). 개발 PC 서비스 폴더는 S0 해시와 일치 |
| S4-2 운영 `PRIVACY_NER_MODE` 실제 값 | **미확인**. 이 PR 의 이미지는 `required` 를 박지만 서비스에 다른 값이 덮어쓰여 있을 수 있어 게이트 스크립트로 확인해야 한다 |
| S4-6·S2b 운영 자원 조건 재측정 | **미완료**(UNVERIFIED) |
| 이전 리비전·이미지(digest) 보존 확인 | 운영 확인 필요. 개발 PC 롤백 시험만 통과 |
| 위험 수용 결정서 서명(`NER_R11_OPS_RISK_ACCEPTANCE.md`) | **서명 전**. 서명란 비어 있음. 작업 지시서는 교체 결정을 알렸지만 서명·승인은 따로 필요하다 |
| 배포 담당자 승인 | **미확보** |
| 후보 리비전(0% 트래픽)에서 실제 서비스 경로 스모크 | 운영 접근·승인 후 |

사전 등록 판정은 `KEEP_S0`(P1~P3 FAIL)이고 바꾸지 않았다.

## 7. 알려진 위험과 롤백

- `required` 라서 모델 로딩 실패 시 NER 연결 입구(가족채팅 AI·일정 에이전트 등)가 503 이다. 롤백 조건·절차는 결정서 4절·런북 6절: 이전 리비전으로 트래픽을 되돌린다(재빌드 없음).
- 일반명사 형태 이름(D1P) 노출은 개선되지 않는다. NER 미적용 경로(메인 AI 채팅·문서 OCR·사진 판별 등)는 이 교체로 보호되지 않는다. 자세한 내용은 결정서 3절.
- 이미지에는 현재 `/health` 로 모델 상태가 보이지 않는다. 지문 확인은 런북 4절의 일회성 Job 으로 한다.
