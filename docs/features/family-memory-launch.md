# AI 추억 출시 준비 (PR9, 2026-11-19)

PR1~PR8 이 `release/1.3` 에 병합돼 있다. 이 문서는 **출시 전에 무엇이 되어 있고 무엇이 남았는지**를 정리한다(새 기능 설계가 아니다). 사용자에게 켜는 것은 별도 승인 전까지 하지 않는다.

## 1. 지금 상태 (release/1.3 기준)
- **Alembic head `d1f4a8c6e293` 단일.** `main` 에 아직 없는 AI 추억 리비전(공용 DB 미적용, 모두 expand-only): `f5b1c8d4e2a7`(동의·설정·제외 표 3개) → `639d80e653b4`(다른 PR 과의 병합 리비전, 표 변경 없음) → `b7d2e5f1a846`(작업 큐) → `c9a3e7b2d514`(임베딩) → `d1f4a8c6e293`(추억 후보 2개). 공용 DB 반영은 `main` 병합 뒤 DB 담당자가 Pull Agent 로만(마이그레이션이 코드보다 먼저).
- **운영 스위치 기본 모두 꺼짐**(기본값을 시험이 확인): `FAMILY_MEMORY_ENABLED=false`, `FAMILY_MEMORY_WORKER_ENABLED=false`, `FAMILY_MEMORY_ENCODER=off`, `FAMILY_MEMORY_CANDIDATES_API_ENABLED=false`, `FAMILY_MEMORY_CONSENT_VERSION_REQUIRED=false`, 앱 `EXPO_PUBLIC_FAMILY_MEMORY_UI` 비움(off).
- **자동 등록 진입점은 없다.** `job_service.enqueue`(사진 → 분석 작업)와 `candidate_service.refresh`(가족 → 후보 저장)를 **부르는 코드가 운영 어디에도 없다.** 그래서 스위치를 모두 켜도 지금은 아무 사진도 분석되지 않는다. 시험·개발 환경에서만 명시적으로 부른다.

## 2. 워커 실행 환경 (torch·transformers)
- API 가상환경(Python 3.14)에는 `torch`·`transformers` 가 없고 `pyproject.toml` 에도 넣지 않았다(의존성 추가는 별도 승인). 웹 프로세스는 이 라이브러리를 가져오지 않는다(`encoder.py` 는 `load()` 안에서만 가져온다).
- 실제 추론이 확인된 환경(벤치마크 격리 venv): Python 3.12.10, torch 2.14.1+cu126, transformers 5.23.0, numpy 2.5.4, pillow 13.0.0, psutil. **API 와 같은 Python 으로는 torch 를 못 쓴다**(3.14 용 휠 없음) → 워커는 별도 환경(Python 3.12 + 위 라이브러리 + API 의존성)에서 `python -m app.features.family_memory.worker_main` 으로 돌려야 한다. 이 구성은 팀이 정하고 승인해야 한다.
- 모델: 이미 내려받은 `google/siglip2-base-patch16-224` 스냅샷 폴더를 `FAMILY_MEMORY_SIGLIP2_PATH` 로 지정(다운로드 안 함, 라이선스·저장 위치는 팀 확인). 실측(RTX 3050 6GB): GPU fp32 약 26ms/장·GPU 1.5GB, fp16 약 19ms/장·0.8GB, CPU 약 166ms/장·RSS 2.2GB, 첫 로드 약 27초. 종료 코드 2(스위치 꺼짐)·3(모델 로드 실패, 작업은 건드리지 않음).
- **실제 모델 검증 범위:** (a) `scripts/siglip2_smoke.py`·`siglip2_scene_fixture.py` 로 합성 이미지 실제 추론(768차원, 정규화, 재현성) — torch 환경에서만. (b) 그 **실제 임베딩을 고정 자료로 저장**(`tests/fixtures/siglip2_synthetic_scenes.json`)해 서버 파이프라인(워커→저장→그룹화→후보→API)을 재생하는 시험(`test_pipeline_real_embeddings.py`). **한 프로세스에서 실제 모델로 워커 전체를 도는 E2E 는 이 PC 에서 못 했다**(API 환경과 torch 환경의 Python 이 달라 설치 없이는 합칠 수 없음) — 워커 환경이 정해지면 팀이 한 번 실행해 확인해야 한다.
- **임계값 주의(실제 임베딩 관찰):** 합성 장면의 실제 SigLIP2 코사인은 같은 장면 변형 0.97~0.997, **서로 다른 장면 0.71~0.83** 이었다. 현재 `split_cos=0.70`(같은 날 다른 장면을 가르는 기준)은 이보다 낮아 실제 임베딩에서는 **이미지 유사도만으로는 같은 날 다른 이벤트가 나뉘지 않고 시간 간격(8시간)에 의존**할 수 있다. 임계값은 독립 라벨을 가진 실제 사진 평가 뒤에 정한다(합성 3장면만으로 바꾸지 않았다).

