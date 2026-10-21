# 0001. 모노레포 구조

- 날짜: 2026-10-21
- 결정: `apps/mobile`(React Native, Expo, JavaScript)과 `apps/api`(FastAPI)를 한 레포에서 관리한다.
- 이유: API 변경과 앱 변경을 한 PR에서 함께 다루고, 기능 단위로 서버·앱을 한 사람이 맡기 위함.
