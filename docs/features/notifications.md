# 구현 현황: 알림함 (notifications)

- 요구사항: `docs/requirements/notifications.md`
- 설계·계획: `docs/superpowers/specs/2026-10-28-notifications-design.md`, `docs/superpowers/plans/2026-10-28-notifications.md`

## 서버 (구현됨)

- `app/shared/notifications.py`: 모델 `Notification`(테이블 `notifications`), 분류 `KINDS`, 기록 함수 `notify()`.
  - 받는 사람마다 한 줄. 그룹 구성원이 아닌 사람과 행동한 본인은 건너뛰고, 같은 사람은 한 번만 받는다. `group_id=None`(개인 알림)이면 구성원 확인 없이 받는 사람에게 남기고, 목록·읽음 조회도 개인 알림은 본인에게 항상 보인다.
  - 저장이 실패해도 예외를 밖으로 내지 않는다(savepoint 안에서 저장). 알 수 없는 분류는 `ValueError`.
  - 커밋은 부르는 기능이 한다.
- `app/features/notifications/`: 내 알림 API (항상 로그인한 본인 것만, 지금도 구성원인 그룹의 알림만).
  - `GET /notifications?kind=&limit=&cursor=` (최신순, 커서 방식 페이지 이동, 잘못된 커서는 400 `invalid_cursor`)
  - `GET /notifications/unread-count` (`total`, `by_kind`)
  - `POST /notifications/{id}/read` (이미 읽은 것은 시각을 바꾸지 않음, 남의 알림은 404)
  - `POST /notifications/read-all` (본문 `{kind?}`로 분류만 읽음)
- Alembic 리비전 `1ee3e7d2ff2e`(새 테이블 1개, expand만).

## 연결된 사건

- 가족 그룹(`kind=family_group`, `join_service.py`에서 `notify()` 호출)
  - `join_requested`: 새 가입 요청이 만들어졌을 때 그룹 관리자(owner/admin)에게. 같은 사람의 중복 신청(기존 대기 요청을 돌려주는 경로)에서는 알림을 만들지 않는다.
  - `join_approved`: 승인되었을 때 신청자에게.
  - 가입 거절은 알림이 없다(신청자가 아직 구성원이 아니라 알림함에 남지 않는다. 신청자는 기존 대기 화면에서 결과를 본다).
- 고객센터(`kind=support`, `admin/service.py`에서 `notify()` 호출)
  - `ticket_answered`: 관리자가 답변을 저장하면 문의를 보낸 사람에게. `notifications.group_id` 가 비어 있는 개인 알림이라 가족이 없는 사용자도, 가족을 옮긴 사용자도 받는다(Alembic 리비전 `5b7c1d9e3a46`, NOT NULL 완화만).
- 일정(`kind=schedule`, `schedule/together.py`에서 `notify()` 호출, 대상은 `target_type=schedule_request`)
  - `request_received`("같이해요가 도착했어요"): 같이해요를 보내거나, 받는 사람을 바꿔 새로 든 사람에게. 이미 받은 사람에게는 다시 가지 않는다.
  - `request_answered`("같이해요에 답이 왔어요"): 받는 사람이 처음 답하거나 답을 바꿨을 때 보낸 사람에게. 같은 답을 다시 보내면 알림이 없다. 수락·거절 여부와 답한 사람은 문구에 담지 않는다.
  - 알림을 눌러도 이동하는 화면은 아직 없다(읽음 처리만).
- 푸시 설정·토큰 API(푸시 1단계 서버 A, 발송은 서버 B 에서 연결)
  - `GET`·`PUT /notifications/push-settings`: 내 푸시 설정(켜기·끄기 `enabled`, 내용 표시 방식 `preview_mode` full/sender/hidden, 끈 분류 `muted_kinds`, 방해금지 `quiet_start`·`quiet_end`). 저장한 적이 없으면 기본값(줄을 만들지 않는다). 방해금지 시작·끝은 둘 다 있거나 둘 다 없어야 한다(아니면 422).
  - `PUT /notifications/push-token`(204): 이 기기의 Expo 푸시 토큰 등록. 같은 토큰이 이미 있으면 소유자·정보를 갱신한다(기기를 다른 사람이 쓰면 소유자가 옮겨 간다). 형식이 다르면 422. `DELETE /notifications/push-token`(204): 내 토큰만 해제(없어도 204).
