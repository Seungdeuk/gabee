import { apiFetch, isApiConfigured } from "@/shared/api/client";

/**
 * 가비의 답변 한 건.
 * @typedef {object} AssistantReply
 * @property {string} reply 답변 본문(간단한 마크다운: `## 제목`, `- 목록`, `**굵게**`, `[1]` 출처 번호)
 * @property {{ n: number, title: string }[]} [sources] 답변이 근거로 쓴 기록
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
  const sources = (res.sources ?? []).map(({ n, title }) => ({ n, title }));
  return { reply: res.reply, sources, draft: null };
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
  form.append("file", { uri: file.uri, name: filename, type: file.type ?? "image/jpeg" });
  return apiFetch("/ai-assistant/files", { method: "POST", body: form });
}

/**
 * 올린 파일의 분석 상태.
 * status: received | analyzed(저장 완료) | needs_review(저장했지만 확인 필요) | failed(읽지 못함, message 에 이유)
 * @param {string} id
 * @returns {Promise<{ id: string, status: string, title?: string, kind_label?: string, description?: string, message?: string }>}
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

/** 예전 이름. uploadFile 과 같다. */
export const uploadPhoto = uploadFile;