## 3. 사용자 요청형 생성 vs 자동 생성
| | 사용자 요청형 | 자동 생성 |
|---|---|---|
| 시작 | 사용자가 "추억 만들기"를 누를 때(그 가족) | 사진이 일반 사진으로 확인되면 서버가 알아서 |
| 범위·비용 | 한 가족·누른 시점의 사진, 횟수 제한을 걸기 쉽다 | 모든 가족·모든 신규 사진, 비용·부하가 상시 |
| 동의 | 누른 사람의 의사가 눈앞에 있다(그래도 업로더별 동의·가족 활성화는 서버가 확인) | 동의가 철회·변경되는 시점과 경합이 상시(재확인 4지점이 필수) |
| 위험 | 중복 요청 연타 | 무한 재시도·폭주·의도치 않은 처리, 운영 노출 |
| 현재 | **없음(만들지 않음)** | **없음(별도 승인 필요)** |
- **재사용 방법(어느 쪽이든 같은 부품):** ① 자격 있는 사진마다 `job_service.enqueue(db, attachment_id, analysis.KIND_EMBEDDING)` → ② 워커(`worker_main`)가 임베딩 생성 → ③ 가족별 `candidate_service.refresh(db, group_id)`(멱등) → ④ 앱이 `GET /family-memory/candidates` 조회.
- **최초 생성:** 가족을 켠 뒤(또는 동의 직후) 그 가족의 자격 있는 사진을 한 번에 enqueue(가족당 상한·분할 필요), 워커가 끝나면 `refresh` 한 번. 소급(과거) 사진은 아래 4번 때문에 기본에서 제외.
- **증분 생성:** 새로 확인된 사진만 enqueue(UNIQUE `attachment_id`+`kind` 로 중복 불가), 가족당 일정 간격(예: 새 임베딩이 생긴 뒤 몇 분 지연 후)에만 `refresh`. 후보 식별자가 사진 구성으로 정해져 다시 해도 한 벌.
- **중복·무한 재시도 방지(이미 있음):** 같은 사진·종류 한 줄(UNIQUE), 작업당 시도 3회·backoff 30초~15분 후 `failed`(다시 돌리지 않음), 끝난 줄은 `exists`, 철회로 막힌 줄만 `requeued`, 임대 만료 복구도 같은 상한, `refresh` 멱등·동시 새로 고침 안전(PG 시험).
- **소급 분석 동의:** `PUT /family-memory/consent/retro` 는 동의 **기록만** 한다(기본 동의와 별개, 기본 동의가 유효할 때만 켜짐, 철회·재동의 때 사라짐). 소급 분석 경로·대상 선정은 없다. 만들게 되면 `check_photo(..., retro=True)`(소급 동의가 있는 업로더의 사진만)를 쓰고 소급 화면·고지(T31)를 먼저 확정해야 한다.
- **운영 자동 분석을 켜려면 필요한 별도 승인:** ① T31 개인정보 고지문·동의 UI ② 자동 enqueue·`refresh` 호출 코드와 가족당 상한·간격 정책 ③ 워커 환경(torch·transformers)과 모델 사용 승인 ④ 실제 사진 평가·임계값 ⑤ 24시간 삭제 목표·백업 재삭제·동의 기록 보관 기간 ⑥ Android 실기기 검증 ⑦ 공용 DB 반영(DB 담당자). 그 전에는 모든 스위치를 꺼 둔다.