- 푸시 발송(푸시 1단계 서버 B, `app/shared/push.py`, 결정 `docs/adr/0012-push-via-expo.md`)
  - `PUSH_ENABLED`(기본 false)를 켜면 `notify()` 가 알림을 저장한 **커밋 뒤에만** Expo 푸시 API 로 보낸다(롤백이면 나가지 않는다). 백그라운드 스레드에서 한 번에 100개씩, 타임아웃 5초, 재시도 없음. 푸시 실패는 알림함 저장·원래 기능에 영향이 없다.
  - 푸시에는 알림 제목(고정 문구)과 이동용 `data`(`notification_id`·`kind`·`event`·`target_type`·`target_id`)만 담고 본문은 보내지 않는다. 토큰은 로그에 남기지 않는다.
  - 보내기 전에 받는 사람마다 푸시 설정을 적용한다: 푸시를 껐거나, 그 분류를 껐거나, 방해금지 시간(한국 시간 기준, 자정을 넘기는 구간 포함, 끝 시각은 미포함)이면 뺀다. 행동한 본인은 `notify()` 단계에서 이미 빠진다. 기기가 여러 개면 모두 받는다.
  - Expo 가 `DeviceNotRegistered` 로 응답한 토큰은 `push_tokens` 에서 지운다.
  - `push_only()` 는 알림함에 저장하지 않고 푸시만 보낸다(소통 메시지용, 아래 "소통 푸시"에서 연결). `collapse_key` 를 주면 같은 키의 알림이 잠금 화면에서 한 건으로 교체된다(안드로이드 `tag`, iOS `collapseId`).
- 앱 푸시(푸시 1단계 앱, 결정 `docs/adr/0012-push-via-expo.md`)
  - `features/notifications/PushBootstrap.js`: 로그인하면 안드로이드 알림 채널(`default`)을 만들고 권한을 요청한 뒤(처음이면 안내 문구 후 시스템 창) Expo 푸시 토큰을 받아 `PUT /notifications/push-token` 으로 등록한다. 거절·오류·Expo Go·에뮬레이터 실패는 조용히 넘기고 알림함은 그대로 쓴다. 웹에서는 아무것도 하지 않는다.
  - 로그아웃 직전(세션이 살아 있을 때) `shared/auth/signOutHooks.js` 의 `onBeforeSignOut` 로 `DELETE /notifications/push-token` 을 부른다(실패·3초 초과해도 로그아웃은 계속).
  - 앱이 켜져 있을 때 오는 푸시는 상단 배너로 보이고, 푸시를 누르면 알림함 사건은 알림함(`/notifications`)으로, **소통 푸시(`kind=chat`)는 그 채팅방으로** 이동한다. 푸시에는 방 id 만 있어서 `/chat-open?roomId=…`(`ChatOpenScreen`)가 방 목록(`GET /family-chat/rooms`)으로 가족방(`/chat-room`)인지 1:1(`/chat-room?roomId&peer`)인지 찾아 바꿔서 열고, 방을 못 찾거나 목록을 못 읽으면 소통 탭(`/family-chat`)으로 간다(순수 함수 `chatRouteFor`).
  - 마이 > 알림설정(`/push-settings`, `screens/PushSettingsScreen.js`): 푸시 켜기·끄기, 분류별 켜기·끄기(맨 위 "소통" 포함 — 소통 푸시는 "새 메시지가 도착했어요" 고정 문구라 예전의 "메시지 내용 표시 방식" 선택은 없앴다), 방해금지(스위치를 켜면 한 줄에 `[오전/오후] [시] : [분] ~ [오전/오후] [시] : [분]` 드롭다운 6개가 나타나고 끄면 사라진다. 시는 1~12(01~12 표기), 분은 5분 단위(00~55)이며 고르면 즉시 저장한다. 저장·서버 전송은 24시간 "HH:MM"(오전 12시=00시, 오후 12시=12시, 오전/오후만 바꾸면 12시간 옮겨진다). 처음 켤 때 기본값 오후 10:00~오전 07:00(22:00~07:00), 이미 켜져 있으면 정한 시간을 유지한다. 오전/오후를 바꿔서라도 시작과 끝이 같아지면 서버에서 방해금지가 걸리지 않으므로 그 선택은 저장하지 않고 "시작과 끝 시간이 같을 수 없어요"를 보인다. 안내 문구는 현재 설정으로 만든다: "오후 10:00 ~ 다음 날 오전 07:00에는 푸시를 보내지 않아요". 로직은 `push.js` 순수 함수, 드롭다운은 `shared/components/Dropdown.js`). 바꾸는 즉시 저장하고 실패하면 되돌린다.
  - 개발용 빌드(development build)가 필요하다(Expo Go 에서는 안드로이드 원격 푸시가 안 된다). 안드로이드는 Firebase FCM 설정(`google-services.json` → `android.googleServicesFile`)과 EAS 에 올린 FCM 키가 있어야 푸시를 받는다. 이 설정은 Firebase 프로젝트 소유자가 정해지면 추가한다(아직 없음).
