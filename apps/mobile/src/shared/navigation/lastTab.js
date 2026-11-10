// 알림함 같은 탭 밖 화면에서 "뒤로"를 눌렀을 때, 사용자가 마지막으로 보던 탭으로 돌아가기 위한 기억.
// 앱이 떠 있는 동안만 기억한다(저장하지 않는다). 콜드 스타트 뒤에는 기본값(AI 채팅 탭)이다.

/** 탭 라우트 이름 → 경로. 하단 탭 5개(AI 채팅, 소통, 일정, 지갑, 마이)와 (tabs)/_layout.js 의 name 이 같다. */
const TAB_PATHS = {
  chat: "/chat",
  "family-chat": "/family-chat",
  schedule: "/schedule",
  care: "/care",
  my: "/my",
};

const DEFAULT_TAB = "chat";

let lastTab = DEFAULT_TAB;

/**
 * 마지막으로 보던 탭을 기억한다. 탭이 아닌 이름은 무시한다.
 * @param {string} name 탭 라우트 이름("chat", "family-chat", "schedule", "care", "my")
 * @returns {void}
 */
export function rememberTab(name) {
  if (Object.hasOwn(TAB_PATHS, name)) lastTab = name;
}

/**
 * 마지막으로 보던 탭의 경로. 기억한 게 없으면 AI 채팅 탭이다.
 * @returns {string} 예: "/chat"
 */
export function lastTabPath() {
  return TAB_PATHS[lastTab];
}

/**
 * 뒤로 갈 곳을 정한다: 돌아갈 화면이 있으면 "back"(그냥 뒤로), 없으면(푸시로 바로 열린 경우) 탭 경로.
 * @param {boolean} canGoBack 라우터가 뒤로 갈 수 있는지
 * @param {string} tabPath 마지막 탭 경로
 * @returns {string} "back" 또는 tabPath
 */
export function backTarget(canGoBack, tabPath) {
  return canGoBack ? "back" : tabPath;
}
