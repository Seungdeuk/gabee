// 소통 푸시를 눌렀을 때 열 채팅방 경로를 정하는 순수 함수. 푸시에는 방 id 만 있어서(보낸 사람 id 등은 외부 푸시 서버로 보내지 않는다)
// 방 목록으로 가족방인지 1:1 인지, 1:1 이면 상대가 누구인지 찾는다.

/** 방을 찾지 못했을 때 가는 곳: 소통 탭 목록. */
const LIST_ROUTE = "/family-chat";

/**
 * 방 id 로 열 채팅방 경로를 정한다. 가족 전체방은 인자 없는 /chat-room(roomId 를 주면 1:1 로 취급된다),
 * 1:1 방은 roomId 와 상대 id(peer)를 넘긴다. 방을 못 찾으면 소통 탭 목록이다.
 * @param {{ id: string, kind: "family" | "direct", peer_user_id?: string | null }[] | null | undefined} rooms 내 방 목록(`GET /family-chat/rooms`)
 * @param {string | undefined} roomId 푸시 data 의 room_id
 * @returns {string | { pathname: string, params: { roomId: string, peer: string } }}
 */
export function chatRouteFor(rooms, roomId) {
  const room = Array.isArray(rooms) ? rooms.find((r) => r.id === roomId) : undefined;
  if (!room) return LIST_ROUTE;
  if (room.kind === "family") return "/chat-room";
  return { pathname: "/chat-room", params: { roomId: room.id, peer: room.peer_user_id ?? "" } };
}
