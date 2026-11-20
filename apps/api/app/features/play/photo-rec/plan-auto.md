# 찰칵 흔한 사진 자동 보충(2차) 구현 계획

설계 근거: `prj/photo-rec/design.md`(흔한 사진 풀), 위키 [[photo-recommendation]](질문 형태 기준 11/19), [[free-stock-photo-sites]](Pixabay). 11/19 사용자 확정: 하루 한 번 3장을 목표로 하고 실패하면 부족한 만큼만 최대 2번 더(총 3번), 그래도 못 채우면 모자란 채로 두고 로그. 실행 위치는 서버 안 백그라운드 작업(푸시 알림 반복 작업 `push_schedule.start()` 방식), 설정으로 켜고 끔(기본 꺼짐). 출처 칸 마이그레이션 승인됨. 하나도 못 만들어 풀이 비면 앱에 "가비가 오늘 낼 사진을 아직 준비하지 못했어요…"(앱 쪽은 반영 완료).

> 11/20 변경: 하루 한 번 타이머 대신 **가족이 추천을 열 때** 백그라운드 실행(`photo_rec_auto_hour` 설정 삭제, 쿨다운 `photo_rec_auto_cooldown_seconds`). 사람·손·다리가 찍힌 사진도 허용(외부 사진은 저작권 허락됨). 구현은 위키 [[photo-recommendation]] 참고.

