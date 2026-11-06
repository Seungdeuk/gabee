import { colors } from "@/theme/index"; // 시험 환경(Node)이 디렉터리 import 를 못 풀어서 index 를 명시한다

/** 알림 분류별 표시(이름·아이콘·색). 분류는 서버 app/shared/notifications.py 의 KINDS 와 같다. */
export const KIND_META = {
  schedule: { label: "일정", icon: "calendar-outline", color: colors.primary },
  billing: { label: "정산", icon: "wallet-outline", color: colors.accent },
  care: { label: "돌봄", icon: "heart-outline", color: colors.success },
  family_group: { label: "가족", icon: "people-outline", color: colors.peach },
  ai_record: { label: "기록", icon: "document-text-outline", color: colors.textMuted },
  support: { label: "고객센터", icon: "chatbubble-ellipses-outline", color: colors.accent },
  chat: { label: "소통", icon: "chatbubbles-outline", color: colors.primary }, // 푸시 설정에서만 끄는 분류(알림함에는 남지 않아 칩이 없다)
};

const FALLBACK_META = { label: "알림", icon: "notifications-outline", color: colors.textMuted };

/** 칩 필터에 보이는 분류 순서(전체 칩은 따로 있다). 가족·기록 알림은 "전체"에서만 보이게 칩을 두지 않는다. */
export const KIND_ORDER = ["schedule", "billing", "care"];

/**
 * 분류의 표시 정보. 모르는 분류(서버가 먼저 새로 만든 것)도 깨지지 않게 기본값을 돌려준다.
 * @param {string | undefined | null} kind
 * @returns {{ label: string, icon: string, color: string }}
 */
export const metaFor = (kind) => KIND_META[kind] ?? FALLBACK_META;

/** 누르면 돌봄(지갑) 탭으로 가는 정산·용돈 알림 사건. */
const BILLING_EVENTS = ["settlement_updated", "payment_marked", "allowance_requested", "allowance_decided"];

/**
 * 알림을 눌렀을 때 이동할 화면 경로. 이동할 곳이 없으면 null(읽음 처리만 한다).
 * @param {{ kind?: string, event?: string } | null | undefined} notification
 * @returns {string | null}
 */
export function routeFor(notification) {
  if (notification?.kind === "family_group") {
    if (notification.event === "join_requested") return "/family-requests";
    if (notification.event === "join_approved") return "/family";
  }
  if (notification?.kind === "schedule" && notification.event === "event_shared") return "/schedule"; // todo_assigned 는 공동 할 일을 보는 화면이 앱에 생길 때까지 읽음만 한다
  if (notification?.kind === "billing" && BILLING_EVENTS.includes(notification.event)) return "/care"; // 정산·용돈은 돌봄(지갑) 탭에서 본다
  if (notification?.kind === "support") return "/support?tab=mine"; // 답변이 달린 문의는 내 문의 탭에서 본다
  return null;
}
