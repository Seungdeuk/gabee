# 구현 현황: 가족 초대·가입 승인 (모바일)

- 상태: 구현 완료(실제 기기 확인 전). 서버는 `docs/features/family-group.md`의 "가족 초대·가입 승인" 참고.
- 요구사항: docs/requirements/family-group.md (6번 초대코드 정책, 5번 승인 흐름)

## 화면 (`apps/mobile/src/app/*.js` 라우트 → `features/family-group/screens`)

| 경로 | 화면 |
|---|---|
| 기타 탭 | `FamilyGroupCard`: 가족 요약(없음 / 승인 대기 중 / 구성원), 가족 관리자에게는 기다리는 가입 요청 수 |
| `/family` | 내 가족 그룹. 그룹이 없으면 만들기·참여, 승인 대기 중이면 대기 화면 안내, 구성원이면 가족 목록(권한 표시). **가족 관리자(소유자·관리자)에게만** 초대 코드(24시간·1회, 길게 눌러 복사)·공유·새 코드 만들기·폐기·가입 요청 확인 |
| `/family-create` | 가족 만들기(이름) |
| `/family-join` | 초대 코드 입력 → 참여 요청. 정식 회원은 `/family-pending`, 기존 익명 계정이 예전 방식 코드를 쓰면 바로 `/family` |
| `/family-pending` | 승인 대기. 8초마다 상태 확인, 승인되면 `/family`로 이동, 거절·취소 안내, 지금 확인하기, 요청 취소 |
| `/family-profile` | 내 프로필: 가족에서 쓸 이름, 가족 관계 선택(엄마·아빠·아들·딸·할머니·할아버지·기타), 기타면 직접 적기 |
| `/family-member` | 구성원 한 명: 이름·관계·권한, **나만 보는 별명·메모**, 가족 소유자에게만 보이는 **관리자 지정·해제** |
| `/family-requests` | 가족 관리자의 가입 요청 목록과 승인·거절 버튼(처리 후 목록을 새로 불러오고, 이미 처리된 요청은 안내) |

## 구조

- 서버 호출은 `features/family-group/api.js`만(`shared/api/client.js`의 Bearer/자동 갱신/익명 `X-Gyeot-Token` 호환을 그대로 쓴다). 오류 문구는 `messages.js`(`invalid_invite`·`too_many_attempts`(남은 시간)·`not_manager`·`already_member`·`join_request_already_decided` 등).
- 구성원 목록은 `별명(나만 보임) > 표시 이름 > 계정 이름` 순으로 이름을 보여 주고(`relations.js`의 `shownName`), 관계 문구를 함께 보여 준다. 구성원을 누르면 `/family-member`로 간다.
- `useFamilyState`: `GET /groups/me` + `GET /groups/join-requests/mine`로 loading / none / pending / member / error를 정하고, 관리자면 대기 요청 수를 센다.
- 권한 판단은 서버가 한다. 화면은 `my_role`로 관리자 영역을 보여 줄 뿐이고, 요청에 role 을 실어 보내지 않는다.
- 기존 디자인 토큰·공통 컴포넌트(`Screen`, `Card`, `Tag`, `Avatar`, `Button`, `Field`)만 쓴다. 기타 탭의 가족 그룹 영역은 임시 데이터(`mock.js`) 대신 실제 데이터로 바뀌었다.

## 테스트

- `npm test`: `tests/family.test.js`(오류 문구·만료 안내·API 호출 경로, 로그인 세션이면 Bearer만), 실서버 `tests/e2e_family.test.js`(초대 → 요청 → 승인 대기 → 승인 → 구성원, 1회 코드 재사용 거부, 거절·취소, 권한 오류). 실서버 시험은 `GABEE_E2E_API_URL=http://127.0.0.1:8766`(임시 SQLite 서버)일 때만 돌고 평소엔 건너뛴다.
- `npm run lint`, `npx expo-doctor`. 웹 번들(`expo export --platform web`)이 새 화면 포함해 성공하는 것까지 확인했다.
- 화면 렌더링, 키보드, 공유 시트(`Share`), 길게 눌러 복사, 승인 대기 화면의 자동 이동은 자동화하지 않았다 — 실제 기기 확인 항목은 PR 설명 참고(Android 기기 확인은 추후).
