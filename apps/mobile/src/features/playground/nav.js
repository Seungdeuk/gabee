/**
 * 놀이터 메인으로 나간다. 이미 스택에 놀이터 메인이 있으면 그 위의 화면만 닫아서(replace 로 메인을 한 번 더 쌓으면
 * 소통 탭으로 가려고 뒤로를 두 번 눌러야 한다) 한 번에 돌아가고, 없으면(링크로 바로 들어온 경우) 메인으로 이동한다.
 * @param {{ dismissTo: (href: string) => void }} router
 */
export function leaveToPlayMain(router) {
  router.dismissTo("/play");
}

/**
 * 폭탄 열린 방 목록(대기실)으로 간다. 로비 X·방 나가기에서 쓴다. 목록 화면의 X 는 leaveToPlayMain 으로 한 번에 메인까지 닫는다.
 * @param {{ replace: (href: string) => void }} router
 */
export function leaveToRoomList(router) {
  router.replace("/play/bomb-lobby");
}