- 2차로 미룬 것: 구성원 변경(서버에 나가기·역할 변경 기능이 없다), 돌봄(서버 `care` 기능이 없다).

## 예약 푸시 (푸시 4단계, 2026-11-06)
- **일정 시작 30분 전**("30분 안에 시작하는 일정이 있어요")과 **할 일 마감 당일 아침 9시**("오늘까지인 할 일이 있어요")에 푸시한다(한국 시간). 문구는 고정이라 일정·할 일의 제목·장소를 싣지 않고, 알림함에는 남기지 않는다(`push_only`, 분류 `schedule`이라 사용자가 일정 푸시를 끄면 가지 않고 방해금지 시간도 적용된다). 누르면 일정 탭(`/schedule`)으로 이동한다.
- **예약 목록 테이블 없이** 서버가 1분마다(`features/schedule/push_schedule.py`, 서버 시작 시 `start()`가 `PUSH_ENABLED` 가 켜져 있을 때만 백그라운드 스레드를 한 번 띄운다) 현재 일정을 직접 찾는다. 그래서 일정을 고치거나 지워도 예약을 따로 고칠 필요가 없고, 시작 시각을 옮기면 키가 달라져 새 시각 30분 전에 다시 보낸다.
  - 약속(`kind=1`): 시간이 있는 것만. **종일 일정(앱이 00:00~23:59 로 저장)은 뺀다**(안 그러면 전날 23:30 에 "30분 안에 시작" 푸시가 간다). 이미 체크한 약속은 뺀다. 시작 30분 전(포함)~시작 전(미포함).
  - 할 일(`kind=2`): 오늘 날짜이고 아직 체크하지 않은 것, 9시 이후. **오늘 9시 전에 만들어 둔 것만** 보낸다(22:30 에 방금 만든 할 일을 1분 뒤 알리지 않는다).
  - 일정 줄의 주인(`events.user_id`)이고 **지금도 이 가족 구성원**인 사람만 받는다(가족을 나가도 일정 줄은 남기 때문). 공유한 일정의 복사본은 받은 사람 몫의 줄이라 각자에게 간다.
