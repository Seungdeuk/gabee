# 설계: 앱 푸시 알림 (Expo 푸시 서비스 경유)

> 상태: 초안(검토 대기). 요구사항 `docs/requirements/notifications.md`는 "폰 푸시는 범위 밖"이라 이 설계가 승인되면 함께 고친다.
> 기반: 알림함(`app/shared/notifications.py` `notify()`, 2026-10-28 설계 `2026-10-28-notifications-design.md`).

## 1. 목표와 확인한 이해

- 알림함에 새 알림이 생기면 앱이 꺼져 있거나 다른 화면에 있어도 **폰에 푸시**가 온다.
- 푸시는 알림함을 **대체하지 않고 추가**한다. 같은 사건·같은 문구를 쓰고, 푸시를 누르면 앱이 열려 알림함으로 간다.
- 푸시가 실패해도 알림함 저장과 원래 기능(일정 보내기, 문의 답변 등)은 영향받지 않는다.
- 확인 환경: 팀은 안드로이드 폰, 작성자는 iOS 라 BlueStacks(안드로이드 에뮬레이터). **Expo Go 에서는 안드로이드 원격 푸시가 SDK 53 부터 안 되므로 development build(EAS) 가 필요하다.**

## 2. 범위 밖 (이번에 하지 않는다)

- iOS 푸시(Apple 개발자 계정·APNs 설정이 정해지면 같은 코드로 확장. 이번에는 안드로이드만 확인한다).
- 알림 설정(분류별 끄기), 조용한 시간, 시간 기반 알림, 푸시에 이미지·버튼.
- 푸시 영수증(receipts) 후속 조회. 이번에는 발송 응답(tickets)의 `DeviceNotRegistered` 만 처리한다.
- 웹(`Platform.OS === "web"`)은 등록하지 않는다.

## 3. 개인정보 규칙 (필수)

- 푸시에 담는 것은 **알림 제목(고정 템플릿)뿐**이다. `body` 는 보내지 않는다. 사용자 이름·금액·장소·건강 정보·AI 요약·채팅 내용은 담지 않는다(알림함의 규칙과 같다).
- `data` 에는 `notification_id`, `kind`, `event` 만 넣는다(탭했을 때 이동용).
- 푸시는 Expo 푸시 서비스 → 구글(FCM) 서버를 거친다. 이 외부 경유는 ADR 로 남긴다. 사용자는 "A 방식으로 진행"이라고 답했지만 의존성 추가·외부 경유·EAS 빌드 사용 3가지는 따로 확인하지 못했으므로 이 설계 검토에서 다시 확인받는다.
- 푸시 토큰은 기기 식별자라 로그에 남기지 않는다(앞 6자리만 남긴다).

## 4. 서버 설계

### 4.1 데이터: `push_tokens` (Alembic 새 리비전, expand 만)

| 컬럼 | 설명 |
|---|---|
| `id` | PK |
| `user_id` | FK users, 인덱스. 한 사용자가 여러 기기를 가진다 |
| `token` | Expo 푸시 토큰(`ExponentPushToken[...]`), **유니크**. 같은 기기에 다른 사용자가 로그인하면 소유자를 옮긴다(upsert) |
| `platform` | `android` / `ios` |
| `device_label` | 선택(로그인 기기 이름과 같은 값) |
| `created_at`, `last_seen_at` | 등록·마지막 갱신 시각 |

- 가족(그룹)과 무관한 개인 데이터라 `group_id` 가 없다.
- `schema.py` 의 기능 등록(`SHARED_MODEL_FEATURES`)에 이 테이블을 쓰는 기능을 등록한다.

### 4.2 API (새 `features/notifications` 에 추가, 요청·응답은 Pydantic)

- `PUT /notifications/push-token` `{token, platform, device_label?}` → 204. 로그인 사용자 기준으로 upsert(소유자 이동 포함). 토큰 형식(`ExponentPushToken[`·`ExpoPushToken[` 로 시작) 검증, 아니면 422.
- `DELETE /notifications/push-token` `{token}` → 204. 본인 소유 토큰만 지운다(없으면 그냥 204).
- 로그아웃 때 앱이 먼저 위 DELETE 를 부른다(서버 `logout` 에 끼워 넣지 않는다 — 기존 인증 코드를 건드리지 않기 위해).

### 4.3 발송: `app/shared/push.py` (새 파일)

