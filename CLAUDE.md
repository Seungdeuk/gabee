# gabee 공통 규칙

가족용 비서 앱. 하단 5개 탭(AI 채팅, 소통, 일정, 가계, 돌봄)과 로그인·가족 그룹. 기타 화면(가족 그룹·설정)은 AI 채팅 상단의 ⋮ 로 들어간다.
여러 명이 Claude로 함께 개발한다. 협업 절차는 `CONTRIBUTING.md`, 코드 세부 규칙은 `CODING_RULES.md`를 따른다.

## 스택

- 앱: React Native (Expo SDK 54, Expo Router), JavaScript — `apps/mobile` (npm). SDK 는 아이폰 App Store 의 Expo Go 가 지원하는 54 에 맞춘다(올리기 전에 팀 Expo Go 를 확인)
- API: Python, FastAPI, Pydantic v2 — `apps/api`
- DB: PostgreSQL (Supabase). 서버는 SQLAlchemy 2 로 접근한다. 로컬 SQLite는 서버가 시작할 때 테이블을 만들고(`init_db`), PostgreSQL 스키마 변경은 **Alembic**(`apps/api/alembic/`, `alembic upgrade head`)로만 한다 — `supabase/migrations`는 더 이상 쓰지 않는다.
- 배포: API는 Docker + Caddy, 앱은 EAS Build
- TypeScript는 사용하지 않는다.

## 구조

```
apps/mobile/src/app/(tabs)/   라우트. 화면 파일은 얇게 (조립만)
apps/mobile/src/features/     기능별 코드. 탭 이름과 동일 (하이픈: ai-assistant)
apps/mobile/src/shared/       공통 UI·훅·유틸, shared/api (서버 호출 공통)
apps/mobile/src/theme/        색상·간격·글자 크기 토큰 (디자인 값은 여기에만 둔다: 크림 바탕, 브라운 글자, 꿀색·복숭아색 포인트). 디자인 파일 기준 공통 규칙은 `docs/contracts/ui.md`
apps/mobile/assets/images/    가비 캐릭터(gabee-mascot.png)와 앱 아이콘
apps/api/app/features/<기능>/  router.py, service.py, repository.py, schemas.py, models.py, tests/
apps/api/app/shared/          auth, errors, config, db, llm
docs/contracts/openapi.json   API 명세 (자동 생성, 기준 파일)
docs/requirements/            기능별 요구사항 (_template.md 참고)
docs/features/                기능별 구현 현황
docs/adr/                     기술 결정 기록
docs/legacy/                  원본 프로젝트(family-secretary_prj) 참고 자료
```

기능: ai-assistant, family-chat, schedule, billing, care, family-group, more
- `more`는 기타 화면(오늘 요약·가족 그룹·설정)이라 서버 기능이 따로 없다. `start`는 시작 화면이다. 서버는 family_group, 나머지 5개 기능이 있다.
- 앱 폴더는 하이픈(`family-chat`), 서버 폴더는 밑줄(`family_chat`)이다. 같은 기능이다.
- family-group은 로그인·권한이라 모든 기능이 의존한다.

## 명령어

```bash
# API (apps/api)
python -m venv .venv          # 처음 한 번, 이후 가상환경 활성화
pip install -e ".[dev]"
uvicorn app.main:app --reload
pytest
ruff check . && ruff format --check .
PYTHONPATH=. python scripts/export_openapi.py    # docs/contracts/openapi.json 갱신 (서버 API 를 바꾸면 같이 갱신)

# 앱 (apps/mobile)
npm install
npx expo start                 # 서버 주소: apps/mobile/.env 의 EXPO_PUBLIC_API_URL (없으면 임시 데이터)
npx expo install <패키지>      # 의존성 추가는 npm install 대신 이걸로
npm run lint

# 기타
docker compose up --build      # 개발용 DB + API (루트 .env 필요)
```

## 작업 방식

- 기능 작업 전에 `docs/requirements/<기능>.md`를 읽는다. 없거나 모호하면 구현하지 말고 질문한다.
- 3개 파일 이상 바꾸거나 구조에 영향이 있으면 구현 전에 계획을 보여주고 확인받는다.
- 요청한 범위만 수정한다. 무관한 리팩터링·포맷 변경·파일 이동 금지.
- 수정 후 해당 영역의 테스트·린트를 실행하고 결과를 보고한다. 못 돌렸으면 못 돌렸다고 말한다.
- 모르면 추측하지 않는다. 없는 API·함수·필드명을 지어내지 않는다.
- Expo API는 자주 바뀐다. 앱 코드 작성 전 `apps/mobile/AGENTS.md` 지침대로 현재 SDK 문서를 확인한다.
- 기능 구현을 마치면 `docs/features/<기능>.md`의 구현 현황을 갱신한다.

## 서버 규칙

