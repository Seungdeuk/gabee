import { apiFetch, apiUrl, authHeaders, ensureFreshAccess, isApiConfigured } from "@/shared/api/client";

import { confirmResultText, mapChatCards } from "./scheduleCard";

/**
 * 가비의 답변 한 건.
 * @typedef {object} AssistantReply
 * @property {string} reply 답변 본문(간단한 마크다운: `## 제목`, `- 목록`, `**굵게**`, `[1]` 출처 번호)
 * @property {{ n: number, title: string, itemId?: string, sourcePath?: string | null }[]} [sources] 답변이 근거로 쓴 기록(itemId 가 있으면 원본을 열 수 있다)
 * @property {{ to: string, text: string } | null} [draft] 가족에게 보낼 메시지 초안(승인 전)
 */

const MOCK_REPORT = `저장된 영수증 4건을 모아 지출 보고서를 만들었어요. 가게별 금액과 합계를 정리해 드릴게요.

## 영수증 4건
- **가게 이름 미확인**: 2025-09-21 · 143,273원 [1]
- **스타필드 코엑스몰점**: 2025-10-03 · 60,000원 [2]
- **공차 선릉중앙점**: 2025-10-01 · 10,800원 [3]
- **동대문마트**: 2026-10-15 · 2,950원 [4]

## 합계
- **영수증 4건**: 모두 더하면 **217,023원**이에요.`;

/** 서버가 없을 때 화면을 확인하려고 쓰는 임시 답변. 질문에 들어 있는 낱말로 고른다. */
function mockReply(text) {
  if (/영수증|지출|보고서/.test(text)) {
    return {
      reply: MOCK_REPORT,
      sources: [1, 2, 3, 4].map((n) => ({ n, title: `영수증 ${n}` })),
      draft: null,
    };
  }
  if (/전기|요금|고지서|공과금|엄마/.test(text)) {
    return {
      reply: "10월 전기요금 고지서가 있어요. 금액은 **48,200원**이고 납기일은 **10월 25일**이에요. [1] 엄마께 보낼 메시지 초안을 만들었어요.",
      sources: [{ n: 1, title: "10월 전기요금 고지서" }],
      draft: { to: "엄마", text: "10월 전기요금 48,200원, 25일까지예요. 누가 낼까요?" },
    };
  }
  return {
    reply: `"${text}"에 대한 답변이에요. 아직 서버와 연결되지 않은 임시 응답입니다.`,
    sources: [],
    draft: null,
  };
}

/**
 * AI 비서에게 메시지를 보내고 답변을 받는다.
 * 서버 주소(EXPO_PUBLIC_API_URL)가 없으면 화면 확인용 임시(mock) 답변을 돌려준다.
 * 서버는 답과 출처(sources)를 돌려준다. 메시지 초안(draft)은 아직 서버가 만들지 않는다.
 *
 * @param {string} text 사용자가 입력한 메시지
 * @param {{ role: "user" | "assistant", text: string }[]} [history] 앞 대화(오래된 것부터, 서버는 최근 10개만 받는다)
 * @returns {Promise<AssistantReply>}
 */
export async function sendMessage(text, history = []) {
  if (!isApiConfigured()) {
    await new Promise((resolve) => setTimeout(resolve, 2400));
    return mockReply(text);
  }
  const res = await apiFetch("/ai-assistant/chat", { method: "POST", body: { message: text, history: history.slice(-10) } });
  const sources = (res.sources ?? []).map(({ n, title, item_id: itemId, source_path: sourcePath }) => ({ n, title, itemId, sourcePath }));
  return { reply: res.reply, sources, draft: null, confirmCards: mapChatCards(res) };
}

/**
 * 채팅의 일정 확인 카드(가족 공유 등록·수정·삭제)의 버튼을 눌렀을 때. AI 를 부르지 않고, 서버는 돌려받은 내용을 처음부터 다시 검증한다.
 * @param {{ pendingAction: object }} card mapConfirmCards 가 만든 카드
 * @param {boolean} share 등록일 때 true 면 공유 대상에게도 등록, false 면 내 일정만
 * @param {boolean} [postToRoom] 가족 채팅방 @가비 의 카드면 true: 공유 등록을 마치면 서버가 결과를 가비 이름으로 방에 알린다(문장은 서버가 만든다)
 * @returns {Promise<{ text: string }>} 사용자에게 보여 줄 결과 한 줄
 */
