/** 마이 페이지에서 "준비 중" 항목을 눌렀을 때 보여 줄 안내 문구. */
export const SOON_MESSAGE = "준비 중이에요";

/**
 * 마이 페이지 위쪽 바로가기 4칸. route 가 있으면 그 화면으로 가고, soon 이 true 면 "준비 중" 안내만 보인다.
 * icon 은 Ionicons 이름이다.
 * @type {{ key: string, icon: string, title: string, subtitle: string, route?: string, soon?: boolean }[]}
 */
export const SHORTCUTS = [
  { key: "report", icon: "newspaper-outline", title: "주간 뉴스", subtitle: "우리 가족 한 주 이야기", route: "/report" },
  { key: "timeline", icon: "time-outline", title: "타임라인", subtitle: "함께한 추억 모아 보기", soon: true },
  { key: "subscription", icon: "diamond-outline", title: "구독 관리", subtitle: "요금제 · 사용량", route: "/subscription" },
  { key: "invite", icon: "person-add-outline", title: "가족 초대", subtitle: "초대 코드 · 가입 요청", route: "/family-invite" },
];

/**
 * 마이 페이지 목록 8줄(위에서 아래 순서, section 별로 묶여 보인다). 규칙은 SHORTCUTS 와 같다. subtitle 은 화면에는 보이지 않고 접근성 읽기에만 쓴다.
 * @type {{ key: string, icon: string, title: string, subtitle: string, route?: string, soon?: boolean }[]}
 */
export const MENU = [
  { key: "family", section: "service", icon: "people-outline", title: "우리 가족", subtitle: "구성원 · 역할 · 내 프로필", route: "/family" },
  { key: "location", section: "service", icon: "location-outline", title: "가족 위치 확인", subtitle: "가족 위치 공유", soon: true },
  { key: "ai", section: "service", icon: "sparkles-outline", title: "가비 AI 이용 안내", subtitle: "사용 방법 · 개인정보 처리", route: "/ai-guide" },
  { key: "memory", section: "service", icon: "bookmark-outline", title: "가비의 기억", subtitle: "기억해 달라고 한 내용 보기 · 지우기", route: "/memories" },
  { key: "account", section: "support", icon: "lock-closed-outline", title: "계정 및 보안", subtitle: "비밀번호 · 로그인 · 계정", route: "/account-security" },
  { key: "notice", section: "support", icon: "megaphone-outline", title: "공지사항", subtitle: "서비스 소식 · 업데이트", route: "/notices" },
  { key: "help", section: "support", icon: "help-circle-outline", title: "고객센터", subtitle: "FAQ · 문의 · 오류 신고", route: "/support" },
  { key: "service", section: "support", icon: "information-circle-outline", title: "서비스 정보", subtitle: "이용약관 · 개인정보 · 문의", soon: true },
];

/** 마이 페이지 목록의 묶음 제목(위에서 아래 순서). MENU 항목의 section 이 이 key 를 가리킨다. */
export const MENU_SECTIONS = [
  { key: "service", title: "가족 및 AI 서비스" },
  { key: "support", title: "계정 및 고객지원" },
];

/**
 * 목록 항목을 묶음별로 나눈다(항목이 없는 묶음은 뺀다).
 * @param {{ section?: string }[]} items MENU(또는 badge 를 붙인 사본)
 * @returns {{ key: string, title: string, items: object[] }[]}
 */
export function menuSections(items) {
  return MENU_SECTIONS.map((sec) => ({ ...sec, items: items.filter((i) => i.section === sec.key) })).filter((sec) => sec.items.length > 0);
}

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