- 중복 방지: `scheduled_push_log`(키 `event:<일정 id>:<시작 시각>` 또는 `todo:<할 일 id>:<날짜>`, Alembic `f3256ed34da7`, 새 테이블 1개 expand)에 키를 먼저 넣은 쪽만 보낸다(서버가 여러 대여도 안전, 조회는 id 순으로 해 교착을 피한다). 한 사람이 같은 구간에 여러 건이면 푸시는 한 번만(`collapse_key`로 잠금 화면에서도 교체).
- **못 받는 사람은 기록하지 않는다**: 푸시를 껐거나 방해금지 시간이거나 기기 토큰이 없으면 선점하지 않아 다음 확인(1분 뒤)에 다시 본다. 그래서 방해금지(예: 22:00~09:30)가 끝나는 9:40 에 그날 할 일 알림이 간다. 일정 30분 전 알림은 방해금지에 걸려 있는 동안 구간이 지나가면 사라진다(되돌려 보내지 않는다).
- 시간대는 일정 기능이 쓰는 `local_tz()`(`ai_day_utc_offset_hours` 설정을 따르는 고정 오프셋, 기본 한국 시간)를 쓴다. 방해금지 판정은 `Asia/Seoul` 이라 둘이 어긋나려면 그 설정을 바꿔야 한다.
- 후속: 일정마다 알림 시각 고르기, 정산 기한 알림, `scheduled_push_log` 오래된 기록 삭제(정리할 때 `created_at` 인덱스 추가), Expo 발송 실패 시 재발송(지금은 한 번 선점하면 다시 보내지 않는다).
- 시험: `tests/test_push_schedule.py`(18개: 30분 전 구간 경계, 종일·체크한 일정·가족 나간 사람 제외, 자정 경계, 시작 시각 변경 시 재알림, 한 사람 여러 건 한 번, 아침 9시 할 일, 방해금지 뒤 재전송, 푸시 꺼짐).

## 알림 설정 ↔ 기기 푸시 연결 (앱, 2026-11-06)
- 마이 > 알림설정의 "푸시 알림 받기" 스위치를 **켜면** 서버 설정을 저장한 뒤 이 기기의 푸시를 준비한다(`PushBootstrap.prepareThisDevice`: 알림 채널 → 권한 확인·요청(처음이면 안내 문구 후 시스템 창) → 토큰 받기 → 서버 등록). 로그인할 때만 하던 등록을 스위치로도 할 수 있다.
- 화면은 기기 알림 권한을 `granted`(허용)·`ask`(아직 허용 안 함)·`blocked`(기기 설정에서만 켤 수 있음)·`failed`(토큰을 못 받음)로 나눠(`push.js` `permissionState`·`permissionNotice`) 푸시를 켜 둔 사람에게만 안내한다: ask → "알림 허용하기", blocked → "기기 설정 열기"(`Linking.openSettings`), failed → 알림함에서는 그대로 볼 수 있다는 안내. 푸시를 꺼 둔 사람에게는 권한 이야기를 하지 않는다.
- 화면에 돌아올 때(`useFocusEffect`)와 앱이 다시 활성화될 때(`AppState`, 기기 설정에서 돌아온 경우)마다 권한을 다시 읽고, 이미 허용돼 있으면 묻지 않고 토큰을 다시 등록한다. 웹에는 기기 푸시가 없어 이 안내가 없다.
- 스위치를 **끄면** 서버 설정(`enabled=false`)만 바꿔 서버가 푸시를 보내지 않는다(토큰은 남겨 두어 다시 켜면 바로 받는다). 알림함에는 그대로 쌓인다.
- 첫 권한 안내 문구에서 "알림에 메시지 내용이 보일 수 있어요"를 고쳤다(푸시는 짧은 안내만 보이고 내용은 앱에서 확인).