export async function confirmScheduleAction(card, share, postToRoom = false) {
  if (!isApiConfigured()) return { text: "(임시) 반영했어요." };
  const res = await apiFetch("/schedule/agent/confirm", { method: "POST", body: { action: card.pendingAction, share: Boolean(share), post_to_room: Boolean(postToRoom) } });
  return { text: confirmResultText(res) };
}

/**
 * 확인 카드의 버튼을 눌렀을 때 종류에 맞게 실행한다: 일정 카드는 일정 확인, 정산·돌봄 제안은 그 탭의 확인(token).
 * 제안 토큰은 10분 안에 한 번만 쓸 수 있고, 서버가 사용자·가족·탭을 다시 확인한다.
 * @param {{ kind: string, tab?: string, token?: string, pendingAction?: object }} card
 * @param {boolean} share 일정 등록일 때만 쓰는 값
 * @param {boolean} [postToRoom] 가족 채팅방 @가비 의 일정 카드면 true(정산·돌봄 제안은 쓰지 않는다)
 * @returns {Promise<{ text: string }>}
 */
export async function confirmCardAction(card, share, postToRoom = false) {
  if (card.kind !== "proposal") return confirmScheduleAction(card, share, postToRoom);
  if (!isApiConfigured()) return { text: "(임시) 반영했어요." };
  const res = await apiFetch(`/${card.tab}/agent/confirm`, { method: "POST", body: { token: card.token } });
  return { text: res?.summary ? `반영했어요 · ${res.summary}` : "반영했어요." };
}

/**
 * 우리 가족의 AI 사용 설정(켜져 있는지, 내가 켤 수 있는지). 가족 채팅 AI 설정과 같은 서버 API 를 계약대로 부른다.
 * @returns {Promise<{ enabled: boolean, canManage: boolean }>}
 */
export async function getAiSettings() {
  if (!isApiConfigured()) return { enabled: true, canManage: true };
  const res = await apiFetch("/family-chat/ai/settings");
  return { enabled: res?.enabled === true, canManage: res?.can_manage === true };
}

/**
 * 우리 가족의 AI 사용을 켠다(소유자·관리자만, 아니면 서버가 403). 사용자가 버튼을 눌렀을 때만 부른다.
 * @returns {Promise<void>}
 */
export async function enableAi() {
  if (!isApiConfigured()) return;
  await apiFetch("/family-chat/ai/settings", { method: "PUT", body: { enabled: true } });
}

const MOCK_ANALYZE_MS = 2500;
const mockUploads = new Map(); // 서버가 없을 때 id → 올린 시각

/**
 * 파일 한 개(사진·문서 등)를 가족 기록으로 올린다. 서버는 바로 받았다고 답하고 뒤에서 분석한다.
 * 분석 결과는 getFileStatus 로 확인한다. 용량·네트워크 오류는 ApiError 메시지를 그대로 쓴다.
 * @param {{ uri: string, name?: string, type?: string }} file expo-image-picker 등에서 받은 파일
 * @returns {Promise<{ id: string, filename: string, size?: number, status: string }>}
 */
export async function uploadFile(file) {
  const filename = file.name ?? "photo.jpg";
  if (!isApiConfigured()) {
    await new Promise((resolve) => setTimeout(resolve, 600));
    const id = `mock-${Date.now()}`;
    mockUploads.set(id, Date.now());
    return { id, filename, status: "received" };
  }
  const form = new FormData();
  form.append("file", { uri: file.uri, name: filename, type: file.type ?? "application/octet-stream" });
  return apiFetch("/ai-assistant/files", { method: "POST", body: form });
}

