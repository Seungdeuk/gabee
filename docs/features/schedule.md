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
- 메인 화면(`screens/ScheduleScreen.js`, 와이어프레임 v1.2 기준): 헤더 + 주간 스트립(월~일, 일정 있는 날 점), 오늘·내일 카드(체크 수 표시·체크 동작), 함께하기 한 줄, 먼저 권해드려요, 채팅 입력창
- 먼저 권해드려요(`suggestions.js`): 약속 확인 카드("오늘 약속을 모두 확인했어요"를 남김), 할 일 확인 카드(오늘 할 일 + 에이전트가 유추한 챙길 것, "오늘 할 일을 모두 확인했어요"를 남김), 추가 제안 카드. 나중에·새로고침 동작 포함. 챙길 것·추가 제안 문장은 임시
- `npm run lint` 통과

## 남은 것
- 메인에서 이동 연결: 주간 스트립·+ 아이콘(달력), 약속·할 일 추가하기(등록), 카드 터치(상세), 함께하기·같이하기(같이), 채팅 입력(채팅)
- 화면: 달력, 등록, 상세, 같이, 채팅
- 일정 라우트(`src/app/schedule/`)
- 서버 연동(서버 `schedule` 기능 확장 합의 후 `api.js`)
- 임시 색을 디자인 토큰으로 확정
