# 프로젝트 공통 규칙

React Native(Expo) 앱 + FastAPI 서버 모노레포. 여러 명이 Claude로 함께 개발한다.

## 스택

- 앱: Expo SDK 58, Expo Router, TypeScript (`app/`)
- 서버: Python 3.11+, FastAPI, Pydantic v2, pytest, ruff (`server/`)
- 패키지: 앱은 npm (`npx expo install`), 서버는 pip + `pyproject.toml`

## 구조

```
app/src/app/         Expo Router 라우트 — 화면·레이아웃 파일만 둔다
app/src/components/  재사용 UI
app/src/hooks/       커스텀 hooks
app/src/constants/   상수·테마
app/src/api/         서버 통신 (API 호출은 여기서만)
server/src/<도메인>/  router.py, schemas.py, service.py(, models.py)
server/tests/        pytest
docs/decisions.md    중요한 결정 기록
```

## 명령어

```bash
# 앱 (app/)
npx expo start
npx tsc --noEmit
npm run lint
npx expo install <패키지>     # npm install 대신 반드시 이걸 사용

# 서버 (server/)
uvicorn src.main:app --reload
pytest
ruff check . && ruff format --check .
```

## 작업 방식

- 3개 파일 이상 바꾸거나 구조에 영향이 있는 작업은 구현 전에 계획을 보여주고 확인받는다.
- 요청한 범위만 수정한다. 무관한 리팩터링·포맷 변경·파일 이동 금지.
- 수정 후 해당 영역의 테스트·린트·타입체크를 실행하고 결과를 보고한다. 실행 못 했으면 못 했다고 말한다.
- 모르면 추측하지 말고 질문한다. 존재하지 않는 API·함수를 지어내지 않는다.
- Expo API는 자주 바뀐다. 코드 작성 전 `app/AGENTS.md`의 지침대로 현재 SDK 문서를 확인한다.

## Git

- `main` 직접 push 금지. `feature/<이름>-<작업>` 브랜치 → PR → 리뷰 후 병합.
- 커밋: `feat:` `fix:` `refactor:` `docs:` `chore:` + 한 줄 요약.
- PR은 작게(약 400줄 이하), 한 PR에 한 목적. 작업 전 최신 `main`을 pull.
- force push, `reset --hard`, 브랜치 삭제는 사용자가 명시적으로 요청할 때만.
- 같은 파일을 여러 명이 동시에 건드리지 않게 작업 시작 전 팀에 공유한다.

## API 계약 (앱 ↔ 서버)

- FastAPI의 OpenAPI 스키마가 단일 기준. 요청/응답은 반드시 Pydantic 모델.
- 앱의 API 타입·클라이언트는 스키마에서 생성하고 손으로 중복 정의하지 않는다.
- API 변경은 서버(스키마) → 앱 순서. 하위 호환을 깨면 PR에 명시한다.
- 에러 응답 형식 통일: `{"code": "...", "message": "..."}`

## 컨벤션

- 서버: 타입 힌트 필수, 라우터는 얇게(로직은 `service.py`), 새 엔드포인트는 테스트 1개 이상.
- 앱: TS strict 유지, `any` 금지, 함수형 컴포넌트 + hooks만, 화면에서 직접 fetch 금지(`src/api` 경유).
- `src/app/`에는 라우트 파일만. 그 외 파일을 두면 라우트로 취급된다.

## 하지 말 것

- `.env` 등 시크릿 파일 읽기·수정·출력 금지. 새 환경변수는 `.env.example`에만 추가.
- 키·토큰·비밀번호를 코드나 커밋에 넣지 않는다.
- 의존성 임의 추가·업그레이드 금지 (이유와 함께 먼저 제안).
- DB 마이그레이션 임의 생성·적용 금지.
- 테스트를 통과시키려고 테스트를 삭제·약화하지 않는다.

## 결정 기록

중요한 결정(라이브러리 선택, 구조 변경)은 `docs/decisions.md`에 남긴다. 같은 실수가 반복되면 이 파일에 규칙을 추가한다.
