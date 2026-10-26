// 소통 탭 목록 순수 함수(화면과 분리해 시험한다). 대화 글자는 어디에도 기록하지 않는다.
import { formatTime, parseTime } from "./chatUtils";

const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

/**
 * 채팅 목록의 시각: 오늘이면 "오후 3:20", 어제면 "어제", 그 외 "10월 21일".
 * @param {string} iso
 * @param {Date} [now]
 * @returns {string}
 */
export function formatRoomTime(iso, now = new Date()) {
  const d = parseTime(iso);
  if (Number.isNaN(d.getTime())) return "";
  if (sameDay(d, now)) return formatTime(iso);
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (sameDay(d, yesterday)) return "어제";
  return `${d.getMonth() + 1}월 ${d.getDate()}일`;
}

/**
 * 접근성 라벨. 안 읽은 메시지가 있으면 수를 함께 읽어 준다.
 * @param {string} last 마지막 메시지 미리보기
 * @param {number} [unread] 안 읽은 메시지 수
 * @param {string} [title] 방 설명(기본 "가족 채팅방", 1:1 방은 "<이름>님과 1:1 대화")
 * @returns {string}
 */
export const roomA11yLabel = (last, unread = 0, title = "가족 채팅방") => (unread > 0 ? `${title}, 안 읽은 메시지 ${unreadBadgeText(unread)}개, 마지막 메시지 ${last}` : `${title}, 마지막 메시지 ${last}`);

/**
 * 방 이름 검색 필터(공백 무시, 빈 검색어는 모두 통과).
 * @param {string} name
 * @param {string} query
 * @returns {boolean}
 */
export function matchesQuery(name, query) {
  const q = String(query ?? "").trim();
  return !q || String(name ?? "").includes(q);
}

/**
 * 안 읽은 수 배지 문구: 0 이하면 빈 문자열(숨김), 99 를 넘으면 "99+".
 * @param {number} count
 * @returns {string}
 */
export function unreadBadgeText(count) {
  const n = Number(count);
  if (!Number.isFinite(n) || n <= 0) return "";
  return n > 99 ? "99+" : String(Math.floor(n));
}

/**
 * 내 말풍선 옆 "아직 N명이 읽지 않았어요" 접근성 라벨.
 * @param {number} count
 * @returns {string}
 */
export const unreadByA11yLabel = (count) => `아직 ${count}명이 읽지 않았어요`;

/**
 * 구성원 표시 이름(별명 우선).
 * @param {{ name?: string, display_name?: string | null } | null | undefined} member
 * @returns {string}
 */
export const memberName = (member) => member?.display_name || member?.name || "가족";

/**
 * 서버의 대화방 목록과 가족 정보로 소통 탭에 그릴 행을 만든다. 가족 전체방은 맨 위, 1:1 방은 서버가 준 순서 그대로다.
 * 1:1 방의 상대가 구성원 목록에 없으면(나간 사람) 이름을 "나간 가족"으로 둔다. 대화 글자는 미리보기 한 줄 말고는 쓰지 않는다.
 * @param {{ id: string, kind: string, peer_user_id: string | null, last_message: object | null, unread: number }[]} rooms
 * @param {{ name: string, my_id: string | null, members?: { id: string, name: string, display_name?: string | null, photo_url?: string | null }[] }} group
 * @param {(message: object | null, myId: string | null) => string} preview 마지막 메시지 한 줄 만들기
 * @param {(iso: string) => string} timeLabel 시각 글자 만들기
 * @returns {{ id: string, kind: string, name: string, last: string, time: string, unread: number, count?: number, tone?: string, peerId?: string, photoUrl: string | null, a11yTitle: string }[]}
 */
export function buildRoomRows(rooms, group, preview, timeLabel) {
  const members = Array.isArray(group?.members) ? group.members : [];
  const byId = Object.fromEntries(members.map((m) => [m.id, m]));
  return (Array.isArray(rooms) ? rooms : []).map((room) => {
    const message = room.last_message ?? null;
    const base = {
      id: room.id,
      kind: room.kind,
      last: preview(message, group?.my_id ?? null),
      time: message ? timeLabel(message.created_at) : "",
      unread: Number(room.unread) || 0,
    };
    if (room.kind === "direct") {
      const peer = byId[room.peer_user_id];
      const name = peer ? memberName(peer) : "나간 가족";
      return { ...base, name, peerId: room.peer_user_id ?? undefined, photoUrl: peer?.photo_url ?? null, a11yTitle: `${name}님과 1:1 대화` };
    }
    return { ...base, name: group?.name ?? "가족 채팅", count: members.length, tone: "blue", photoUrl: null, a11yTitle: "가족 채팅방" };
  });
}

/**
 * 새 대화 상대 후보: 나를 뺀 가족 구성원.
 * @param {{ id: string, name: string, display_name?: string | null, photo_url?: string | null }[]} members
 * @param {string | null} myId
 * @returns {{ id: string, name: string, photoUrl: string | null }[]}
 */
export const pickableMembers = (members, myId) =>
  (Array.isArray(members) ? members : []).filter((m) => m.id !== myId).map((m) => ({ id: m.id, name: memberName(m), photoUrl: m.photo_url ?? null }));

/**
 * 모든 방의 안 읽은 수 합계(소통 탭 아이콘 배지). 숫자가 아닌 값은 0 으로 본다.
 * @param {{ unread?: number }[] | null | undefined} rooms
 * @returns {number}
 */
export function totalUnread(rooms) {
  if (!Array.isArray(rooms)) return 0;
  return rooms.reduce((sum, room) => {
    const n = Number(room?.unread);
    return sum + (Number.isFinite(n) && n > 0 ? Math.floor(n) : 0);
  }, 0);
}
