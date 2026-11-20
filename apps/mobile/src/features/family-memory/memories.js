// 가족 추억 후보 화면의 순수 함수·문구·상태 전이(화면·네트워크와 분리돼 있어 `npm test` 로 시험한다).
// 서버가 준 후보(비공개, 자동 게시 없음)를 그대로 보여 줄 뿐 장소·인물·감정을 추론하지 않는다. 제목은 촬영 날짜만으로 만든 중립 문구다.
// 사진 내용·주소는 어디에도 기록하지 않고, 주소는 기존 채팅 사진 주소 규칙(`photoPath`)을 통과한 것만 쓴다.

import { photoPath } from "@/shared/photoCache";

export const MEMORIES_TITLE = "가족 추억 후보";
export const MEMORIES_HINT = "가족 사진을 날짜와 비슷한 장면으로 묶은 후보예요. 아직 게시되지 않았어요.";
export const MEMORIES_EMPTY = "아직 추억 후보가 없어요";
export const MEMORIES_EMPTY_HINT = "사진이 더 모이고 조건이 맞으면 여기에 보여요";
export const MEMORIES_UNAVAILABLE = "추억 기능은 아직 열려 있지 않아요";
export const MEMORIES_UNAVAILABLE_HINT = "열리면 이곳에서 가족 사진을 모아 볼 수 있어요";
export const MEMORIES_AUTH_EXPIRED = "로그인이 만료됐어요. 다시 로그인해 주세요";
export const MEMORIES_FORBIDDEN = "이 가족의 추억을 볼 수 없어요";
export const MEMORIES_NETWORK = "서버에 연결하지 못했어요. 연결을 확인하고 다시 시도해 주세요";
export const MEMORIES_ERROR = "추억 후보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요";
export const UNKNOWN_DATE = "촬영 날짜를 알 수 없어요";
export const MIN_PHOTOS = 3; // 서버가 3장면 미만 후보를 숨기는 것과 같은 기준: 사진이 빠져 3장 미만이 되면 화면에서도 후보를 숨긴다

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;

/**
 * 시각(ISO 8601)을 한국 시간 기준 연·월·일로. 읽을 수 없으면 null.
 * @param {unknown} iso
 * @returns {{ y: number, m: number, d: number } | null}
 */
export function kstDate(iso) {
  if (typeof iso !== "string" || !iso) return null;
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return null;
  const date = new Date(ms + KST_OFFSET_MS);
  return { y: date.getUTCFullYear(), m: date.getUTCMonth() + 1, d: date.getUTCDate() };
}

const full = (p) => `${p.y}년 ${p.m}월 ${p.d}일`;

/**
 * 촬영 날짜 범위 문구. 같은 날이면 그 날짜, 같은 해면 "5월 1일 ~ 5월 3일"처럼 짧게, 해가 다르면 둘 다 연도까지. 날짜가 없으면 null.
 * @param {string | null | undefined} startsAt
 * @param {string | null | undefined} endsAt
 * @returns {string | null}
 */
export function dateRangeLabel(startsAt, endsAt) {
  const a = kstDate(startsAt);
  const b = kstDate(endsAt ?? startsAt);
  if (!a && !b) return null;
  const s = a ?? b;
  const e = b ?? a;
  if (s.y === e.y && s.m === e.m && s.d === e.d) return full(s);
  if (s.y === e.y) return `${full(s)} ~ ${e.m}월 ${e.d}일`;
  return `${full(s)} ~ ${full(e)}`;
}

/**
 * 후보 카드 제목: 촬영 날짜만으로 만든 중립 문구(장소·인물·감정을 추론하지 않는다). 날짜가 없으면 "촬영 날짜를 알 수 없어요".
 * @param {{ starts_at?: string | null, ends_at?: string | null }} candidate
 * @returns {string}
 */
export function candidateTitle(candidate) {
  return dateRangeLabel(candidate?.starts_at, candidate?.ends_at) ?? UNKNOWN_DATE;
}

/**
 * 후보 카드 부제: 사진 수, 촬영 날짜가 없는 사진이 있으면 그 수(날짜를 지어내지 않는다).
 * @param {{ photo_count: number, undated_count?: number }} candidate
 * @returns {string}
 */
export function candidateSubtitle(candidate) {
  const count = `사진 ${candidate.photo_count}장`;
  return candidate.undated_count > 0 ? `${count} · 촬영 날짜 없는 사진 ${candidate.undated_count}장 포함` : count;
}

const str = (v) => (typeof v === "string" && v ? v : null);

/** 서버 사진 항목 하나를 화면이 쓰는 모양으로. 알려진 필드만 남기고 사진 주소가 허용된 모양이 아니면 버린다(null). */
function normalizePhoto(raw) {
  if (!raw || typeof raw !== "object") return null;
  const id = str(raw.attachment_id);
  const thumb = photoPath(raw.thumb_url);
  const photo = photoPath(raw.photo_url);
  if (!id || !thumb || !photo) return null;
  return { attachment_id: id, thumb_url: thumb, photo_url: photo, taken_at: str(raw.taken_at), is_representative: raw.is_representative === true };
}

