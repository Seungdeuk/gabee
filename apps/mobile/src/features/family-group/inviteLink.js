// 가족 초대 링크와 공유 문구. 앱 주소(gabee://…)는 화면이 expo-linking 으로 만들어 넘긴다(이 파일은 node 테스트로도 돈다).

const CODE_PATTERN = /^[A-Z0-9]{4,12}$/;

/**
 * 초대 링크. 공개 초대 페이지 주소(EXPO_PUBLIC_INVITE_PAGE_URL)가 있으면 카카오톡·SNS 에서 눌리는 https 링크,
 * 없으면 앱을 바로 여는 주소(appLink)를 쓴다.
 */
export function inviteLink(code, appLink, pageBase = process.env.EXPO_PUBLIC_INVITE_PAGE_URL) {
  if (!CODE_PATTERN.test(code)) return "";
  if (pageBase) return `${pageBase.replace(/\/+$/, "")}/?code=${encodeURIComponent(code)}`;
  return appLink ?? "";
}

/** 공유 문구. 링크가 안 열리는 메신저에서도 손으로 넣을 수 있게 코드를 함께 적는다. */
export function inviteMessage(code, link) {
  const lines = ["가비 가족 초대가 왔어요!"];
  if (link) lines.push(`아래 링크를 누르면 바로 참여할 수 있어요.\n${link}`);
  lines.push(`링크가 안 열리면 가비 앱의 "초대 코드로 참여"에 ${code} 를 입력해 주세요.`);
  return lines.join("\n\n");
}
