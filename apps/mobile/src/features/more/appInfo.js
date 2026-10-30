/**
 * 앱 버전을 화면에 보일 문구로 바꾼다. 버전을 알 수 없으면 안내 문구를 돌려준다.
 * @param {string | null | undefined} version app.json 의 version (예: "1.0.0")
 * @returns {string}
 */
export function versionText(version) {
  const v = typeof version === "string" ? version.trim() : "";
  return v ? `v${v.replace(/^v/i, "")}` : "확인할 수 없어요";
}