/** 후보 하나를 정리한다. 사진이 `MIN_PHOTOS` 미만이거나 대표가 없으면 null(보이지 않는다). */
function normalizeCandidate(raw) {
  if (!raw || typeof raw !== "object" || !str(raw.id)) return null;
  const photos = (Array.isArray(raw.photos) ? raw.photos : []).map(normalizePhoto).filter(Boolean);
  if (photos.length < MIN_PHOTOS) return null;
  const repId = raw.representative?.attachment_id;
  const representative = photos.find((p) => p.attachment_id === repId) ?? photos.find((p) => p.is_representative) ?? photos[0];
  const dated = photos.filter((p) => p.taken_at != null);
  return {
    id: raw.id,
    status: "private",
    representative,
    photos: photos.map((p) => ({ ...p, is_representative: p.attachment_id === representative.attachment_id })),
    photo_count: photos.length,
    dated_count: dated.length,
    undated_count: photos.length - dated.length,
    starts_at: str(raw.starts_at),
    ends_at: str(raw.ends_at),
    updated_at: str(raw.updated_at),
  };
}

/**
 * `GET /family-memory/candidates` 응답을 화면용으로 정리한다. 알 수 없는 필드는 버리고, 사진 수·날짜는 실제로 받은 사진 기준으로 다시 센다.
 * @param {unknown} data
 * @returns {object[]}
 */
export function normalizeCandidates(data) {
  const items = Array.isArray(data?.items) ? data.items : [];
  return items.map(normalizeCandidate).filter(Boolean);
}

/**
 * 오류를 화면 상태로 바꾼다. **404 는 "추억 없음"이 아니라 기능 미출시**(서버의 미출시 가드)다. 빈 목록은 200 + items=[] 로만 온다.
 * @param {{ status?: number } | null | undefined} error ApiError
 * @returns {{ kind: "unavailable" | "auth" | "forbidden" | "network" | "error", message: string, retryable: boolean }}
 */
export function errorState(error) {
  const status = error?.status;
  if (status === 404) return { kind: "unavailable", message: MEMORIES_UNAVAILABLE, retryable: false };
  if (status === 401) return { kind: "auth", message: MEMORIES_AUTH_EXPIRED, retryable: false };
  if (status === 403) return { kind: "forbidden", message: MEMORIES_FORBIDDEN, retryable: false };
  if (status === 0) return { kind: "network", message: MEMORIES_NETWORK, retryable: true };
  return { kind: "error", message: MEMORIES_ERROR, retryable: true };
}

/** 사용자·가족이 바뀌면 달라지는 범위 키. 없으면(로그아웃) null. */
export const scopeKey = (user) => (user?.id ? `${user.id}:${user.active_group_id ?? ""}` : null);

/** 로그아웃(anonymous) 상태로 추억 화면에 직접 들어오면 로그인으로 보낸다. 세션 확인 중(loading)·서버 연결 불가(unreachable)에는 기다린다. */
export const needsLogin = (status) => status === "anonymous";

export const initialMemoriesState = () => ({ scope: null, seq: 0, status: "idle", items: [], error: null });

/**
 * 후보 목록 상태 전이. 범위(사용자·가족)가 바뀌거나 로그아웃하면 후보를 **즉시 비운다**(다른 가족의 후보가 남지 않는다). 늦게 온 응답(seq 불일치)은 버린다.
 * action: { type: "scope", scope, seq? } | { type: "start", seq } | { type: "ok", seq, items } | { type: "fail", seq, error } | { type: "photoGone", candidateId, attachmentId }
 */
export function memoriesReducer(state, action) {
  switch (action.type) {
    case "scope":
      return action.scope === state.scope ? state : { ...initialMemoriesState(), scope: action.scope, seq: action.seq ?? state.seq + 1 };
    case "start":
      return { ...state, seq: action.seq, status: "loading", error: null }; // 이전 목록은 새로 고치는 동안 그대로 둔다(같은 범위일 때만 남아 있다)
    case "ok":
      return action.seq === state.seq ? { ...state, status: "ready", items: action.items, error: null } : state; // 응답이 목록을 통째로 바꾼다: 서버가 뺀 사진은 바로 사라진다
    case "fail": {
      if (action.seq !== state.seq) return state;
      const error = errorState(action.error);
      // 미출시·로그인 만료·권한 없음이면 받아 둔 사진도 화면에 남기지 않는다(권한이 사라진 사진이 보이면 안 된다). 네트워크·일시 오류는 같은 범위의 목록을 지우지 않는다.
      const keep = !["unavailable", "auth", "forbidden"].includes(error.kind);
      return { ...state, status: "error", error, items: keep ? state.items : [] };
    }
    case "photoGone": {
      // 사진이 더는 열리지 않는다(지움·권한 없음): 그 사진을 화면에서 빼고, 3장 미만이 되면 후보도 숨긴다. 다음 새로 고침이 서버 기준으로 다시 맞춘다.
      const items = state.items
        .map((c) => (c.id === action.candidateId ? dropPhoto(c, action.attachmentId) : c))
        .filter((c) => c.photo_count >= MIN_PHOTOS);
      return { ...state, items };
    }
    default:
      return state;
  }
}

