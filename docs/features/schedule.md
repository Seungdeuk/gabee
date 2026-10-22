# 구현 현황: 일정

- 상태: 진행 중 (앱 공통 기반까지)
- 담당:
- 요구사항: docs/requirements/schedule.md

## 구현된 것
앱(`apps/mobile/src/features/schedule/`), mock 데이터 기준. 서버 연동 없음.
- `constants.js`: 형태·체크 라벨, 막대·주제 색(임시 값)
- `model.js`: 항목 타입(JSDoc), 정렬, 필터, 누구 처리("부모님" 합치기, 공백은 만든 사람)
- `mock.js`, `store.js`: 오늘 기준 샘플과 메모리 저장소(추가·수정·삭제·체크)
- `utils/date.js`: 주·달 계산, 한글 날짜·시간 표기
- `components/`: EventCard, CheckMark, FormTag, FilterChip, SectionHeader, WeekStrip, BottomSheet
- `npm run lint` 통과

## 남은 것
- 화면: 메인, 달력, 등록, 상세, 같이, 채팅 (기존 `ScheduleScreen`은 임시 화면)
- 일정 라우트(`src/app/schedule/`)
- 서버 연동(서버 `schedule` 기능 확장 합의 후 `api.js`)
- 임시 색을 디자인 토큰으로 확정