- 구조는 `router.py`(경로) → `service.py`(업무 규칙) → `repository.py`(DB 접근). 라우터에 로직을 넣지 않고, service가 DB를 직접 건드리지 않는다.
- 요청·응답은 반드시 Pydantic 모델(`schemas.py`)로 정의하고 타입 힌트를 필수로 쓴다.
- 서버 폴더명은 밑줄(snake_case)만 쓴다. 하이픈은 import가 안 된다.
- 다른 기능의 내부 파일을 직접 import하지 않는다. 공통 코드는 `app/shared/`로 올린다.
- 에러 응답은 `app/shared/errors.py`의 공통 형식만 쓴다.
- 인증·권한은 `app/shared/auth.py`를 거친다. 권한 규칙은 `docs/contracts/permissions.md`가 기준이다. 그룹 데이터를 다루는 라우터는 `group_id`를 요청에서 직접 받지 않고 `Depends(current_group_id)`로만 받는다(이 함수가 `group_members` 기준 실제 멤버십까지 확인한다). 라우터를 거치지 않고 Service를 직접 호출하는 코드(향후 AI Agent 포함)는 호출 전에 `ensure_group_member(db, user_id, group_id)`를 먼저 실행해야 한다.
- LLM 호출은 `app/shared/llm` 래퍼로만 한다. 기능 코드에서 SDK를 직접 호출하지 않는다.
- 새 엔드포인트에는 해당 기능의 `tests/`에 테스트를 최소 1개 함께 작성한다.

## 앱 규칙

- 서버 호출은 `shared/api`의 공통 래퍼와 `features/<기능>/api.js`에서만 한다. 화면에서 직접 fetch 금지.
- 요청·응답 형태는 `docs/contracts/openapi.json`을 기준으로 한다. 필드명을 추측하지 않는다.
- 함수에는 JSDoc으로 인자와 반환값을 적는다 (`@param`, `@returns`).
- `src/app/`에는 라우트 파일만. 로직은 `features/`에 둔다 (그 외 파일은 라우트로 취급된다).
- 다른 기능의 내부 파일을 직접 import하지 않는다. 공통 코드는 `shared/`로 올린다.
- 색상·간격·글자 크기는 `theme/` 토큰만 쓴다. 하드코딩 금지.
- 함수형 컴포넌트와 hooks만 사용한다. ESLint를 통과해야 하고, 쓰지 않는 변수·import를 남기지 않는다.
- 파일 확장자는 `.js`로 통일한다 (JSX 포함).

## API 계약 (앱 ↔ 서버)

- 기준은 `docs/contracts/openapi.json`이다. 순서: 서버 수정 → openapi.json 갱신 → 앱 수정.
- `openapi.json`은 서버 코드에서 스크립트로 생성한다. 손으로 수정하지 않는다.
- 하위 호환이 깨지는 변경은 PR 설명에 명시한다.

## DB

- PostgreSQL 스키마 변경은 `apps/api/alembic/`의 Alembic 리비전으로만 한다(`alembic revision --autogenerate` 후 직접 리뷰, `alembic upgrade head`로 적용). 적용된 리비전은 수정하지 않고 새 리비전을 추가한다. `supabase/migrations`는 더 이상 스키마 변경에 쓰지 않는다.
- 컬럼·테이블 삭제 등 데이터가 사라지는 변경은 PR에 적고 팀에 공유한 뒤 진행한다.
- 변경하면 `docs/contracts/db.md`도 갱신한다.
- `supabase/seed`에는 가짜 데이터만 둔다. 실제 사용자 데이터를 넣지 않는다.

## Git

- `main`은 곧 운영 배포다. 직접 push 금지.
- 브랜치: `feature/<이름>-<기능>`, `fix/<이름>-<내용>`. 최신 `main`에서 시작한다.
- 커밋·PR 제목: `feat:` `fix:` `refactor:` `docs:` `chore:` + 한 줄 요약.
- PR은 작게(약 400줄 이하), 한 PR에 한 목적. CI 통과 + 리뷰 승인 후 Squash 병합.
- force push, `reset --hard`, 브랜치 삭제는 사용자가 명시적으로 요청할 때만 한다.

## 하지 말 것

- `.env` 등 시크릿 파일 읽기·수정·출력 금지. 새 환경변수는 `.env.example`에만 추가.
- API 키(LLM 포함)·토큰·비밀번호를 코드·커밋·로그에 넣지 않는다.
- 의존성 임의 추가·업그레이드 금지. 필요하면 이유와 함께 먼저 제안한다.
- 가계(결제)·가족 구성원·사진 같은 개인 데이터를 로그에 남기거나 외부 서비스(LLM 포함)로 보내는 코드를 임의로 추가하지 않는다. 필요하면 먼저 질문한다.
- TypeScript 파일(`.ts`, `.tsx`)이나 `tsconfig`를 추가하지 않는다.
- 테스트를 통과시키려고 테스트를 삭제·약화하지 않는다.
- `deploy/`, `.github/workflows/`는 요청 없이 수정하지 않는다 (운영에 바로 영향).

## 원본 프로젝트 (참고용)

이 레포의 기능 뼈대는 `family-secretary_prj`(원본)를 보고 만든 것이다. 원본 코드는 가져오지 않았고, 기능을 채울 때 해당 부분만 읽고 참고한다.
기능별로 어느 파일을 보면 되는지는 `docs/legacy/original-reference.md`에 있다. 원본의 웹 화면은 앱 화면으로 다시 만들고, ADB/MTP(폰 USB 수집)는 쓰지 않는다.

## 결정 기록

중요한 결정은 `docs/adr/`에 날짜와 이유를 남긴다. 같은 실수가 반복되면 이 파일에 규칙을 추가한다.