## 구조
- `app/features/play/photo_rec_auto.py` (새): `run_daily(db, now, fetch=..., ask=...)` 가 하루 목표 3장에서 오늘(한국 날짜) 이미 넣은 자동 행(source 4) 수를 빼고 부족분만 채운다. 시도 = 한 번에 검색→후보 하나씩 내려받기→AI 질문 만들기→규칙 검사→저장. 한 사진이 어느 단계든 실패하면 다음 후보로 넘어가고, 실행 한 번의 "시도"는 부족분이 있는 동안 최대 3번(처음 + 재시도 2). 같은 `pixabay_id` 는 다시 쓰지 않는다(이미 풀에 있거나 이전에 쓸 수 없어서 버린 것 포함, 기록은 행에 남김).
- `app/features/play/photo_rec_pixabay.py` (새): Pixabay API 클라이언트(키는 `settings.pixabay_api_key`, 환경변수 `PIXABAY_API_KEY`). 검색어 목록은 `scripts/fetch_pixabay_seed.py` 의 EVERYDAY 목록과 같은 소재 기준(일상·친숙한 음식·과일·동물·쉬운 꽃·장소·계절·물건)을 가져오되 서버가 쓸 수 있게 app 안에 둔다(scripts 는 서버 이미지에 안 들어감). 사진은 `largeImageURL`(1280px)을 서버로 내려받아 JPEG 로 저장(핫링크 금지). `safesearch=true`, 사람·글자·브랜드가 태그로 의심되는 후보는 거른다(스크립트의 나쁜 태그 필터와 같은 목록).
- `app/features/play/photo_rec_auto_ai.py` (새): 공개 사진용 질문 만들기. `llm.complete_json` 으로 사진 한 장당 한 번(+규칙에 안 맞으면 한 번 더 재시도 안 함 — 시도 단위 재시도로 처리). `PROMPT_VERSION="auto-v1"`. 프롬프트·규칙 검사에 시드 기준을 넣는다: 소재(일상·친숙·완성 음식·과일·친숙한 동물·쉬운 꽃·장소·계절·물건), 금지(뱀·곤충·파충류 등 무서운 동물, 낯선 풍경, 사람·손·다리·실루엣, 술, 읽을 수 있는 글자·브랜드, 장례 느낌 꽃(국화), 병원 같은 부정적 장소, 정적·식별 불가), 질문은 "무슨 음식/과일/꽃/동물일까요?"처럼 직접 묻기(장소·계절·물건은 "어디일까요?"·"어느 계절 같아요?"·"무엇일까요?" 허용), "어울릴까요?"·"한식일까요?" 같은 간접 질문 금지, 색깔 질문 금지, 보기는 한두 단어, 꽃은 허용 목록(민들레·개나리·튤립·무궁화·해바라기·카네이션·코스모스·장미·진달래·벚꽃·목련 등 흔한 꽃)만 정답·보기에 쓰고 할미꽃·국화·소국 등 금지. 서버 규칙 검사(`photo_rec_ai.validate_content`)를 먼저 통과해야 하고 그 위에 금지어(위 꽃·무서운 동물 목록)·질문 형태 검사를 더한다. 쓸 수 없다고 하면(`usable=false`) 저장하지 않고 다음 후보.
- 저장: `play_photo_rec` 행 `source=4`, `group_id`·`attachment_id` 비움, `image` 에 JPEG, `prompt_version="auto-v1"`, 출처 칸(`credit_user`·`credit_url`·`license`·`search_query`·`external_id`)을 채운다. 행 id = `auto<pixabay_id>`.
- 마이그레이션(새 리비전, 시드 마이그레이션 `b8e2f4a6c917` 다음): `play_photo_rec` 에 nullable 칸 `credit_user`(String 80), `credit_url`(String 300), `license`(String 40), `search_query`(String 60), `external_id`(String 32, 인덱스)를 더한다(expand 전용, 기존 행·데이터 변경 없음, downgrade 는 칸 삭제).
- 하루 한 번 실행: `photo_rec_auto.start()` 를 `app/main.py` lifespan 에서 부른다(푸시 알림 반복과 같은 방식의 백그라운드 스레드). `settings.photo_rec_auto_enabled`(기본 False)가 켜져 있을 때만 돈다. 한국 시간 새벽(설정 `photo_rec_auto_hour`, 기본 4)에 하루 한 번, 서버가 그 시각에 꺼져 있었으면 켜졌을 때 오늘 부족분을 채운다(오늘 행 수로 판단하므로 여러 번 불려도 3장을 넘기지 않는다). PostgreSQL 이면 `pg_try_advisory_lock` 으로 여러 서버가 동시에 돌지 않게 한다.
- 설정(`app/shared/config.py`): `pixabay_api_key: str = ""`, `photo_rec_auto_enabled: bool = False`, `photo_rec_auto_hour: int = 4`, `photo_rec_auto_per_day: int = 3`, `photo_rec_auto_max_attempts: int = 3`. 키는 로그·응답에 찍지 않는다.
- 로컬 확인용 수동 실행: `python -m scripts.run_photo_rec_auto`(설정과 무관하게 한 번 `run_daily` 실행, 결과 요약 출력).
- 풀 선택(`photo_rec_pool.pool_rows`)이 source 4 행도 흔한 사진으로 포함하는지 확인하고 아니면 포함한다. 14일 제외·점수·전송(rec_id)은 시드와 동일하게 동작해야 한다.

## 시험(모두 가짜 Pixabay·가짜 LLM)
- 3장 목표를 한 번에 채움 / 첫 시도에 일부 실패해 부족분만 두 번째에 채움 / 3번 모두 실패하면 모자란 채로 끝 / 오늘 이미 3장이면 아무것도 안 함 / 같은 pixabay_id 중복 안 함 / `usable=false`·규칙 위반·금지 꽃·간접 질문은 저장 안 함 / 출처 칸과 prompt_version 저장 / 풀에 source 4 가 포함돼 추천에 나옴 / 설정이 꺼져 있으면 시작하지 않음 / 키가 없으면 조용히 건너뛰고 로그.
- 마이그레이션: 임시 DB 에서 upgrade·downgrade(공통 조상까지가 아니라 한 단계).

## 안 하는 것
- 운영 키 반영(사용자 처리 완료), 앱 변경(앱은 source 로 라벨만 보여 줌), 가족 앨범 재활성화.