## 소통 푸시 서버 (푸시 2단계, 2026-11-06)
- 가족방·1:1 방에 새 글·사진·파일이 올라오면(`service.post`, `photo_service.send_photo`, `file_service.send_file` 가 저장 뒤 `chat_push.notify_new_message` 를 부른다) 받을 사람에게 **고정 문구 푸시 한 문구**("새 메시지가 도착했어요", 본문 없음)만 보낸다. 글 내용·보낸 사람·방 이름·파일 이름은 싣지 않고, 암호화·마스킹은 하지 않는다(결정은 설계서 "결정 변경(2026-11-06)"). 실제 메시지는 앱을 연 뒤 인증 API 로 읽는다.
- 분류 `chat`(`PUSH_KINDS` = 알림함 분류 `KINDS` + `chat`): 사용자가 푸시 설정에서 "소통" 푸시를 끌 수 있다(`muted_kinds`). 알림함 분류가 아니라 알림함에는 남지 않고(`push_only`), `GET /notifications?kind=chat` 은 422 그대로다.
- 받는 사람: 방 참여자에서 보낸 사람과 **방 알림을 끈 사람**(`ChatRoomMute`)을 뺀다(가족방은 구성원 전원, 1:1 은 상대 한 명이며 지금도 이 가족인 사람만 — 가족을 나가면 1:1 참여 기록이 남아 있어도 받지 않는다). 그다음 푸시 설정(전체 끔·방해금지·분류 끔)이 적용된다.
- 합치기: 같은 묶음 번호(`batch_id`)의 사진은 최근 10분 안에서 첫 사진에서만, 같은 사람이 같은 방에 보낸 글은 **10초 칸(`BURST_SECONDS`)마다 첫 글에서만** 푸시한다(칸이 바뀌면 다시 푸시해서 대화가 이어지는 동안 푸시가 영영 막히지 않는다). 푸시에는 방 id 를 합치기 키(안드로이드 `tag`, iOS `collapseId`)로 붙여 같은 방의 알림은 잠금 화면에서 한 건으로 교체된다.
- `data`: `kind=chat`, `room_id` 만(보낸 사람 id 같은 다른 값은 외부 푸시 서버로 보내지 않는다. 1:1 의 상대는 앱이 인증된 방 목록으로 찾는다).
- 푸시가 실패해도 메시지 전송은 그대로다(예외를 삼키고 종류만 기록). `PUSH_ENABLED` 가 꺼져 있으면 아무것도 하지 않는다.
- 아직 없는 것: 지금 보고 있는 방 제외, @가비 답변 푸시.
- 시험: `tests/test_chat_push.py`.

## 푸시 PR 1: 알림함 사건 연결 (일정·지갑·AI 기록, 2026-11)
모두 `notify()` 로 알림함에 남고 `PUSH_ENABLED` 가 켜져 있으면 푸시로도 간다. 문구는 고정이라 제목·금액·이름·메모를 담지 않고, 행동한 본인은 받지 않는다. 푸시를 누르면 알림함(`/notifications`)이 열리고, 알림함 목록에서 알림을 누를 때 `routeFor` 가 이동 화면을 정한다.
- 일정(`kind=schedule`): `event_shared`("가족이 일정을 공유했어요", 새 공유 일정을 만들 때 공유 대상에게, 공유 대상에 새로 든 사람에게만, → `/schedule`), `todo_assigned`("할 일이 배정됐어요", 공동 할 일의 담당자가 정해지거나 바뀔 때 새 담당자에게, 본인이 맡은 경우·다른 수정은 없음, 이동 화면 없음 — 일정 탭의 할 일은 다른 데이터라 공동 할 일 화면이 앱에 생길 때까지 읽음만 한다).
- 지갑(`kind=billing`, 모두 → `/care`): `settlement_updated`("정산 내역이 업데이트됐어요", 정산하기 완료 시 나눌 사람과 지출을 낸 사람에게), `payment_marked`("송금 완료가 표시됐어요", 송금 완료 표시 시 송금하는 사람·받는 사람 중 표시한 사람을 뺀 상대에게, 표시한 사람은 서버가 `actor_id` 로 받는다), `allowance_requested`("용돈 요청이 도착했어요", 자녀의 요청을 부모 역할·그룹을 만든 사람에게), `allowance_decided`("용돈 요청이 처리됐어요", 처리 결과를 자녀에게, 승인·거절 여부는 담지 않음).
- AI 기록(`kind=ai_record`): `document_added`("가족 문서함에 새 문서가 올라왔어요", 가비가 문서를 읽어 저장한 뒤 올린 사람을 뺀 가족에게, **민감 문서·읽기 실패는 알리지 않음**, 이동 화면은 아직 없음).
- 연결하지 않은 것: 일정 **변경·취소** 알림(공유 일정은 받은 사람마다 독립된 복사본이라 원본을 고쳐도 받은 사람의 일정은 그대로여서 "바뀌었어요"가 사실과 다르다), 가족 구성원 변경, 돌봄.
- 시험: `tests/test_push_events.py`(일정·할 일·정산·송금·용돈), `ai_assistant/tests/test_document_notification.py`, 앱 `tests/notifications.test.js`(`routeFor`).