## 4. 개인정보 출시 차단 요소 — 기술 준비 상태
- **고지문(T31): 미확정이다.** 최종 고지문을 만들거나 실제 동의 수집을 켜지 않았다(앱 `MEMORY_NOTICE_FINAL=false`: 동의·가족 활성화·소급 동의 컨트롤 차단, 철회·끄기는 언제나 가능).
- **동의 버전 일치·우회 방지:** 서버 `CONSENT_VERSION` 과 앱 `REQUIRED_CONSENT_VERSION` 이 같아야 하고(시험이 둘을 비교한다), 고지문이 확정되면 서버 스위치 `FAMILY_MEMORY_CONSENT_VERSION_REQUIRED=true` 로 **버전을 안 보낸 동의 요청(409 `consent_version_required`)과 틀린 버전(409 `consent_version_mismatch`)을 막는다.** 이 값만으로 사용자가 고지문을 실제로 봤다고 증명하지는 못하므로 앱이 고지문을 실제로 보여 준 뒤에만 보내야 한다.
- **동의·철회·소급 동의 분리:** 서로 다른 API·필드(`consent`, `consent/retro`, 가족 `settings`). 철회는 소급 동의도 함께 끝내고 버전을 요구하지 않는다.
- **파생 데이터 삭제 실패 기록·재처리:** 즉시 정리가 실패해도 철회는 유지되고(SAVEPOINT) 종류 이름만 기록(`memory cleanup deferred what=… error=…`). 남은 데이터는 조회 재검증으로 보이지 않고, `reconcile` 이 워커 루프(60초)·`refresh` 시작·저장 직전에 멱등하게 지운다.
- **지속 실패 감지(운영자):** ① 대조 정리가 **연속 3번 이상 실패하면 ERROR 로그** `family memory reconcile failed error=<종류> consecutive=<N>`(로그 모니터링 대상), 못 지웠던 것을 뒤늦게 지우면 WARNING `family memory reconcile removed leftovers count=<N>`. ② **`python -m app.features.family_memory.reconcile_check`**(읽기 전용): 동의 없음·가족 꺼짐인 쪽에 남은 임베딩·후보·작업 개수를 JSON 으로 내고 종료 코드 0(없음)·1(남음)·2(DB 오류) — cron/모니터링에서 종료 코드로 감지. 사진 id·경로·사용자 정보는 출력하지 않는다. 워커가 꺼져 있으면(기본) 즉시 정리가 못 지운 것은 `refresh` 호출이나 이 점검으로 드러나므로, 운영 활성화 전에 워커 또는 정기 점검 중 하나는 반드시 정해야 한다.
- **기기 캐시의 남은 위험:** 로그아웃 직전 이미지 캐시(메모리·디스크)를 모두 비우고 추억 목록에서 사라진 사진의 캐시 사본을 지운다. 남는 것: 채팅 화면이 따로 받아 둔 같은 사진의 디스크 캐시(메시지를 삭제해도 expo-image 캐시가 밀려날 때까지 남을 수 있음), 앱이 강제 종료돼 로그아웃 훅이 못 돈 경우, 기기 자체 백업. AI 분석 철회·제외는 채팅 접근 권한과 별개라 채팅 원본은 지우지 않는다.
- **팀이 확정할 사항(임의로 완료 처리하지 않음):** 24시간 삭제 목표, 백업 만료·복원 시 재삭제 절차, 동의 기록 보관 기간, 원본 채팅 사진의 탈퇴 처리, 소급 분석 화면·고지.