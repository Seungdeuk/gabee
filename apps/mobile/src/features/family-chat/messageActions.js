// 메시지 메뉴(반응·답장·공지·복사·삭제)·더블탭 하트·삭제 표시의 순수 함수(화면·네트워크와 분리해 시험한다). 메시지 글자는 어디에도 기록하지 않는다.
/** 메뉴·더블탭이 쓰는 반응 이모지 6개(서버 허용 목록과 같다, 표시 순서). */
export const REACTIONS = [
  { emoji: "❤️", name: "하트" },
  { emoji: "👍", name: "좋아요" },
  { emoji: "😂", name: "웃겨요" },
  { emoji: "😮", name: "놀라워요" },
  { emoji: "😢", name: "슬퍼요" },
  { emoji: "🙏", name: "감사해요" },
];
export const HEART = REACTIONS[0].emoji;

export const DELETED_TEXT = "삭제된 메시지입니다";
export const REPLY_PHOTO_TEXT = "사진";
export const REPLY_FILE_TEXT = "파일";
export const DELETE_TITLE = "이 메시지를 삭제할까요?";
export const DELETE_BODY = "삭제하면 모두에게서 삭제돼요";

/** 두 번 누르는 간격(밀리초). */
export const DOUBLE_TAP_MS = 300;

/** 열어 둔 화면이 반응·삭제를 따라가도록 폴링 몇 틱마다 최근 메시지를 다시 받는지(기본 3초 틱이면 약 9초). */
export const REFRESH_EVERY_TICKS = 3;
export const REFRESH_LIMIT = 50;

/**
 * 서버에 저장된 메시지인지(임시: 전송 중·실패 제외, 숫자 id 가 있어야 한다).
 * @param {{ id?: unknown, clientId?: string, status?: string } | null | undefined} message
 * @returns {boolean}
 */
const isSaved = (message) => Boolean(message) && !message.clientId && message.status !== "sending" && message.status !== "failed" && Number.isInteger(Number(message.id)) && Number(message.id) >= 1;

/**
 * 반응·답장 메뉴를 열어도 되는 메시지인지: 서버에 저장됐고 지우지 않은 메시지.
 * @param {object | null | undefined} message
 * @returns {boolean}
 */
export const canOpenMenu = (message) => isSaved(message) && !message.deleted;

/**
 * 메뉴에 보일 항목 키를 순서대로. 반응 줄은 항상 맨 위(reactions)다.
 * 답장·삭제(내가 보낸 것만, 가비의 답 제외)는 사진 메시지·공유 카드에도 열리고, 복사·공지는 글자가 있는 메시지에만 열린다(공유 카드는 제외).
 * readOnly(상대가 나간 1:1 방)이면 새로 보내는 일인 답장과 공지 등록을 뺀다(반응·복사·내 글 삭제·공지 내리기는 그대로).
 * @param {{ message: object, myId?: string | null, pinned?: boolean, readOnly?: boolean }} args
 * @returns {("reactions" | "reply" | "pin" | "unpin" | "copy" | "delete")[]}
 */
export function menuKeys({ message, myId = null, pinned = false, readOnly = false }) {
  if (!canOpenMenu(message)) return [];
  const keys = readOnly ? ["reactions"] : ["reactions", "reply"];
  const hasText = String(message.text ?? "").trim().length > 0;
  const isCard = Boolean(message.share); // 공유 카드의 text 는 고정 문구라 공지·복사 대상이 아니다
  if (hasText && !message.attachment && !isCard && (pinned || !readOnly)) keys.push(pinned ? "unpin" : "pin");
  if (hasText && !isCard) keys.push("copy");
  if (myId && message.user_id === myId && !message.is_assistant) keys.push("delete");
  return keys;
}

/**
 * 내가 이 메시지에 누른 반응 이모지(없으면 null).
 * @param {{ reactions?: { emoji: string, mine: boolean }[] } | null | undefined} message
 * @returns {string | null}
 */
export const myReaction = (message) => (message?.reactions ?? []).find((r) => r.mine)?.emoji ?? null;

/**
 * 반응 줄 정렬: 많은 순, 같으면 허용 목록 순서(서버와 같은 규칙).
 * @param {{ emoji: string, count: number, mine: boolean }[]} list
 * @returns {{ emoji: string, count: number, mine: boolean }[]}
 */
export function sortReactions(list) {
  const order = new Map(REACTIONS.map((r, i) => [r.emoji, i]));
  return [...list].sort((a, b) => b.count - a.count || (order.get(a.emoji) ?? 99) - (order.get(b.emoji) ?? 99));
}

/**
 * 내 반응을 바꾼 결과를 미리 그려 본다(서버 응답 전). 이전 내 반응은 한 명 줄이고, 새 이모지(null 이면 취소)는 한 명 늘린다.
 * @param {object} message
 * @param {string | null} emoji 새 반응(취소면 null)
 * @returns {object} reactions 만 바뀐 새 메시지
 */
