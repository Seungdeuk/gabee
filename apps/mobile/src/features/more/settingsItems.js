/**
 * 환경설정 화면 구역(일반·시스템 설정·알림설정·개인 보안). 줄 모양은 마이 페이지 목록(MenuList)과 같다.
 * value 가 있으면 오른쪽에 글자로 보이고, static 줄은 화살표 없이 눌러도 아무 일 없다.
 * @param {string} versionLabel 앱 버전 문구(예: "v1.0.0", appInfo.versionText 의 결과)
 * @returns {{ key: string, title: string, items: { key: string, icon: string, title: string, subtitle: string, value?: string, static?: boolean, soon?: boolean, route?: string, action?: string }[] }[]}
 */
export function settingsSections(versionLabel) {
  return [
    {
      key: "general",
      title: "일반",
      items: [{ key: "version", icon: "information-circle-outline", title: "앱 버전", subtitle: "현재 설치된 버전", value: versionLabel, static: true }],
    },
    {
      key: "system",
      title: "시스템 설정",
      items: [{ key: "system-soon", icon: "construct-outline", title: "준비 중이에요", subtitle: "곧 만나요", static: true, soon: true }],
    },
    {
      key: "notifications",
      title: "알림설정",
      items: [{ key: "notifications", icon: "notifications-outline", title: "알림설정", subtitle: "푸시 알림을 켜고 꺼요", route: "/push-settings" }],
    },
    {
      key: "security",
      title: "개인 보안",
      items: [{ key: "logout", icon: "log-out-outline", title: "로그아웃", subtitle: "이 기기에서 로그아웃해요", action: "logout" }],
    },
  ];
}

/**
 * 환경설정 줄을 눌렀을 때 할 일.
 * @param {{ route?: string, action?: string, static?: boolean }} item
 * @returns {{ type: "route", path: string } | { type: "logout" } | { type: "none" }}
 */
export function settingsAction(item) {
  if (item.static) return { type: "none" };
  if (item.route) return { type: "route", path: item.route };
  if (item.action === "logout") return { type: "logout" };
  return { type: "none" };
}
