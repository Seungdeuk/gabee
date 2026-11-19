// 체류시간을 셀 탭 이름 판정 — docs/requirements/usage-time.md
// 경로의 첫 칸만 본다. 화면 안의 내용(방 id·일정 id 등)은 쓰지 않는다.

const TABS = ["chat", "family-chat", "schedule", "care", "my"]; // app/(tabs)/_layout.js 의 탭 이름과 같다

/**
 * 지금 경로가 어느 탭인지 돌려준다. 아래쪽 탭이 아닌 화면(로그인, 설정 등)은 "other".
 * @param {string | null | undefined} pathname expo-router 의 usePathname() 값. 예: "/schedule/detail"
 * @returns {"chat" | "family-chat" | "schedule" | "care" | "my" | "other"}
 */
export function tabFromPath(pathname) {
  const first = String(pathname || "").split("/").filter(Boolean)[0] || "";
  return TABS.includes(first) ? first : "other";
}

/**
 * 기기 날짜를 서버가 받는 모양(YYYY-MM-DD)으로 만든다.
 * @param {Date} at 시각
 * @returns {string}
 */
export function localDay(at) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`;
}
