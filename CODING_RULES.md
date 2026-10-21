# 코드 규칙

핵심 규칙은 `CLAUDE.md`에 있다. 이 파일은 세부 사항을 다룬다.

## 공통
- 이름은 의도가 드러나게 짓는다. 주석은 "왜"가 필요한 곳에만 쓴다.
- 디버그용 `print` / `console.log`는 남기지 않는다.

## 서버 (Python)
- 포맷·린트는 `ruff`를 따른다 (`ruff format`, `ruff check`).
- 기능 폴더 구조: `router.py`, `service.py`, `repository.py`, `schemas.py`, `tests/`
- 폴더·파일명은 snake_case.

## 앱 (JavaScript)
- 컴포넌트 이름은 PascalCase, 파일은 기능 폴더 안에서 `components/`, `hooks/`, `api.js`로 나눈다.
- 화면(`src/app/`)은 기능 컴포넌트를 조립만 한다.

## 기능 구현 기록
- 기능을 마치면 `docs/features/<기능>.md`에 구현된 것과 남은 것을 적는다.
- 큰 작업 후에는 `docs/dev-log/`에 날짜별로 짧게 남긴다.
