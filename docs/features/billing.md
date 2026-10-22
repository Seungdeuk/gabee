# 구현 현황: 가계 (billing)

- 상태: 진행 중 (서버·앱 화면 연결과 브라우저 클릭 검증 완료, 실기기 미검증)
- 요구사항: `docs/requirements/billing.md` 없음. 2026-10-21 요청 메시지의 명세를 기준으로 구현했다.
- 브랜치: `billing-care`

## 구현된 것
### 서버 (`apps/api/app/features/billing`)
- 지출 추가·내역: 항목, 금액(정수 원), 날짜. **낸 사람은 요청 바디에서 받지 않고 로그인한 사용자로 서버가 정한다**(`permissions.md` 규칙 2; 바디에 `paid_by`를 보내도 무시). 삭제는 `deleted_at` 소프트 삭제.
- 비용 정산 `GET /billing/settlement`: 구성원별 잔액, 최소 송금 목록, 송금 완료 표시(`POST /billing/settlement/payments`)와 취소.
  - 지출마다 나눌 사람끼리 정수로 나누고 나머지 원은 앞 사람(가족 그룹 가입 순서)부터 1원씩 더한다. 잔액 합계는 항상 0.
  - 송금 목록은 큰 금액부터 맞추는 방식이라 송금 횟수가 최대 (사람 수 - 1)번이다. 수학적 최소 횟수는 보장하지 않는다.
- **정산하기(대상 태그)**: 정산하는 사람이 지출을 고르고 대상 태그를 걸어 정산한다. 태그는 "정산하기"를 누를 때 걸린다(그 전 지출은 기본 `all`=가족 전체).
  - 고정 태그 3개(`GET /billing/settlement/tags`): 부모님 대상(`parents`: 부모 역할이 아닌 구성원이 부담), 자녀 대상(`children`: 역할이 child인 구성원), 가족 전체(`all`). 역할 규칙은 `service.py`의 `FIXED_TAGS` 한 곳에서 바꾼다.
  - 직접 고르기(`custom`): 고정 태그로 채워진 인원에서 사람을 더하거나 빼서 `participants`로 보낸다. 지출에는 `target_tag`와 `split_among`(태그+나눌 사람)이 저장되고, 잔액·최소 송금 계산은 기존 것을 그대로 쓴다.
  - `POST /billing/settlement/tag`: 같은 달의 지출 여러 건에 한 번에 건다. 송금 완료 표시가 있는 달은 `settlement_locked`로 거절(송금 완료를 먼저 취소).
- 용돈: 자녀별 월 예산, 사용 기록, 남은 금액. 남은 금액보다 큰 사용은 저장하지 않는다(`over_budget`). 이미 쓴 금액보다 예산을 낮출 수 없다.
- 구독·통신비 가족 할인 상태: 확인 필요/적용 가능/적용 중. 금액을 계산하거나 보장하지 않고 "예시, 실제 적용은 통신사에서 확인" 문구를 응답(`notice`)에 담는다.
- 테스트: `tests/test_billing.py`, `tests/test_billing_features.py`. DB: Alembic 리비전 `9e28d84c1686`.

### 앱 (`apps/mobile/src/features/billing`)
- `BillingScreen`: 월 이동, 정산·지출·용돈·구독·통신 4구역(`components/*Tab.js`), 서버 호출은 `api.js`.
- `SettleForm`(정산 탭): 지출 선택 → 고정 태그 3개 → 나눌 사람 → 정산하기. "대상 태그" 줄 오른쪽의 작은 스위치(라벨 "직접", 꺼짐은 "켜기", 켜짐은 "켜짐" + 색 표시, 스크린리더 이름은 "직접 고르기")를 켜면 고정 태그로 채워진 인원을 그대로 두고 더하거나 뺄 수 있고, 한 줄 배너의 "← 고정 태그로" 버튼으로 언제든 돌아간다. 직접 고른 지출은 목록에서 "✎ 직접 고름" 표시로 고정 태그 지출과 구분한다. 정산하기를 마치면 고정 태그로 되돌아간다.
- 지출 추가에서는 낸 사람·나눌 사람 선택을 뺐다(낸 사람은 로그인한 나, 나눌 사람은 정산하기에서 정한다).
- 서버 주소(`EXPO_PUBLIC_API_URL`)가 없으면 기존 임시 데이터 화면(`BillingPreview`)을 그대로 보여 준다.
- 공통으로 `shared/components`(Button, Field, Segmented)와 `shared/hooks/useResource`를 추가했다.

## 확인 방법
- 서버 확인용 화면: `apps/api/scripts/dev_console.py` → `/console`.
- 앱: `EXPO_PUBLIC_API_URL=http://<서버> EXPO_PUBLIC_DEV_TOKEN=<토큰> npx expo start --web`. 로그인 화면이 붙기 전까지 `EXPO_PUBLIC_DEV_TOKEN`(개발용 토큰)으로 인증한다.
- 2026-10-22 Edge 브라우저(Expo 웹)에서 정산·지출·용돈·구독 클릭 흐름 검증(서버 응답까지 대조).

## 정한 것 (확인 필요)
- 용돈 대상 "자녀" = 가족 그룹에서 역할이 `parent`가 아닌 구성원. 예산을 누가 정할 수 있는지는 `docs/contracts/permissions.md`가 비어 있어 제한하지 않았다.
- 송금 완료 후 지출을 삭제하면 완료한 송금은 그대로 남고 남은 잔액이 반대 부호가 될 수 있다.
- 월 기준은 한국 시간(서버). 앱의 월 이동은 기기 시간 기준으로 시작한다.

- **확인 필요**: 고정 태그 "부모님 대상"과 "자녀 대상"이 현재 같은 사람들(자녀)로 채워진다(구성원이 parent/child뿐일 때). 두 태그의 분담 인원을 다르게 하려면(예: 자녀 대상은 부모가 부담) `FIXED_TAGS`만 고치면 된다.

## 남은 것
- 로그인·가족 그룹 화면 연결(현재는 개발용 토큰), 실기기(Expo Go) 확인.
- 구독 항목 추가·삭제, 영수증 연결, 균등이 아닌 분담.
