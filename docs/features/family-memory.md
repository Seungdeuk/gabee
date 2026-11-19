# AI 추억 동의·설정 (family_memory) — 구현 현황

요구사항: `docs/requirements/auto-memory.md`(자격·단계), ADR 0020(동의·자체 서버), ADR 0021(노출 정책). 동의·철회·삭제의 구현용 요구사항은 `docs/requirements/auto-memory-consent.md`(문서 PR #446).

## 지금 되는 것 (PR1, 2026-11-18)

**동의 기록과 분석 자격 판정만 있다. 이미지 분석·작업 큐·워커·추억 카드·앱 화면은 없고, 서버 스위치는 기본 꺼짐이라 켜지 않는 한 아무 일도 일어나지 않는다.**

| 기능 | 내용 |
|---|---|
| 서버 스위치 | 환경변수 `FAMILY_MEMORY_ENABLED`(기본 false). 꺼져 있으면 가족 활성화·동의를 새로 받지 않고 모든 사진이 분석 자격 없음(`server_off`). 제외·철회는 항상 가능 |
| 가족 활성화 | `GET/PUT /family-memory/settings`. 켜고 끄는 건 소유자·관리자만(member 403 `not_manager`). 끄면 정리 훅(`memory_hooks.family_disabled`)을 같은 트랜잭션에서 부른다 |
| 업로더 동의·철회 | `PUT /family-memory/consent`(본인만). 철회는 요청 안에서 즉시 효력(`withdrawn_at`), 두 번 보내도 같음. 정리 훅(`member_withdrawn`)이 실패하면 철회도 롤백 |
| 소급 분석 동의 | `PUT /family-memory/consent/retro`. 기본 동의와 별개·기본 없음, 기본 동의가 유효할 때만 켜짐, 철회·재동의 때 사라짐. **이 PR 에서는 기록만 하고 소급 분석 경로는 없다** |
| 사진별 제외 | `PUT /family-memory/photos/{attachment_id}/exclusion`. 업로더 본인만(남의 가족 전체방 사진 403, 다른 가족·남의 1:1 방 사진 404). 타임라인 제외(`chat_photo_checks`)와 별개 |
| 자격 판정 | `service.check_photo(db, attachment_id, retro=False)` → `Eligibility(eligible, reason)`. 서버 스위치 → 가족 활성 → 사진 존재 → 가족 전체방 → 업로더 동의 → (소급이면 소급 동의) → 제외 아님 → 판별 상태 `photo`(E0). 모르면 자격 없음 |
| 정리 | 가족 나가기: `member_exit` 훅으로 그 사람 동의 즉시 종료(같은 트랜잭션, 실패하면 나가기도 취소). 사진 삭제: `shared/memory_hooks` 로 제외 기록 삭제(실패해도 삭제 성공). 가족 삭제: 세 표 모두 `group_id` 열이 있어 `group_purge` 가 지움 |
| 기본값 | 가족 설정 행이 없으면 꺼짐, 동의 행이 없으면 미동의. 새로 들어온 구성원은 미동의로 시작 |

## 영속 작업 큐 (PR3, 2026-11-19)
**작업의 등록·선점·재시도·복구·차단만 있다. 이미지 분석·모델(SigLIP2)·임베딩·카드·앱 화면은 없고, 처리 함수(`worker.register_handler`)를 등록하는 곳이 PR4 의 연결 지점이다. 처리 함수가 없으면 워커는 아무 작업도 선점하지 않는다.** 새 표 `family_memory_jobs`(Alembic `b7d2e5f1a846`, expand-only)와 새 인프라 없는 PostgreSQL 큐다. 워커는 기본 꺼짐(`FAMILY_MEMORY_WORKER_ENABLED=false`, 켜려면 `FAMILY_MEMORY_ENABLED` 도 켜야 함).

| 기능 | 내용 |
|---|---|
| 중복 방지 | UNIQUE(`attachment_id`,`kind`): 같은 사진·종류는 한 줄. 다시 등록하면 `exists`, 자격을 잃어 막았던(`canceled`) 작업만 `requeued`(횟수 0부터), 시도 상한으로 `failed` 가 된 작업은 되살리지 않는다 |
| 선점 | `job_service.claim`: `FOR UPDATE SKIP LOCKED` 로 여러 워커가 같은 작업을 가져가지 못한다(PG16 e2e 로 6 워커·8 작업 검증). 선점마다 `attempts`+1, 임대 `lease_until`(기본 300초). 등록된 종류만 선점 |
| 복구 | 임대가 만료된 `running`(워커 중단·서버 재시작)은 다음 선점 때 되찾는다: 상한 전이면 backoff 뒤 `queued`, 상한이면 `failed`. 느려서 임대를 잃은 워커의 결과·실패 기록은 `lost` 로 버려진다 |
| 재시도 | 기본 최대 3회, 실패하면 30초·1분·… 최대 15분 backoff 뒤 재시도, 상한이면 `failed`(다시 돌리지 않는다). PR2 의 사람이 누르는 사진 재검사(`/photos/{id}/recheck`)와는 별개이며 그 횟수·D-13 을 바꾸지 않는다 |
| 자격 재확인 4지점 | ① 등록 ② 선점 ③ 실행 직전 ④ 결과 저장 직전 모두 PR1 `check_photo`(서버 스위치·가족 활성화·업로더 동의·제외·확인된 일반 사진·가족 전체방)를 쓴다. 하나라도 아니면 `canceled`(사유 코드)로 닫고 결과는 저장하지 않는다. ④는 행을 잠근 같은 트랜잭션에서 확인하고 저장한다 |
| 즉시 차단 훅 | 동의 철회·가족 나가기(`member_withdrawn`)·가족 기능 끄기(`family_disabled`)·사진별 제외(`photo_excluded`, 새 훅)는 대기·진행 중인 작업을 같은 트랜잭션에서 `canceled` 로 막는다(실패하면 철회·나가기도 취소). 사진 삭제는 작업 줄을 지운다 |
| 로그·기록 | 예외 **종류 이름**과 사유 코드만 `last_error`·`cancel_reason`·로그에 남긴다. 사진 내용·라벨·경로·OCR 글자는 어디에도 없다 |
| D-13 | 작업 큐는 `chat_photo_checks` 를 읽기만 한다. 확인되지 않은 사진(pending·unsure·failed·document)은 등록이 거절되고 자동 `photo` 승격은 없다 |

PR4 연동 지점: 사진이 일반 사진으로 확인되고 자격이 있을 때 `job_service.enqueue(db, attachment_id)` 를 부르는 곳(자동 등록은 PR3 에 없다), `worker.register_handler(kind, run, save)`. `member_withdrawn` 훅에는 파생 데이터(임베딩 등) 삭제를 PR4 가 더해야 한다(이미 저장된 결과는 이 PR 이 지우지 않는다: 저장된 결과가 없다).

## 이미지 임베딩 (PR4, 2026-11-19)
**PR3 워커에 SigLIP2 이미지 임베딩 처리 함수를 붙였다. 운영에서는 서버 스위치·워커·인코더가 모두 기본 꺼짐이고, 어떤 사진도 자동으로 등록·실행되지 않는다**(큐에 들어 있는 작업만 처리). 카드 생성·검색·군집화·게시·앱 화면은 없다. 새 표 `photo_embeddings`(Alembic `c9a3e7b2d514`, expand-only, 파생 데이터).

| 항목 | 내용 |
|---|---|
| 인코더 | `encoder.py`: `FakeEncoder`(모델 없는 환경용 결정적 가짜, 16차원) · `Siglip2Encoder`(`google/siglip2-base-patch16-224`, PoC 와 같은 모델·`get_image_features`, 768차원). **이미 내려받은 로컬 파일만** 쓰고(`local_files_only`·`HF_HUB_OFFLINE=1`) 다운로드하지 않는다. 모듈은 `torch`·`transformers` 를 `load()` 안에서만 가져온다 |
| 별도 프로세스 | 모델은 웹 서버가 아니라 `python -m app.features.family_memory.worker_main`(torch·transformers 가 있는 환경)에서만 올라간다. 웹 프로세스는 처리 함수를 등록하지 않아 작업을 선점하지 않는다. 시작 조건: `FAMILY_MEMORY_ENABLED`·`FAMILY_MEMORY_WORKER_ENABLED`·`FAMILY_MEMORY_ENCODER`(siglip2·fake) 모두 켜짐(아니면 종료 코드 2), 모델 로드 실패는 종료 코드 3(작업은 건드리지 않음) |
| 처리 | 선점·자격 재확인(PR3 ②③)을 통과한 작업만, 채팅이 저장한 사진 파일(EXIF 없는 JPEG)을 읽어 임베딩을 만들고 L2 정규화·차원·유한값을 검증한다. 결과는 **저장 직전 자격 재확인(PR3 ④) 뒤 같은 트랜잭션에서만** `photo_embeddings` 에 저장(모델 이름·버전·차원 기록). 외부 서비스(LLM 포함)로 사진을 보내지 않는다 |
| 실패 | 모델 로드 실패·추론 오류·사진 파일 없음·GPU 메모리 부족(OOM: 캐시를 비우고 `EncoderResourceError`)은 예외 **종류 이름**만 기록하고 PR3 재시도 규칙(3회·backoff)에 맡긴다. 로드·추론 시간(ms)과 CPU/GPU 메모리(MB)만 로그에 남긴다 |
| 파생 결과 정리 | 철회·가족 나가기·가족 끄기·사진별 제외·사진 삭제 때 그 임베딩과 끝난 작업 줄을 같은 트랜잭션에서 지운다(끝난 줄이 남으면 재동의 뒤 `exists` 로 막히므로). 정리 훅은 PR3 의 작업 차단 훅 **뒤에** 불린다: 저장 중이던 트랜잭션이 작업 줄을 잠그고 있으면 철회가 그 저장이 끝나기를 기다렸다가 지운다(PG16 e2e) |
| 성능(실측, RTX 3050 6GB, 합성 640px 이미지 20장, 단일 이미지) | GPU fp32 25.7ms/장·GPU 메모리 약 1.5GB·로드 27초(첫 로드, 이후 7초) · GPU fp16 18.9ms/장·약 0.8GB · CPU 166ms/장·RSS 약 2.2GB. 같은 입력은 완전히 같은 벡터(차이 0). `scripts/siglip2_smoke.py` 로 재현 |

연결 지점(PR5): 자격이 있는 사진에서 `job_service.enqueue(db, att, analysis.KIND_EMBEDDING)` 를 부르는 곳(자동 등록·소급 분석 동의 처리는 PR4 에 없다), 임베딩 검색·군집화·카드(`photo_embeddings` 읽기), pgvector 인덱스가 필요해지면 별도 리비전. 의존성: `torch`·`transformers` 는 API `pyproject.toml` 에 넣지 않았다(워커 환경에만 필요, 추가는 별도 승인).
## 추억 후보 그룹화 (PR5, 2026-11-19)
**가족 사진을 묶어 추억 후보와 대표 사진을 계산하는 최소 알고리즘이다. 저장·공개·자동 게시·카드 DB/API·앱 화면은 없다**(요청할 때마다 계산하므로 철회·삭제·제외가 바로 반영된다). DB 변경 없음. 외부 AI·새 모델 없음(입력 임베딩은 PR4 의 SigLIP2 768차원 인터페이스를 쓰되 이 PR 은 주입된 값만 받는다).

| 모듈 | 내용 |
|---|---|
| `grouping.py`(순수) | `group_photos(photos, config) -> list[MemoryCandidate]`. DB·파일·모델 없음, 입력 순서와 무관하게 같은 결과(결정적) |
| `quality.py` | 사진 한 장의 선명도·노출·내용 해시(sha256)·dHash(서버 안에서만, 숫자·해시뿐) |
| `discovery.py` | `discover(db, group_id, embeddings, stats)`: 가족 전체방 사진을 읽어 **PR1 `check_photo` 를 통과한 사진만** 그룹화에 넘긴다(자격 없는 사진은 이유 코드별 개수만). 읽기 전용 |

알고리즘 `memgrp-1`: ① 가족별로 따로 처리 ② 날짜 있는 사진을 촬영 시각순으로 훑으며 간격이 8시간을 넘거나(30분을 넘고 그룹 중심과 코사인 0.70 미만) 새 그룹 ③ 간격 36시간 이내이고 중심 유사도 0.85 이상이면 다일 이벤트로 이음(다른 연도는 절대 안 이어짐) ④ **날짜 없는 사진은 같은 batch_id 의 날짜 있는 사진이 모두 한 그룹에 있고 이미지가 0.80 이상 비슷할 때만** 붙임 ⑤ 중복(같은 해시·dHash 해밍 ≤4·임베딩 0.985)은 한 덩어리로 묶고 가장 좋은 한 장만 남김(원본은 지우지 않음) ⑥ 중복을 뺀 고유 사진이 3장 미만이면 후보 없음 ⑦ 대표 사진은 화질·노출·그룹 중심 대표성 점수(중복 많은 장면은 감점) + MMR 다양성으로 최대 3장.

- **근거 원칙:** 업로드 시각을 촬영 시각으로 쓰지 않는다(시간 근거는 `taken_at` 뿐, 없으면 시간만으로 그룹을 만들지 않음). `batch_id` 는 같이 올렸다는 근거일 뿐 사건 확증이 아니다(날짜 있는 사진을 묶지 않음). 장소·인물·관계·감정은 추론하지 않고 출력에도 없다.
- **출력 `MemoryCandidate`:** `candidate_id`(가족+포함 사진으로 정해지는 결정적 값)·`group_id`·`attachment_ids`·`representative_id`·`representative_ids`·`duplicates`·`time_evidence`(basis·start·end·dated_count·batch_attached_count·bridged)·`score`(0~1, 우선순위용)·`algorithm_version`.
- **합성 평가(`scripts/grouping_synthetic_eval.py`, 60개 합성 타임라인):** 정답은 합성 이벤트 번호라 **실제 가족 정확도가 아니다**. 이미지 잡음 0.5 에서 pair precision 1.00·recall 0.935·이벤트 복원 0.99, 잡음 0.8(같은 장면 유사도가 낮음)에서 recall 0.70·복원 0.80, 다른 이벤트를 섞은 그룹 0%. 이음 단계를 끄면 recall 0.57 로 떨어져 다일 이벤트 이음이 필요함을 확인. 가중치·임계값은 정답이 아니라 초기값이다.
- **PR6 데이터 계약:** `discovery.discover(db, group_id, embeddings=..., stats=...)` 에 PR4 `photo_embeddings` 읽기 함수(`attachment_id -> 벡터|None`)와 `quality.image_stats(사진 파일 바이트)` 읽기 함수를 연결하고, 결과(`DiscoveryResult.candidates`)를 카드로 저장·공개할지는 PR6 에서 정한다.

## 추억 후보 저장·조회 (PR6, 2026-11-19)
**PR4 임베딩과 PR5 그룹화를 실제 DB 조회 경로에 연결하고 후보를 비공개로 저장·조회한다. 자동 등록·자동 게시·앱 화면·외부 AI 없음, 운영 기본 꺼짐.** 새 표 `memory_candidates`·`memory_candidate_photos`(Alembic `d1f4a8c6e293`, expand-only).

| 항목 | 내용 |
|---|---|
| 실제 데이터 연결 | `discovery.discover_group(db, group_id)`: 자격 **일괄** 판정(`service.check_group_photos`, 같은 `evaluate` 규칙, 사진 수와 무관하게 조회 4번) → `photo_embeddings` 일괄 조회 1번 → 저장된 사진 파일(EXIF 없는 JPEG)에서 `ImageStats` 계산(내용·경로·EXIF 로그 없음) → PR5 그룹화. 촬영 시각이 없으면 업로드 시각으로 대체하지 않는다. 사진 4장→24장에서도 조회 수가 같음을 시험으로 고정 |
| 저장 | `candidate_service.refresh(db, group_id)`(**명시적으로 부를 때만**, 자동 호출 없음): 후보 식별자가 결정적이라 **같은 입력은 한 줄**, 내용이 같으면 `updated_at` 도 그대로, 더는 발견되지 않는 후보는 지움. 후보·사진 id·대표·점수·근거·알고리즘 버전·비공개 상태만 저장(사진 복사 없음) |
| 조회 API | `GET /family-memory/candidates`: 인증 + 현재 가족만 + **미출시 가드**(`FAMILY_MEMORY_CANDIDATES_API_ENABLED`, 기본 꺼짐 → 404). **조회할 때마다 자격 재검증**: 지운·철회·제외·자격 잃은 사진은 응답에서 빠지고 그 사진의 주소·시각도 남지 않음(시각 범위는 남은 사진으로 재계산). 대표가 무효가 되면 남은 대표 후보 → 남은 첫 장면 순으로 재선정, 중복을 뺀 장면이 3 미만이면 후보 숨김. 사진 주소는 기존 `/family-chat/photos/{id}` 권한 체계 |
| 정리 | 철회·가족 나가기·가족 끄기·사진별 제외·사진 삭제 때 그 사진이 든 후보를 통째로 지움(`memory_hooks`) + `reconcile.reconcile` 대조 정리(동의 없음·가족 꺼짐인 사람·가족의 임베딩·후보·작업을 멱등하게 지움, `refresh` 에서 호출) |
| **철회 안전성 수정** | 이전에는 파생 데이터 정리 훅이 실패하면 철회·가족 나가기가 통째로 롤백돼 **동의가 다시 켜진 채 남고 사용자가 철회하지 못했다**. 이제 정리는 SAVEPOINT 안에서 최선을 다하되 실패해도 철회는 수락돼 커밋된다(자격은 즉시 닫히고, 남은 파생 데이터는 조회 재검증이 못 보게 막고 `reconcile` 이 지움) |

PR7(앱) 계약: 위 `GET /family-memory/candidates` 응답(`CandidatesOut`: 후보 `id`·`status:"private"`·`representative`·`photos[{attachment_id,thumb_url,photo_url,taken_at,is_representative}]`·`photo_count`·`dated_count`·`undated_count`·`starts_at`·`ends_at`·`bridged`·`score`·`algorithm_version`·`updated_at`). 후보 생성 진입점(자동 enqueue·refresh 호출)은 별도 승인 전까지 없다.

## 앱 추억 후보 화면 (PR7, 2026-11-19)
**읽기 전용 미리보기 화면이다. 후보 게시·공유·가족 채팅 전송·자동 등록 없음, 운영 기본 꺼짐(진입점이 보이지 않는다).** 서버 변경 없음.

| 항목 | 내용 |
|---|---|
| 화면 | `src/features/family-memory/screens/FamilyMemoriesScreen.js`(라우트 `/family-memories`): 후보 카드 목록(대표 사진·**촬영 날짜로만 만든 중립 제목**·사진 수·날짜 범위) → 후보를 누르면 사진 모아보기(3열) → 사진을 누르면 기존 `AlbumViewer`. 장소·인물·감정을 추론하지 않는다. 당겨서 새로 고침 |
| 진입점(기본 꺼짐) | 서버에는 "후보 조회 API 가 열려 있는가"를 알려 주는 계약이 없다(미출시면 404 만 온다). 그래서 빌드 변수 `EXPO_PUBLIC_FAMILY_MEMORY_UI`(`off` 기본 / `on` 실제 API / `mock` 합성 데이터)로 가족방 서랍의 "가족 추억 후보" 줄을 숨긴다. 기본에서는 서랍이 기존과 똑같다 |
| 상태 | **200 + `items=[]` = 정상 빈 상태**, **404 = 미출시("아직 열려 있지 않아요", 빈 상태가 아님)**, 401 = 로그인 만료 안내, 403 = 권한 없음, 네트워크 오류 = 다시 시도, 그 밖의 오류 = 다시 시도. 미출시·만료·권한 없음이면 받아 둔 사진도 화면에서 지운다 |
| 개인정보 | 현재 가족(`user.id:active_group_id`) 범위로만 상태를 둔다: **가족 전환·로그아웃이면 후보를 즉시 비우고** 늦게 온 이전 가족 응답은 버린다. 새로 고침 응답이 목록을 통째로 바꿔 서버가 뺀 사진·후보는 바로 사라지고, 사진이 열리지 않으면(지움·권한 없음) 그 사진을 빼고(3장 미만이면 후보 숨김) 날짜 범위를 다시 센다. 사진 주소는 기존 채팅 사진 주소 규칙(`photoPath`)을 통과한 것만 쓰고 로그인 헤더 이미지(`AuthImage`)를 재사용한다. 화면을 떠나면 이미지 메모리 캐시를 비운다(디스크 캐시는 기존 채팅 사진과 같은 정책) |
| 시험 | `apps/mobile/tests/familymemories.test.js`(순수 로직 20개: 정리·제목·상태·오류 종류·가족 전환 초기화·늦은 응답·제거된 사진 반영·진입점 스위치·서랍) |

개발자 확인: `EXPO_PUBLIC_FAMILY_MEMORY_UI=mock` 이면 합성 후보 3개(`fixtures.js`)로 화면을 볼 수 있다(API 를 부르지 않고 실제 사진·가족 데이터를 쓰지 않는다). `on` 은 서버의 `FAMILY_MEMORY_CANDIDATES_API_ENABLED` 를 켠 개발 서버에서만 쓴다.

## 통합 검증과 출시 안전성 보강 (PR8, 2026-11-19)
기존 기능을 다시 설계하지 않고 전체 흐름·개인정보 시나리오를 검증하고 확인된 결함만 고쳤다. 서버 스위치·워커·인코더·후보 API 가드·앱 진입점은 **모두 기본 꺼짐**이다.

**실제 수정한 결함**
- **후보 새로 고침 경합(서버):** `refresh` 가 계산하는 사이에 철회가 커밋되면 그 사람의 사진이 든 후보가 저장된 채 남을 수 있었다. 저장 직전에 한 번 더 대조(`reconcile`)하도록 했고, 이 DB 세션은 자동 flush 가 꺼져 있어 방금 추가한 후보 줄이 대조에 보이지 않던 문제도 함께 고쳤다(`flush` 추가, 시험으로 재현·확인).
- **동의 버전 검증(서버, T31 기술 준비):** `PUT /family-memory/consent` 에 선택 필드 `consent_version` 을 더해, 보내면 현재 버전과 같은지 확인한다(다르면 409 `consent_version_mismatch`, 철회에는 보지 않음). 안 보내는 기존 호출은 그대로 된다 — **고지문이 확정되면 필수로 바꾼다.** 이 값만으로 사용자가 고지문을 실제로 봤다고 증명하지는 못한다.
- **기기 이미지 캐시(앱):** 인증 이미지(`AuthImage`)는 expo-image `memory-disk` 캐시를 쓰고 캐시 키가 요청 주소라, 서버가 후보에서 뺀 사진·로그아웃·가족 전환 뒤에도 기기 디스크에 사본이 남았다. ① **로그아웃 직전에 메모리·디스크 이미지 캐시를 모두 비운다**(기존 로그아웃 훅 사용, 같은 기기에서 다른 사람이 로그인해도 남지 않게) ② **추억 목록에서 사라진 사진(서버가 뺌·사진 열림 실패·가족 전환·로그아웃)의 디스크 캐시 사본만 골라 지운다**. AI 분석 동의 철회·제외는 **가족 채팅의 사진 접근 권한과 별개**라 채팅 원본 사진을 지우지 않는다(캐시 사본만 정리, 필요하면 다시 받는다).

**확인만 한 것(결함 없음, 시험으로 고정)** — 전체 흐름 시험 `test_pipeline_e2e.py`(SQLite)와 PG16 `test_full_pipeline_and_privacy_events_on_postgres`: 확인된 사진 → 동의(버전 포함) → 작업 등록 → 워커 → 임베딩(가짜 인코더) → 그룹화 → 후보 새로 고침 → 후보 API. 철회·사진별 제외·사진 삭제·가족 나가기·가족 끄기 각각이 **작업 재등록 거절·임베딩·후보 줄·API 노출을 모두 막고**, 영향받지 않는 사진과 다른 가족은 그대로이며, 실행 중 이벤트는 결과 저장을 막고, 정리가 전부 실패해도 철회는 유지되고(실패는 종류 이름만 기록, 사진 id·경로는 로그에 없음) 대조 정리가 재시도로 지운다(멱등). 서버·앱이 같은 응답 계약 fixture(`docs/contracts/fixtures/family_memory_candidates.json`)를 시험한다.

**T31 개인정보 고지: 고지문은 아직 확정되지 않았다(ADR 0020: 개인정보처리방침·Play 데이터 안전 양식 반영 필요).** 그래서 최종 문구·실제 동의 수집·동의 화면은 만들지 않았다. 기술 준비만 했다: `features/family-memory/consent.js`(`MEMORY_NOTICE_FINAL=false` 동안 동의·가족 활성화·소급 동의 컨트롤을 막고 **철회·끄기는 언제나 가능**, 업로더별 동의·가족 활성화(소유자·관리자)·소급 동의를 구분, 버전이 다르면 재동의 필요)와 `consentApi.js`(기존 동의·철회·제외 API 연결). 시험 `familymemorysafety.test.js`.

**출시 가능 범위(현재 가능):** 서버 코드·마이그레이션 배포(모든 스위치 꺼짐으로), 개발 서버·시험 환경에서 명시적 `enqueue`·`refresh` 호출로 전체 흐름 검증, 앱의 개발용 화면(`mock`·`on`).
**출시 불가능 범위(별도 승인·개발 필요):** 사용자에게 AI 추억 기능을 켜는 것 — ① 개인정보 고지문·보관/삭제 정책 확정(T31) 후 동의 UI ② 자동 등록(enqueue)·`refresh` 진입점(지금 없음) ③ 워커 환경 의존성(`torch`·`transformers`) 승인 ④ 실제 가족 사진 평가와 임계값 재조정 ⑤ 24시간 삭제 목표·백업 재삭제·동의 기록 보관 기간 확정 ⑥ Android 실기기 화면 검증 ⑦ 공용 DB 반영(DB 담당자, `main` 병합 뒤 Pull Agent).

## 지키는 것
- `ai_group_settings`(대화 분석 동의)와 `chat_photo_checks`(사진 판별 상태, D-13)를 읽거나 쓰지 않는다(자격 판정은 판별 상태를 읽기만 한다).
- 사진 내용·라벨·임베딩·파일 경로를 저장·로그하지 않는다(이 PR 에는 그런 데이터가 없다).
- 동의 기록 보관 기간은 미결정이라 지우는 배치를 만들지 않았다. 가족을 나간 사람의 동의 행은 `withdrawn_at` 만 채우고 남긴다.

## 아직 없는 것 (이후 PR, 별도 승인)
- 앱의 동의 안내·스위치·사진 제외 버튼(T31 개인정보 고지·동의 UX, 고지문 확정 전에는 만들지 않는다). 추억 후보 읽기 화면은 PR7 에 있다.
- 카드 생성·게시·검색·군집화(PR5 이후; 작업 큐는 PR3, 임베딩 추출·파생 결과 삭제는 PR4 에 있다).
- E1(`unsure` 포함 자동 게시): 독립 안전성 평가와 별도 정책 승인 전에는 열지 않는다.
- 미결정: 동의 기록 보관 기간, 24시간 삭제 목표 확정, 백업 만료·복원 시 재삭제 절차, 원본 채팅 사진의 탈퇴 처리, 소급 분석 화면·고지.

## 시험
`apps/api/app/features/family_memory/tests/test_candidates.py`(PR6: 일괄 조회 N+1 없음, 임베딩·ImageStats 연결, 멱등 저장, 조회 API 계약·미출시 가드·가족 격리, 조회 재검증·대표 재선정·3장면 미만 숨김, 정리 훅·대조 정리, 철회가 정리 실패에 막히지 않음).
`apps/api/app/features/family_memory/tests/test_memory_jobs.py`(작업 큐: 등록 자격·중복·1:1 제외, 선점·임대 복구·재시작 복구·상한, backoff, 자격 재확인 4지점, 철회·나가기·끄기·제외·삭제 차단, 가족 격리, 워커·로그) 와 `tests/test_family_memory_pg_e2e.py`(PG16: 기본값·UNIQUE·CASCADE, 6 워커 동시 선점, 잠긴 줄 건너뛰기, 철회 차단).
`apps/api/app/features/family_memory/tests/test_grouping.py`(순수: 같은 시점·다른 날짜/연도·같은 날 다른 이벤트·연사, batch_id 경계, 촬영 시각 누락, 중복, 대표 사진 결정성·다양성, 가족 격리, 빈 결과, 입력 순서 불변, 잘못된 임베딩, 화질·해시)와 `test_discovery.py`(DB: 자격·미동의·철회·제외·삭제·서버/가족 끄기·1:1·문서·미확인·가족 격리·읽기 전용).
`apps/api/app/features/family_memory/tests/test_family_memory.py` — 기본 꺼짐, 서버 스위치, owner/admin/member 권한, 가족 간 격리, 동의·철회 멱등, 소급 동의 분리, 사진별 제외(본인만), 자격 판정 표, D-13·`ai_group_settings` 불변, 훅 실패 롤백, 가족 나가기·사진 삭제·가족 삭제 정리, 로그.