- `notify()` 는 알림 한 줄을 저장한 뒤, **그 세션에 "보낼 푸시" 목록**(`db.info["pending_push"]`)에 받는 사람·제목·`data` 를 쌓기만 한다.
- 세션 `after_commit` 이벤트에서 그 목록을 꺼내 **백그라운드 스레드**로 발송한다. 커밋이 안 되거나 롤백되면 푸시도 나가지 않는다(알림은 없는데 푸시만 가는 일이 없다).
- 발송: `httpx` 로 `POST https://exp.host/--/api/v2/push/send`(한 번에 최대 100개, 제목만, `channelId="default"`, `priority="high"`). 타임아웃 5초, 재시도 없음.
- 응답 tickets 에서 `details.error == "DeviceNotRegistered"` 인 토큰은 `push_tokens` 에서 지운다(별도 세션).
- 어떤 오류도 호출 쪽으로 던지지 않는다(로그에는 종류만, 토큰·문구 제외).
- 설정: `PUSH_ENABLED`(기본 **false**, `ops_errors_enabled` 와 같은 방식). 꺼져 있으면 토큰 등록 API 는 동작하지만 발송은 하지 않는다. 새 환경변수는 `.env.example` 에만 추가한다. 선택 `PUSH_EXPO_ACCESS_TOKEN`(Expo 계정에서 푸시 보안을 켰을 때만).
- `notify(group_id=None, …)` 개인 알림(고객센터 답변)도 같은 경로로 푸시한다.

### 4.4 시험

- 토큰 등록·소유자 이동·삭제·형식 오류·다른 사용자 토큰 삭제 불가.
- 발송은 `httpx` 를 가짜로 바꿔서: 커밋 후에만 호출, 롤백이면 호출 없음, 본인 제외, 제목만 담김(본문·금액 문자열 없음), `DeviceNotRegistered` 토큰 삭제, 발송 오류가 호출 쪽에 안 번짐, `PUSH_ENABLED=false` 면 호출 없음.

## 5. 앱 설계

- 의존성: `npx expo install expo-notifications`(새 의존성, 사용자 승인). `app.json` `plugins` 에 `expo-notifications` 추가(안드로이드 알림 색 `color` 는 `theme` 토큰값과 같은 hex 하나). `expo-device`·`expo-constants` 는 이미 있다.
- `features/notifications/push.js`(순수 함수와 얇은 래퍼) + `usePushRegistration.js`:
  1. 로그인 상태에서만, 실제 기기일 때만(`Device.isDevice`, 에뮬레이터는 시도하되 실패를 삼킨다) 안드로이드 채널 `default` 를 만들고 권한을 요청한다.
  2. 허용되면 `getExpoPushTokenAsync({ projectId })`(`projectId` 는 `app.json` `extra.eas.projectId`) 로 토큰을 받아 `PUT /notifications/push-token`.
  3. 거절·실패는 조용히 넘기고 앱 사용에는 영향이 없다(알림함은 그대로).
  4. 로그아웃 시 `DELETE /notifications/push-token` 을 먼저 부른다.
- 푸시를 누르면 `/notifications` 로 이동한다(분류별 상세 이동은 `routeFor` 확장과 함께 후속).
- 앱이 켜져 있을 때 푸시가 오면 상단 배너로 보이게 하고 안 읽은 개수를 다시 읽는다(10초 폴링 PR 과 별개로 즉시 반영).
- 서버 호출은 `features/notifications/api.js` 에서만, JSDoc 필수, 하드코딩 색 금지, 시험은 `tests/` 순수 함수 위주.

## 6. 환경·빌드 (코드 밖에서 사람이 할 일)

- 안드로이드 FCM 자격: Firebase 프로젝트와 FCM 서비스 키를 EAS 에 올린다(`eas credentials`). **누가 Firebase 프로젝트를 소유할지 팀 결정이 필요하다.** 서버에는 비밀 키를 두지 않는다.
- development build: `eas build --profile development --platform android` 로 APK 를 만들어 팀 폰과 BlueStacks 에 설치한다. Metro 는 `EXPO_OFFLINE=1` 로 기존대로 붙인다.
- 이 PR 들은 자격 없이도 병합 가능하다(`PUSH_ENABLED=false` 가 기본이라 운영 동작은 그대로).

## 7. PR 분할 (각 약 400줄 이하, 한 목적)

1. **서버**: `push_tokens` 리비전 + 모델·`db.md`, 등록·해제 API(+`openapi.json`), `shared/push.py` 발송·정리, `notify()` 연결, 설정·`.env.example`, 시험, 문서(`docs/features/notifications.md`, 요구사항 갱신, ADR).
2. **앱**: `expo-notifications` 추가·`app.json` 플러그인, 등록·해제·탭 이동, 시험, 문서.
3. **(별도, 이미 합의)** 10초 폴링 PR.

서버 PR 이 먼저 병합돼야 앱 PR 의 등록 API 호출이 동작한다. 마이그레이션은 임시 PostgreSQL 에서만 검증하고 공용 DB 는 통합 때 DB 담당자가 반영한다.

## 8. 열린 질문

- 안드로이드 FCM 키를 올릴 Firebase 프로젝트 소유자(팀 결정).
- BlueStacks 에서 푸시 토큰 발급·수신이 되는지(해 봐야 안다). 안 되면 팀의 실제 안드로이드 폰을 확인 기준으로 한다.
- 기본 ADR 번호는 구현 직전에 `git fetch` 후 가장 큰 번호 + 1 로 정한다(현재 목록 최대 0011).
