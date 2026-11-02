# 구현 현황: 가족 초대·가입 승인 (모바일)

- 상태: 구현 완료(실제 기기 확인 전). 서버는 `docs/features/family-group.md`의 "가족 초대·가입 승인" 참고.
- 요구사항: docs/requirements/family-group.md (6번 초대코드 정책, 5번 승인 흐름)

## 화면 (`apps/mobile/src/app/*.js` 라우트 → `features/family-group/screens`)

| 경로 | 화면 |
|---|---|
| 마이 탭 | 프로필 카드 둘째 줄에 가족 요약(가족 이름 · 역할, 승인 대기 중이면 "승인 대기 중"), "우리 가족" 줄에 관리자가 기다리는 가입 요청 수 태그. 예전 `FamilyGroupCard` 는 없앴다 |
| `/family` | **우리 가족**. 그룹이 없으면 만들기·참여, 승인 대기 중이면 대기 화면 안내. 구성원이면 **위쪽**에 가족 이름·내 역할·구성원 수와 구성원 프로필 가로 줄(`FamilyHeader`, 누르면 `/family-member`), "내 프로필" 버튼, **아래쪽**에 가족 초대(`InviteSection`)·가입 요청(`JoinRequestsSection`) — 둘은 **가족 관리자(소유자·관리자)에게만** — 그리고 모두에게 "가족 나가기"(`LeaveFamilySection`, 확인 팝업 후 `POST /family-group/groups/me/leave`; 소유자는 나갈 수 없다는 안내만). 초대 코드는 24시간·1회, 길게 눌러 복사 |
| `/family-create` | 가족 만들기(이름) |
| `/family-join` | 초대 코드 입력 → 참여 요청. 정식 회원은 `/family-pending`, 기존 익명 계정이 예전 방식 코드를 쓰면 바로 `/family` |
| `/family-pending` | 승인 대기. 8초마다 상태 확인, 승인되면 `/family`로 이동, 거절·취소 안내, 지금 확인하기, 요청 취소 |
| `/family-profile` | 내 프로필: 가족에서 쓸 이름, 가족 관계 선택(엄마·아빠·아들·딸·할머니·할아버지·기타), 기타면 직접 적기 |
| `/family-member` | 구성원 한 명: 이름·관계·권한, **나만 보는 별명·메모**, 가족 소유자에게만 보이는 **관리자 지정·해제** |
| `/family-requests` | 가족 관리자의 가입 요청 목록과 승인·거절 버튼(처리 후 목록을 새로 불러오고, 이미 처리된 요청은 안내) |

## 구조

- 서버 호출은 `features/family-group/api.js`만(`shared/api/client.js`의 Bearer/자동 갱신/익명 `X-Gyeot-Token` 호환을 그대로 쓴다). 오류 문구는 `messages.js`(`invalid_invite`·`too_many_attempts`(남은 시간)·`not_manager`·`already_member`·`join_request_already_decided` 등).
- 구성원 목록은 `별명(나만 보임) > 표시 이름 > 계정 이름` 순으로 이름을 보여 주고(`relations.js`의 `shownName`), 관계 문구를 함께 보여 준다. 구성원을 누르면 `/family-member`로 간다.
- `useFamilyState({ pollMs })`: `GET /groups/me` + `GET /groups/join-requests/mine`로 loading / none / pending / member / error를 정하고, 관리자면 승인 대기 요청 목록(`pendingRequests`)과 수를 가져온다. **화면이 다시 보일 때마다, 그리고 `pollMs` 간격(가족 화면 8초, 기타 탭 카드 10초)으로 로딩 표시 없이 조용히 다시 불러와** 새 가입 요청이나 승인 결과가 바로 보인다(겹친 요청은 건너뛰지 않고 끝난 뒤 한 번 더 불러와 방금 한 승인·거절이 늦게 반영되지 않는다).
- 가족 화면의 "가입 요청" 카드에는 들어온 요청이 이름과 함께 **바로 나타나고 승인·거절 버튼**이 있다("가입 요청 화면 열기"는 전체 목록 화면으로 간다). 요청이 없으면 "요청이 들어오면 여기에 바로 나타나요"라고 안내한다.
- 가족 이름 변경과 구성원 내보내기는 만들지 않았다(제품 결정). 가족에서 나가는 것은 본인만 할 수 있고, 나가도 이미 남긴 대화·일정·가계 기록과 1:1 대화방은 그대로 남는다. 나가면 별명은 서버가 정리하고, 다시 들어오려면 새 초대 코드가 필요하다. `ConfirmDialog` 는 일정 기능에서 `shared/components` 로 옮겨 가족에서도 쓴다.
- **프로필 사진**: `/family-profile`에서 갤러리의 사진을 골라 올리고(`expo-image-picker`, 정사각형 편집) 삭제할 수 있다. 웹은 올리기 전에 긴 변 1024px 이하 JPEG로 줄이고, 네이티브는 화질을 낮춰 올린다(2MB·1,600만 화소 초과는 서버가 거절하며 안내 문구가 나온다. 네이티브에서 확실히 줄이려면 `expo-image-manipulator` 추가가 필요해 팀 승인을 기다린다). 사진은 로그인이 필요한 이미지라 `shared/components/UserAvatar.js`가 인증 헤더로 받아 보여 주고(웹은 blob URL, 같은 사진은 한 번만 받는 참조 카운트 캐시), 사진이 없거나 실패하면 이니셜과 구성원 색 아바타로 돌아간다. 가입 요청 행에는 서버 응답에 `photo_url`이 없어 사진이 보이지 않는다.
- 권한 판단은 서버가 한다. 화면은 `my_role`로 관리자 영역을 보여 줄 뿐이고, 요청에 role 을 실어 보내지 않는다.
- 기존 디자인 토큰·공통 컴포넌트(`Screen`, `Card`, `Tag`, `Avatar`, `Button`, `Field`)만 쓴다. 기타 탭의 가족 그룹 영역은 임시 데이터(`mock.js`) 대신 실제 데이터로 바뀌었다.

## 테스트

- `npm test`: `tests/family.test.js`(오류 문구·만료 안내·API 호출 경로, 로그인 세션이면 Bearer만), 실서버 `tests/e2e_family.test.js`(초대 → 요청 → 승인 대기 → 승인 → 구성원, 1회 코드 재사용 거부, 거절·취소, 권한 오류). 실서버 시험은 `GABEE_E2E_API_URL=http://127.0.0.1:8766`(임시 SQLite 서버)일 때만 돌고 평소엔 건너뛴다.
- `npm run lint`, `npx expo-doctor`. 웹 번들(`expo export --platform web`)이 새 화면 포함해 성공하는 것까지 확인했다.
- 화면 렌더링, 키보드, 공유 시트(`Share`), 길게 눌러 복사, 승인 대기 화면의 자동 이동은 자동화하지 않았다 — 실제 기기 확인 항목은 PR 설명 참고(Android 기기 확인은 추후).