export function withMyReaction(message, emoji) {
  const next = [];
  for (const r of message.reactions ?? []) {
    if (r.mine) {
      if (r.count > 1) next.push({ ...r, count: r.count - 1, mine: false });
    } else next.push({ ...r }); // 원본 객체를 바꾸지 않도록 복사한다
  }
  if (emoji) {
    const same = next.find((r) => r.emoji === emoji);
    if (same) {
      same.mine = true;
      same.count += 1;
    } else next.push({ emoji, count: 1, mine: true });
  }
  return { ...message, reactions: sortReactions(next) };
}

/**
 * 더블탭·반응 칩을 눌렀을 때 보낼 일: 이미 같은 이모지면 취소, 아니면 그 이모지로 정한다.
 * @param {object} message
 * @param {string} emoji
 * @returns {{ type: "set" | "remove", emoji: string }}
 */
export const reactionAction = (message, emoji) => (myReaction(message) === emoji ? { type: "remove", emoji } : { type: "set", emoji });

/**
 * 지운 메시지를 미리 그려 본다(서버 응답 전): 글자·사진·공유 카드·반응·답장 표시를 비운다.
 * @param {object} message
 * @returns {object}
 */
export const markDeleted = (message) => ({ ...message, deleted: true, text: "", attachment: null, share: null, reactions: [], reply_to: null });

/**
 * 서버가 알려 준 삭제 id 를 목록에 반영한다: 아직 지우지 않은 그 메시지를 삭제 표시로 바꾸고, 그 메시지를 인용한 답장도 삭제 표시로 바꾼다. 목록에 없는 id 는 무시한다.
 * @param {object[]} messages
 * @param {number[]} ids
 * @returns {object[]} 바뀐 것이 없으면 같은 배열
 */
export function applyDeletedIds(messages, ids) {
  const set = new Set((ids ?? []).map(Number));
  if (set.size === 0) return messages;
  let next = messages.map((m) => (!m.clientId && !m.deleted && set.has(Number(m.id)) ? markDeleted(m) : m));
  for (const id of set) next = markRepliesDeleted(next, id);
  return next.every((m, i) => m === messages[i]) ? messages : next;
}

/**
 * 어떤 메시지를 지웠을 때 그 메시지를 인용한 답장들의 원본 표시를 "삭제됨"으로 바꾼다(서버 응답을 기다리지 않고 바로 반영).
 * @param {object[]} messages
 * @param {number|string} deletedId
 * @returns {object[]} 바뀐 것이 없으면 같은 배열
 */
export function markRepliesDeleted(messages, deletedId) {
  const id = Number(deletedId);
  let changed = false;
  const next = messages.map((m) => {
    if (m.reply_to?.id !== id || m.reply_to.deleted) return m;
    changed = true;
    return { ...m, reply_to: { ...m.reply_to, deleted: true, text: "", has_attachment: false } };
  });
  return changed ? next : messages;
}

/**
 * 답장 대상을 입력창·임시 메시지에 보일 미리보기로(글자 40자까지).
 * @param {{ id: number|string, user_name?: string, text?: string, attachment?: object | null, deleted?: boolean }} message
 * @param {(userId: string) => string | undefined} [nameOf]
 * @returns {{ id: number, user_name: string, text: string, deleted: boolean, has_attachment: boolean, attachment_kind: string | null }}
 */
export function replyPreview(message, nameOf) {
  const deleted = Boolean(message.deleted);
  return {
    id: Number(message.id),
    user_name: nameOf?.(message.user_id) || message.user_name || "가족",
    text: deleted ? "" : String(message.text ?? "").replace(/\s+/g, " ").trim().slice(0, 40),
    deleted,
    has_attachment: !deleted && Boolean(message.attachment),
    attachment_kind: !deleted && message.attachment?.kind ? message.attachment.kind : null,
  };
}

/**
 * 답장 원본 한 줄: 지웠으면 "삭제된 메시지입니다", 글자가 없는 사진이면 "사진", 파일이면 "파일".
 * @param {{ text?: string, deleted?: boolean, has_attachment?: boolean, attachment_kind?: string | null } | null | undefined} reply
 * @returns {string}
 */
export function replyLine(reply) {
  if (!reply) return "";
  if (reply.deleted) return DELETED_TEXT;
  const text = String(reply.text ?? "").trim();
  if (text) return text;
  // 서버가 준 attachment_kind 를 먼저 따르고, 없을 때만 has_attachment 로 사진 취급(하위 호환)
  if (reply.attachment_kind === "file") return REPLY_FILE_TEXT;
  if (reply.attachment_kind === "image" || reply.has_attachment) return REPLY_PHOTO_TEXT;
  return "";
}