## 앱

- `features/notifications/`: `api.js`(목록·개수·읽음·전부 읽음), `kinds.js`(분류별 이름·아이콘·색과 알림을 눌렀을 때 이동 경로 `routeFor`), `format.js`(배지 글자·상대 시각·개수 실패 처리), `useUnread.js`(안 읽은 개수 훅, 못 읽으면 0), `screens/NotificationsScreen.js`, `components/NotificationRow.js`.
- 홈(AI 채팅) 상단 종 아이콘과 숫자 배지(`AppHeader`의 `onBell`·`bellBadge`). 연결은 라우트 `app/(tabs)/chat.js`에서 한다(기능끼리 서로를 import 하지 않기 위해). 누르면 `/notifications` 화면이 열린다.
- 알림 화면: 분류 칩(전체·일정·지갑·안부. 가족·기록 알림은 칩 없이 "전체"에서만 보인다), 제목·부제·칩은 가운데 정렬, 안 읽은 알림은 굵은 제목과 점, 누르면 읽음 처리 후 이동(가입 요청 → `/family-requests`, 가입 승인 → `/family`, 그 외는 읽음만), "모두 읽음"(현재 분류만), "더 보기"로 다음 페이지, 빈 목록·불러오기 실패(다시 시도) 안내.
- 개수는 홈 화면에 돌아올 때마다 다시 읽는다(폴링·폰 푸시 없음). 못 읽으면 배지만 숨긴다.

## 고객센터 답변 알림(앱, 2026-11)
- 분류 `support`("고객센터", 알림 칩은 두지 않고 "전체"에서만 보임)와 이동 규칙(`routeFor` → `/support?tab=mine`)을 앱에 추가했다. 서버는 관리자가 답변을 저장할 때(`admin/service.update_support`) `notify(group_id=None, kind="support", event="ticket_answered")` 로 보낸 사람에게만 남긴다. 새 답변이나 고친 답변일 때만 보내고(같은 답변을 다시 저장하거나 상태만 바꾸면 없음), 문구는 고정("문의에 답변이 달렸어요")이며 문의 제목·내용·답변은 담지 않는다.

## 시험

- 앱: `tests/notifications.test.js`(API 경로, 분류·이동 규칙, 배지·시각 표시, 개수 실패 처리). 화면 렌더링과 실기기는 자동화하지 않았다.
- 서버: `tests/test_notifications_model.py`, `app/features/family_group/tests/test_join_notifications.py`,, `tests/test_notifications_notify.py`, `app/features/notifications/tests/test_notifications_api.py`.

## 화면 다듬기 (release/1.1)
- 알림 화면의 분류 칩 줄: `Screen` 의 `pinned` 영역은 좌우 여백이 없어 칩이 왼쪽 끝에서 시작하던 문제를 고쳤다. 제목과 같은 여백(`spacing.xl`)을 두고, 한 줄로 두어 폭이 모자라면 가로로 민다.
- 상단바(`AppHeader`): 종 아이콘이 붙어 오른쪽 버튼이 늘면서 로고가 왼쪽으로 밀리던 문제를 고쳤다. 왼쪽·오른쪽 영역을 같은 너비(flex 1)로 두어 로고가 항상 가운데에 온다.
- 종 배지: 숫자가 작고 종과 겹쳐 안 보일 수 있어 배지를 20px 로 키우고 글자 줄 높이를 고정했다. 실기기(안드로이드)에서는 아직 확인하지 못했다.

