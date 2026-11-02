import { colors } from "@/theme/index"; // 시험 환경(Node)이 디렉터리 import 를 못 풀어서 index 를 명시한다

/** 알림 분류별 표시(이름·아이콘·색). 분류는 서버 app/shared/notifications.py 의 KINDS 와 같다. */
export const KIND_META = {
  schedule: { label: "일정", icon: "calendar-outline", color: colors.primary },
  billing: { label: "지갑", icon: "wallet-outline", color: colors.accent },
  care: { label: "안부", icon: "heart-outline", color: colors.success },
  family_group: { label: "가족", icon: "people-outline", color: colors.peach },
  ai_record: { label: "기록", icon: "document-text-outline", color: colors.textMuted },
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
  return null;
}