/**
 * 사진 로딩 실패를 "사라진 사진" 액션으로 바꾼다. mock 모드의 합성 사진은 서버에 없는 가짜 id 라 늘 404 인데, 그걸 사라진 사진으로 처리하면 후보가 몇 초 만에 모두 사라진다.
 * @param {"off" | "on" | "mock"} mode
 * @param {string} candidateId
 * @param {string} attachmentId
 * @returns {{ type: "photoGone", candidateId: string, attachmentId: string } | null} mock 이면 null(아무것도 하지 않는다)
 */
export function photoGoneAction(mode, candidateId, attachmentId) {
  if (mode === "mock") return null;
  return { type: "photoGone", candidateId, attachmentId };
}

/** 후보에서 사진 한 장을 뺀 새 후보(대표가 빠지면 남은 첫 사진이 대표, 개수·날짜를 다시 센다). */
export function dropPhoto(candidate, attachmentId) {
  const photos = candidate.photos.filter((p) => p.attachment_id !== attachmentId);
  if (photos.length === candidate.photos.length) return candidate;
  const repId = photos.some((p) => p.attachment_id === candidate.representative.attachment_id) ? candidate.representative.attachment_id : photos[0]?.attachment_id;
  const next = photos.map((p) => ({ ...p, is_representative: p.attachment_id === repId }));
  const dated = next.filter((p) => p.taken_at != null).map((p) => p.taken_at).sort();
  return {
    ...candidate,
    photos: next,
    representative: next.find((p) => p.is_representative) ?? candidate.representative,
    photo_count: next.length,
    dated_count: dated.length,
    undated_count: next.length - dated.length,
    starts_at: dated[0] ?? null, // 뺀 사진의 날짜가 범위에 남지 않게 남은 사진으로 다시 계산한다
    ends_at: dated[dated.length - 1] ?? null,
  };
}

/**
 * 화면 본문 종류. 200 + items=[] 만 정상 빈 상태이고, 미출시(404)·오류는 빈 상태로 보이지 않는다.
 * @param {{ status: string, items: object[], error: { kind: string } | null }} state
 * @returns {"loading" | "unavailable" | "error" | "empty" | "list"}
 */
export function bodyKind(state) {
  if (state.status === "error") {
    if (state.error?.kind === "unavailable") return "unavailable";
    return state.items.length > 0 ? "list" : "error"; // 새로 고침이 실패해도 이미 받은 같은 범위의 목록은 지우지 않는다
  }
  if (state.status === "idle" || (state.status === "loading" && state.items.length === 0)) return "loading";
  return state.items.length === 0 ? "empty" : "list";
}

/** 선택한 후보가 새로 고침으로 사라졌으면 null(상세 화면이 닫힌다). */
export const selectedCandidate = (items, id) => (id == null ? null : items.find((c) => c.id === id) ?? null);

/** 사진 뷰어용 목록(`AlbumViewer` 의 { id, url, item } 모양). 원본 주소는 서버가 준 허용된 채팅 사진 주소다. */
export const viewerPhotos = (candidate) => candidate.photos.map((p) => ({ id: p.attachment_id, url: p.photo_url, item: p }));

/** 사진 뷰어 밑 줄: 촬영 날짜(없으면 날짜를 지어내지 않고 안내만). */
export function photoCaption(photo) {
  const d = kstDate(photo?.taken_at);
  return d ? full(d) : UNKNOWN_DATE;
}

/**
 * 이전 목록에는 있었지만 새 목록에는 없는 사진의 주소(작은 사진·원본). 서버가 후보에서 뺐거나(철회·제외·삭제) 가족·로그인이 바뀌어 목록이 비워졌을 때, 이 사진들의
 * 기기 캐시 사본을 지우는 데 쓴다. 같은 사진이 다른 후보에 남아 있으면 지우지 않는다.
 * @param {{ photos: { attachment_id: string, thumb_url: string, photo_url: string }[] }[]} prevItems
 * @param {{ photos: { attachment_id: string }[] }[]} nextItems
 * @returns {string[]}
 */
export function removedPhotoPaths(prevItems, nextItems) {
  const keep = new Set(nextItems.flatMap((c) => c.photos.map((p) => p.attachment_id)));
  const out = new Set();
  for (const c of prevItems) {
    for (const p of c.photos) {
      if (!keep.has(p.attachment_id)) {
        out.add(p.thumb_url);
        out.add(p.photo_url);
      }
    }
  }
  return [...out];
}
