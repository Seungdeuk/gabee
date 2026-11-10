// 상대가 나가서 읽기 전용이 된 1:1 방의 화면 규칙(순수 함수, 화면·네트워크와 분리해 시험한다).

/**
 * 채팅방 위쪽 AI 도우미 버튼의 상태. 상대가 나간 방은 서버가 AI 를 막으므로(403 peer_left) 누르기 전에 비활성하고,
 * 이유는 스크린 리더 라벨에 적는다(다른 버튼과 같이 숨기지 않고 자리를 지킨다).
 * @param {{ ready: boolean, peerLeft: boolean }} args ready: 방 정보를 불러왔는지, peerLeft: 상대가 방을 나갔는지
 * @returns {{ disabled: boolean, label: string }}
 */
export function aiHelperButton({ ready, peerLeft }) {
  if (peerLeft) return { disabled: true, label: "AI 도우미 (상대가 나가서 쓸 수 없어요)" };
  return { disabled: !ready, label: "AI 도우미 열기" };
}