/**
 * 올린 파일의 분석 상태.
 * status: received | analyzed(저장 완료) | needs_review(저장했지만 확인 필요) | failed(읽지 못함, message 에 이유)
 * @param {string} id
 * @returns {Promise<{ id: string, status: string, title?: string, kind_label?: string, description?: string, message?: string, needs_description?: boolean, doubts?: string[] }>}
 * needs_description: 분석이 끝난 글자 없는 사진이라 사용자가 한 줄 설명을 달아야 하면 true(값이 없으면 false 로 본다)
 */
export async function getFileStatus(id) {
  if (!isApiConfigured()) {
    const startedAt = mockUploads.get(id) ?? 0;
    if (Date.now() - startedAt < MOCK_ANALYZE_MS) return { id, status: "received" };
    return {
      id,
      status: "analyzed",
      kind_label: "영수증",
      title: "동대문마트 영수증",
      description: "2026-10-15 · 2,950원",
    };
  }
  return apiFetch(`/ai-assistant/files/${encodeURIComponent(id)}`);
}

/**
 * 글자 없는 사진에 사용자가 한 줄 설명을 단다. 저장하면 그 설명으로 검색된다.
 * 서버는 공백을 뺀 1~200자만 받는다. 실패하면 ApiError 메시지를 그대로 쓴다.
 * @param {string} id 파일(기록) id
 * @param {string} text 사용자가 적은 설명
 * @returns {Promise<{ id: string, status: string, needs_description: boolean }>}
 */
export async function submitDescription(id, text) {
  if (!isApiConfigured()) return { id, status: "analyzed", needs_description: false };
  return apiFetch(`/ai-assistant/files/${encodeURIComponent(id)}/description`, { method: "POST", body: { text } });
}

/**
 * 올린 원본 파일을 화면에 띄울 이미지 소스. 서버가 가족 확인을 하므로 로그인 헤더를 같이 보낸다.
 * 서버가 없으면(mock) null.
 * @param {string} id
 * @returns {{ uri: string, headers: Record<string, string> } | null}
 */
export function originalImageSource(id) {
  if (!isApiConfigured()) return null;
  return { uri: apiUrl(`/ai-assistant/files/${encodeURIComponent(id)}/original`), headers: authHeaders() };
}

const IMAGE_EXT = /\.(jpe?g|png|webp|gif|bmp|heic|heif)$/i;

/**
 * 원본을 앱 안에서 볼 수 있게 이미지 소스 목록으로 바꾼다. 사진은 한 장, PDF 는 서버가 쪽별로 그린 그림 여러 장이다.
 * 그 밖의 형식(워드·엑셀·PPT 등)은 앱에서 열 수 없어 sources 가 비고 안내 문구만 돌려준다.
 * @param {string} id 기록(파일) id
 * @param {string | null | undefined} sourcePath 서버가 알려 준 원본 경로(확장자로 종류를 안다)
 * @returns {Promise<{ sources: { uri: string, headers: Record<string, string> }[], message?: string }>}
 */
export async function openOriginal(id, sourcePath) {
  await ensureFreshAccess().catch(() => {}); // 이미지는 apiFetch 를 거치지 않아 토큰을 미리 갱신한다
  const source = originalImageSource(id);
  if (!source) return { sources: [], message: "서버에 연결되지 않아 원본을 볼 수 없어요." };
  if (!sourcePath) return { sources: [], message: "이 기록에는 원본 파일이 없어요." };
  if (IMAGE_EXT.test(sourcePath)) return { sources: [source] };
  if (/\.pdf$/i.test(sourcePath)) {
    try {
      const { count } = await apiFetch(`/ai-assistant/files/${encodeURIComponent(id)}/original/pages`);
      const base = `/ai-assistant/files/${encodeURIComponent(id)}/original/pages`;
      return { sources: Array.from({ length: count }, (_, i) => ({ uri: apiUrl(`${base}/${i + 1}`), headers: authHeaders() })) };
    } catch (e) {
      return { sources: [], message: e?.message || "PDF 를 불러오지 못했어요." };
    }
  }
  return { sources: [], message: "이 형식의 파일은 아직 앱에서 열 수 없어요. 읽어 낸 글로 확인해 주세요." };
}

