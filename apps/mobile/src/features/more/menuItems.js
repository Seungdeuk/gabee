/** 마이 페이지에서 "준비 중" 항목을 눌렀을 때 보여 줄 안내 문구. */
export const SOON_MESSAGE = "준비 중이에요";

/**
 * 마이 페이지 위쪽 바로가기 4칸. route 가 있으면 그 화면으로 가고, soon 이 true 면 "준비 중" 안내만 보인다.
 * icon 은 Ionicons 이름이다.
 * @type {{ key: string, icon: string, title: string, subtitle: string, route?: string, soon?: boolean }[]}
 */
export const SHORTCUTS = [
  { key: "report", icon: "stats-chart-outline", title: "AI 리포트", subtitle: "주간 가족 요약", route: "/report" },
  { key: "subscription", icon: "diamond-outline", title: "구독 관리", subtitle: "요금제 · 혜택", soon: true },
  { key: "ranking", icon: "trophy-outline", title: "가족 랭킹", subtitle: "가족 활동 순위", soon: true },
  { key: "settings", icon: "settings-outline", title: "설정", subtitle: "앱 · 알림 설정", soon: true },
];

/**
 * 마이 페이지 목록 6줄(위에서 아래 순서). 규칙은 SHORTCUTS 와 같다.
 * @type {{ key: string, icon: string, title: string, subtitle: string, route?: string, soon?: boolean }[]}
 */
export const MENU = [
  { key: "family", icon: "people-outline", title: "우리 가족", subtitle: "구성원 · 초대 · 관리", route: "/family" },
  { key: "docs", icon: "folder-open-outline", title: "가족 공유 문서함", subtitle: "가정통신문 · 공지 · 업로드", soon: true },
  { key: "ai", icon: "sparkles-outline", title: "가비 AI 이용 안내", subtitle: "사용 방법 · 개인정보 처리", route: "/ai-guide" },
  { key: "account", icon: "lock-closed-outline", title: "계정 및 보안", subtitle: "비밀번호 · 로그인 · 계정", route: "/account-security" },
  { key: "notice", icon: "megaphone-outline", title: "공지사항", subtitle: "서비스 소식 · 업데이트", soon: true },
  { key: "service", icon: "information-circle-outline", title: "서비스 정보", subtitle: "이용약관 · 개인정보 · 문의", soon: true },
];

/**
 * 항목을 눌렀을 때 할 일을 정한다. route 가 있으면 이동, 아니면 "준비 중" 안내.
 * @param {{ route?: string, soon?: boolean }} item SHORTCUTS 또는 MENU 의 항목
 * @returns {{ type: "route", path: string } | { type: "soon" }}
 */
export function itemAction(item) {
  if (item && !item.soon && typeof item.route === "string" && item.route) return { type: "route", path: item.route };
  return { type: "soon" };
}

/**
 * 프로필 카드 둘째 줄 문구: 가족 이름과 가족 내 역할(둘 다 없으면 안내).
 * @param {string | null | undefined} groupName 가족 그룹 이름
 * @param {string | null | undefined} roleText 화면에 보일 가족 내 역할(예: "가족 관리자", "엄마")
 * @returns {string}
 */
export function profileSubtitle(groupName, roleText) {
  const parts = [groupName, roleText].map((v) => (typeof v === "string" ? v.trim() : "")).filter(Boolean);
  return parts.length ? parts.join(" · ") : "가족 그룹에 참여해 보세요";
}