/**
 * 메뉴를 띄울 위치. 말풍선 위치(anchor.rect)를 알면 그 **말풍선 바로 아래**에 붙인다(내 말풍선은 오른쪽 끝, 상대는 왼쪽 끝에 맞춤, 아래가 모자라면 말풍선 위로).
 * 말풍선 위치를 모르면 누른 지점(anchor.x, anchor.y) 근처에 둔다. 어느 쪽이든 화면 밖으로 나가지 않게 맞춘다.
 * @param {{ x: number, y: number, rect?: { x: number, y: number, width: number, height: number }, side?: "left" | "right" }} anchor
 * @param {{ width: number, height: number }} size 메뉴 크기
 * @param {{ width: number, height: number }} screen 화면 크기
 * @param {number} [margin] 화면 가장자리·말풍선과의 여백
 * @returns {{ left: number, top: number }}
 */
export function menuPosition(anchor, size, screen, margin = 8) {
  const clampLeft = (left) => Math.min(Math.max(left, margin), Math.max(margin, screen.width - size.width - margin));
  const { rect } = anchor;
  if (rect) {
    const left = clampLeft(anchor.side === "right" ? rect.x + rect.width - size.width : rect.x);
    const below = rect.y + rect.height + margin / 2;
    if (below + size.height + margin <= screen.height) return { left, top: below };
    const above = rect.y - size.height - margin / 2;
    return { left, top: above >= margin ? above : Math.max(margin, screen.height - size.height - margin) };
  }
  const left = clampLeft(anchor.x - size.width / 2);
  const below = anchor.y + margin;
  const top = below + size.height + margin <= screen.height ? below : Math.max(margin, anchor.y - size.height - margin);
  return { left, top };
}

/**
 * 두 번 눌렀는지.
 * @param {number | null} previous 앞선 누름 시각(밀리초, 없으면 null)
 * @param {number} now 이번 누름 시각
 * @returns {boolean}
 */
export const isDoubleTap = (previous, now) => previous != null && now - previous <= DOUBLE_TAP_MS;

/**
 * 폴링 틱 수로 다시 받을 때인지.
 * @param {number} ticks 마지막 갱신 뒤 지난 틱 수
 * @returns {boolean}
 */
export const refreshDue = (ticks) => ticks >= REFRESH_EVERY_TICKS;

/**
 * 다시 받은 최근 메시지로 이미 가진 메시지만 갱신한다(반응·삭제·공유 카드 반영: 카드 없이 굳은 메시지도 서버가 카드를 주면 복구한다). 목록에 없는 메시지는 넣지 않아 새 메시지 확인 기준(cursor)과 겹치지 않는다.
 * 임시(전송 중·실패) 메시지는 그대로 둔다.
 * @param {object[]} existing
 * @param {object[]} incoming 서버가 돌려준 최근 메시지
 * @returns {object[]} 바뀐 것이 없으면 같은 배열
 */
export function refreshExisting(existing, incoming) {
  const byId = new Map((incoming ?? []).map((m) => [Number(m.id), m]));
  let changed = false;
  const next = existing.map((m) => {
    if (m.clientId) return m;
    const fresh = byId.get(Number(m.id));
    if (!fresh) return m;
    const same = Boolean(m.deleted) === Boolean(fresh.deleted) && Boolean(m.share) === Boolean(fresh.share) && JSON.stringify(m.reactions ?? []) === JSON.stringify(fresh.reactions ?? []) && m.text === fresh.text && (m.reply_to?.deleted ?? false) === (fresh.reply_to?.deleted ?? false);
    if (same) return m;
    changed = true;
    return { ...m, ...fresh };
  });
  return changed ? next : existing;
}

/**
 * 반응·삭제 오류를 사용자 문장으로(메시지 글자는 넣지 않는다).
 * @param {{ code?: string, status?: number } | null | undefined} error
 * @param {"react" | "delete" | "reply"} [action]
 * @returns {string}
 */
export function messageActionError(error, action = "react") {
  if (error?.code === "reply_deleted") return "답장하려던 메시지가 삭제돼서 답장 없이 보낼 수 있어요. 다시 보내기를 눌러 주세요";
  if (error?.code === "message_deleted") return "삭제된 메시지예요";
  if (error?.code === "invalid_reaction") return "쓸 수 없는 반응이에요";
  if (error?.code === "invalid_message") return "이 대화방의 메시지가 아니에요";
  if (error?.status === 403) return "내가 보낸 메시지만 삭제할 수 있어요";
  if (error?.status === 404) return "메시지를 찾을 수 없어요";
  if (error?.status === 429) return "너무 자주 눌렀어요. 잠시 뒤에 다시 해 주세요";
  if (error?.status === 0 || error?.code === "network_error") return "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요";
  return action === "delete" ? "삭제하지 못했어요. 다시 시도해 주세요" : action === "reply" ? "답장을 보내지 못했어요" : "반응을 남기지 못했어요. 다시 시도해 주세요";
}

/**
 * 반응 칩의 접근성 라벨.
 * @param {{ emoji: string, count: number, mine: boolean }} reaction
 * @returns {string}
 */
export function reactionLabel(reaction) {
  const name = REACTIONS.find((r) => r.emoji === reaction.emoji)?.name ?? "반응";
  return `${name} ${reaction.count}명${reaction.mine ? ", 내가 누름. 누르면 취소해요" : ", 누르면 나도 눌러요"}`;
}