/**
 * 가족이 올린 기록 목록(최근 순). 사이드바의 "기록" 탭에서 쓴다.
 * needs_review: 읽다 만 부분이 있거나 종류가 애매해서 사용자가 확인해야 하는 기록. 확인이 필요한 것이 앞에 온다.
 * @returns {Promise<{ id: string, title: string, kind_label: string, occurred_on: string | null, has_unread_parts: boolean, needs_review: boolean, needs_description: boolean, hasOriginal: boolean }[]>}
 */
export async function listRecords() {
  if (!isApiConfigured()) {
    return [{ id: "mock-1", title: "동대문마트 영수증", kind_label: "영수증", occurred_on: "2026-10-15", has_unread_parts: false, needs_review: true, needs_description: false, hasOriginal: false }];
  }
  const items = await apiFetch("/ai-assistant/knowledge/items?limit=50");
  await ensureFreshAccess().catch(() => {}); // 목록의 작은 사진도 같은 토큰으로 받는다
  const records = items.map((i) => ({ ...i, needs_description: Boolean(i.needs_description), hasOriginal: Boolean(i.source_path) }));
  return records.sort((a, b) => Number(b.needs_review) - Number(a.needs_review)); // 확인 필요한 기록을 맨 위로(나머지는 서버 순서 유지)
}

/**
 * 기록을 확인하며 고친다. 보낸 칸만 바뀌고, 빈 객체를 보내면 "고칠 것 없이 확인했어요"가 된다.
 * 저장하면 확인 필요 표시가 사라지고 검색에도 고친 내용이 반영된다.
 * @param {string} id
 * @param {{ title?: string, kind_label?: string, occurred_on?: string | null, body_md?: string }} changes
 */
export async function updateRecord(id, changes = {}) {
  if (!isApiConfigured()) return { id, ...changes, needs_review: false };
  return apiFetch(`/ai-assistant/knowledge/items/${encodeURIComponent(id)}`, { method: "PATCH", body: changes });
}

/** 기록 한 건의 읽어 낸 글(개인정보는 가려진 상태). */
export async function getRecord(id) {
  if (!isApiConfigured()) return { id, body_md: "# 동대문마트 영수증\n분류: 영수증\n합계 2,950원" };
  return apiFetch(`/ai-assistant/knowledge/items/${encodeURIComponent(id)}`);
}

/**
 * 기록을 지운다. 읽어 낸 글과 검색용 조각, 서버에 둔 원본 파일까지 지워지고 되돌릴 수 없다.
 * @param {string} id
 */
export async function deleteRecord(id) {
  if (!isApiConfigured()) return;
  await apiFetch(`/ai-assistant/knowledge/items/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/** 예전 이름. uploadFile 과 같다. */
export const uploadPhoto = uploadFile;

/**
 * 앱을 열 때 가비가 먼저 할 말(일정으로 잡을까요 / 미리 알림 / 하셨나요)을 받는다. 서버는 한 번 준 말을 다시 주지 않는다.
 * 여러 개는 서버가 한 덩어리로 묶어 주므로 말풍선 하나(`message`)만 쓴다.
 * 먼저 말하기는 부가 기능이라 서버 주소가 없거나 호출이 실패하면 오류를 보이지 않고 빈 목록을 돌려준다.
 * @returns {Promise<string[]>} 채팅에 넣을 말(없으면 빈 배열, 있으면 한 개)
 */
export async function fetchNudges() {
  if (!isApiConfigured()) return [];
  try {
    const res = await apiFetch("/ai-assistant/reminders/nudges", { method: "POST" });
    return res.message ? [res.message] : [];
  } catch {
    return [];
  }
}

/**
 * 먼저 챙겨주기(문서 날짜 알림) 스위치를 읽는다.
 * @returns {Promise<boolean>} 켜져 있으면 true
 */
export async function getReminderSetting() {
  const res = await apiFetch("/ai-assistant/reminders/settings");
  return res.enabled === true;
}

/**
 * 먼저 챙겨주기 스위치를 켜거나 끈다.
 * @param {boolean} enabled
 * @returns {Promise<boolean>} 저장된 값
 */
export async function setReminderSetting(enabled) {
  const res = await apiFetch("/ai-assistant/reminders/settings", { method: "PUT", body: { enabled } });
  return res.enabled === true;
}
