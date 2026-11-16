// 채팅방 서랍 · 사진 모음의 순수 함수(화면·네트워크와 분리해 시험한다). 사진 내용·대화 글자는 어디에도 기록하지 않는다.
import { formatTime, parseTime } from "./chatUtils";
import { memberName } from "./listUtils";
import { REVIEW_ENTRY_KEY, reviewRowTitle, shouldShowReviewRow } from "./photoChecks";
import { TIMELINE_ENTRY_KEY } from "./timeline";

/** 모음 화면 한 줄의 칸 수. */
export const GRID_COLUMNS = 3;

/** 모음 탭: 서버 kind 와 보이는 이름. */
export const MEDIA_KINDS = [
  { kind: "image", label: "사진" },
  { kind: "file", label: "파일" },
  { kind: "video", label: "동영상" },
];

/**
 * 두 자리로 맞춘다.
 * @param {number} n
 * @returns {string}
 */
const pad = (n) => String(n).padStart(2, "0");

/**
 * 월 구분 헤더 글자.
 * @param {string} iso 서버 시각(시간대 표시가 없으면 UTC)
 * @returns {string} 예: "2026년 10월" (시각을 읽지 못하면 "")
 */
export function monthLabel(iso) {
  const d = parseTime(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월`;
}

/**
 * 기기 시간대 기준 월 묶음 키. 시간대 표시가 없는 서버 시각은 UTC 로 읽는다(chatUtils.parseTime).
 * @param {string} iso
 * @returns {string} 예: "2026-10", 읽지 못하면 "unknown"
 */
const monthKey = (iso) => {
  const d = parseTime(iso);
  return Number.isNaN(d.getTime()) ? "unknown" : `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
};

/**
 * 달(기기 시간대)이 바뀌는 곳마다 나눈다. 순서는 서버가 준 그대로(최신 먼저)라서 같은 달이 이어져 있을 때만 한 묶음이 된다.
 * @param {{ created_at: string }[]} items
 * @returns {{ key: string, label: string, items: object[] }[]}
 */
export function groupByMonth(items) {
  const groups = [];
  for (const item of Array.isArray(items) ? items : []) {
    const key = monthKey(item.created_at);
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(item);
    else groups.push({ key, label: monthLabel(item.created_at), items: [item] });
  }
  return groups;
}

/**
 * 격자 목록(FlatList 데이터): 월 헤더 한 줄 다음에 칸 수만큼씩 끊은 줄들. 마지막 줄은 모자랄 수 있다(화면이 빈 칸을 채운다).
 * @param {{ created_at: string, attachment_id: string }[]} items
 * @param {number} [columns]
 * @returns {({ type: "header", key: string, label: string } | { type: "row", key: string, items: object[] })[]}
 */
export function buildGridItems(items, columns = GRID_COLUMNS) {
  const n = Math.max(1, Math.floor(columns) || GRID_COLUMNS);
  const out = [];
  for (const group of groupByMonth(items)) {
    out.push({ type: "header", key: `h-${group.key}-${group.items[0]?.attachment_id}`, label: group.label });
    for (let i = 0; i < group.items.length; i += n) {
      const row = group.items.slice(i, i + n);
      out.push({ type: "row", key: `r-${row[0].attachment_id}`, items: row });
    }
  }
  return out;
}

/**
 * 다음 쪽을 이어 붙인다(같은 attachment_id 는 한 번만).
 * @param {{ attachment_id: string }[]} prev
 * @param {{ attachment_id: string }[]} next
 * @returns {object[]}
 */
export function mergeMedia(prev, next) {
  const seen = new Set((prev ?? []).map((m) => m.attachment_id));
  const added = (next ?? []).filter((m) => !seen.has(m.attachment_id));
  return added.length ? [...(prev ?? []), ...added] : (prev ?? []);
}

/**
 * 서버 counts 를 숫자로 다듬는다(없거나 이상한 값은 0).
 * @param {{ image?: number, file?: number, video?: number } | null | undefined} counts
 * @returns {{ image: number, file: number, video: number }}
 */
export function normalizeCounts(counts) {
  /**
   * @param {unknown} v
   * @returns {number} 0 이상의 정수(아니면 0)
   */
  const num = (v) => (Number.isFinite(Number(v)) && Number(v) > 0 ? Math.floor(Number(v)) : 0);
  return { image: num(counts?.image), file: num(counts?.file), video: num(counts?.video) };
}

/**
 * 탭 글자: "사진 12" · "파일 0" · "동영상 3".
 * @param {{ image?: number, file?: number, video?: number } | null | undefined} counts
 * @returns {{ kind: string, label: string, count: number }[]}
 */
export function mediaTabs(counts) {
  const c = normalizeCounts(counts);
  return MEDIA_KINDS.map(({ kind, label }) => ({ kind, label: `${label} ${c[kind]}`, count: c[kind] }));
}

/**
 * 비어 있을 때의 안내문. 파일·동영상은 아직 보낼 수 없어서 사진과 다른 문구다.
 * @param {string} kind
 * @returns {string}
 */
export function emptyMediaText(kind) {
  if (kind === "file") return "아직 파일은 보낼 수 없어요. 사진부터 모아 둘게요";
  if (kind === "video") return "아직 동영상은 보낼 수 없어요. 사진부터 모아 둘게요";
  return "아직 공유된 사진이 없어요";
}

/**
 * 모음 불러오기 오류 문구(원인 코드는 문구에 넣지 않는다).
 * @param {{ status?: number } | null | undefined} error
 * @returns {string}
 */
export function mediaErrorMessage(error) {
  if (error?.status === 404) return "채팅방을 찾을 수 없어요";
  if (error?.status === 429) return "잠시 후 다시 시도해 주세요";
  if (error?.status === 0) return "서버에 연결하지 못했어요";
  return "사진을 불러오지 못했어요";
}

/**
 * 전체 화면 보기 아래에 보이는 글: "엄마 · 2026년 10월 24일 오후 3:20".
 * @param {{ user_name?: string, created_at: string }} item
 * @param {(userId: string) => string | undefined} [nameOf] 사용자 id → 표시 이름(별명). 모르면 서버가 준 user_name
 * @returns {string}
 */
export function mediaCaption(item, nameOf) {
  const d = parseTime(item?.created_at);
  const who = nameOf?.(item?.user_id) || item?.user_name || "가족";
  if (Number.isNaN(d.getTime())) return who;
  return `${who} · ${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일 ${formatTime(item.created_at)}`;
}

/**
 * 저장할 파일 이름: gabee-20261024-152030-<id 앞부분>.jpg (서버가 항상 JPEG 으로 다시 만든다). 시각은 기기 시간대.
 * @param {{ attachment_id?: string, created_at?: string }} item
 * @returns {string}
 */
export function saveFileName(item) {
  const d = parseTime(item?.created_at);
  const stamp = Number.isNaN(d.getTime())
    ? "photo"
    : `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
  const id = String(item?.attachment_id ?? "").replace(/[^\w]/g, "").slice(0, 8);
  return `gabee-${stamp}${id ? `-${id}` : ""}.jpg`;
}

// ---------------------------------------------------------------------------------------------
// 채팅방 서랍

/** 서랍 행이 눌렸을 때 하는 일: open 은 화면 이동, search 는 부모가 연결한 검색 열기(없으면 준비 중), soon 은 준비 중 안내, leave 는 나가기 안내. */
export const SOON_NOTICE = "준비 중이에요";
export const FAMILY_LEAVE_NOTICE = "가족 채팅방은 나갈 수 없어요";

/**
 * 방 이름: 가족 전체방은 가족 이름, 1:1 은 상대의 표시 이름.
 * @param {{ direct: boolean, room?: { name?: string, members?: object[] } | null, peerId?: string | null }} args
 * @returns {string}
 */
export function drawerTitle({ direct, room, peerId }) {
  if (!direct) return room?.name || "가족 채팅";
  const peer = (room?.members ?? []).find((m) => m.id === peerId);
  return peer ? memberName(peer) : "1:1 대화";
}

/**
 * 서랍 맨 위 구성원 줄. 가족 전체방은 "가족 구성원 N명"과 전원(나 먼저), 1:1 은 "대화 상대"와 상대 한 명.
 * 이름은 표시 이름(별명) 우선이다. 상대가 구성원 목록에 없으면(나간 가족) 줄이 비어 있다.
 * @param {{ direct: boolean, room?: { members?: object[] } | null, peerId?: string | null, myId?: string | null }} args
 * @returns {{ heading: string, members: { id: string, name: string, photoUrl: string | null }[] }}
 */
export function drawerMembers({ direct, room, peerId, myId }) {
  const all = Array.isArray(room?.members) ? room.members : [];
  const pick = direct ? all.filter((m) => m.id === peerId) : [...all.filter((m) => m.id === myId), ...all.filter((m) => m.id !== myId)];
  const members = pick.map((m) => ({ id: m.id, name: memberName(m), photoUrl: m.photo_url ?? null }));
  return { heading: direct ? "대화 상대" : `가족 구성원 ${members.length}명`, members };
}

const MANAGE_ROWS = [
  { key: "pins", icon: "pin-outline", title: "게시판", subtitle: "공지 모아보기", action: "pins" },
  { key: "media", icon: "images-outline", title: "사진 · 동영상", subtitle: "채팅방에 공유된 미디어", action: "open" },
  { key: "familytodos", icon: "list-outline", title: "가족 할 일", subtitle: "일정 탭의 일정·할 일과 함께하기", action: "open" },
];

const SETTING_ROWS = [
  { key: "notifications", icon: "notifications-outline", title: "이 방 알림", subtitle: "끄면 이 방의 알림을 받지 않아요", action: "mute" },
  { key: "leave", icon: "exit-outline", title: "채팅방 나가기", subtitle: "", action: "leave", danger: true },
];

/**
 * 방 종류별 서랍 행. 채팅 관리: 게시판 · 사진 · 동영상 · 가족 할 일(대화에서 등록한 할 일 포함), 채팅방 설정: 이 방 알림(켜기/끄기 스위치) · 채팅방 나가기. 검색은 채팅방 위 돋보기로 하고,
 * 구성원 초대·관리, AI · 개인정보 설정, 채팅방 정보 수정, 공유 문서 행은 서랍에서 뺐다. 가족방과 1:1 방의 행은 같다.
 * 각 행의 state: "open" 이면 동작, "soon" 이면 "준비 중" 배지. 게시판 행은 연결(pinsReady)이 있을 때만 동작한다.
 * 나가기 행의 notice 는 눌렀을 때의 안내 문구다.
 * 알림 행(kind "switch")은 value 가 "알림 켜짐"이고, 이 방의 muted 값을 아직 모르면(muted 가 null/undefined) disabled 다.
 * 가족 전체방에는 "채팅 관리"의 사진 · 동영상 아래에 "가족 타임라인" 행이 붙고(1:1 방에는 없다), 그 아래에 reviewCount(내가 올린 사진 중 확인이 필요한 장수)가 1 이상일 때만 "확인이 필요한 사진 N장" 행이 붙는다(0·모름·1:1 방에는 없다).
 * @param {{ direct: boolean, pinsReady?: boolean, muted?: boolean | null, reviewCount?: number | null }} args muted 는 이 방의 알림 끔 여부(모르면 null), reviewCount 는 확인이 필요한 사진 수(모르면 null)
 * @returns {{ title: string, rows: { key: string, icon: string, title: string, subtitle: string, action: string, state: "open" | "soon", danger?: boolean, notice?: string, kind?: "switch", value?: boolean, disabled?: boolean }[] }[]}
 */
export function buildDrawerSections({ direct, pinsReady = false, muted = null, reviewCount = null }) {
  /**
   * 정의 행을 화면 행으로: 동작 여부(state)와 나가기 안내(notice)를 붙인다.
   * @param {object} row
   * @returns {object}
   */
  const make = (row) => {
    if (row.action === "mute") return { ...row, state: "open", kind: "switch", value: muted === false, disabled: muted == null };
    const live = row.action === "open" || (row.action === "pins" && pinsReady);
    const state = row.action === "leave" ? "open" : live ? "open" : "soon";
    return { ...row, state, ...(row.action === "leave" ? { notice: direct ? SOON_NOTICE : FAMILY_LEAVE_NOTICE } : {}) };
  };
  const manage = MANAGE_ROWS.map(make);
  if (!direct) {
    const at = manage.findIndex((r) => r.key === "media") + 1;
    manage.splice(at, 0, make({ key: TIMELINE_ENTRY_KEY, icon: "time-outline", title: "가족 타임라인", subtitle: "일반 사진으로 확인된 사진 모아보기", action: "open" }));
  }
  if (!direct && shouldShowReviewRow(reviewCount)) {
    const at = manage.findIndex((r) => r.key === TIMELINE_ENTRY_KEY) + 1;
    manage.splice(at, 0, make({ key: REVIEW_ENTRY_KEY, icon: "alert-circle-outline", title: reviewRowTitle(reviewCount), subtitle: "내가 올린 사진이 일반 사진인지 확인해 주세요", action: "open" }));
  }
  return [
    { title: "채팅 관리", rows: manage },
    { title: "채팅방 설정", rows: SETTING_ROWS.map(make) },
  ];
}

/**
 * 서랍 행을 눌렀을 때 할 일. 화면 이동은 media(모음)·pins(게시판)·familytodos(/family-together)이고, 그 밖에는 안내 문구만 보인다.
 * 이동이 아닌 행(준비 중, 나가기)이나 아직 동작하지 않는 행은 notice 다.
 * @param {{ key: string, state: "open" | "soon", notice?: string }} row buildDrawerSections 의 행
 * 알림 행은 mute(바뀔 muted 값 — 지금 켜져 있으면 끄는 것)이고, 아직 값을 모르면(disabled) 아무 일도 없다(none).
 * @returns {{ type: "media" | "photochecks" | "timeline" | "pins" | "familytodos" | "none" } | { type: "mute", muted: boolean } | { type: "notice", text: string }}
 */
export function resolveRowAction(row) {
  if (row.key === "notifications") return row.disabled ? { type: "none" } : { type: "mute", muted: row.value === true };
  if (row.key === "media") return { type: "media" };
  if (row.key === REVIEW_ENTRY_KEY && row.state === "open") return { type: "photochecks" };
  if (row.key === TIMELINE_ENTRY_KEY && row.state === "open") return { type: "timeline" };
  if (row.key === "pins" && row.state === "open") return { type: "pins" };
  if (row.key === "familytodos" && row.state === "open") return { type: "familytodos" };
  return { type: "notice", text: row.notice ?? SOON_NOTICE };
}

/**
 * 이동 행을 눌러도 되는지. 서랍이 닫히는 중이거나 이미 한 번 눌렀으면 무시한다(이동이 두 번 일어나지 않게).
 * @param {{ visible: boolean, locked: boolean }} state
 * @returns {boolean}
 */
export const canNavigateFromDrawer = ({ visible, locked }) => visible && !locked;

/**
 * 썸네일 경로: 서버가 thumb_url 을 비워 두면(null) 원본으로 대신한다.
 * @param {{ thumb_url?: string | null, url: string }} item
 * @returns {string}
 */
export const thumbPath = (item) => item.thumb_url ?? item.url;
