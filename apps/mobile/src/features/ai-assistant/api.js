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
 * TODO: 서버가 출처와 메시지 초안을 함께 돌려주면 여기서 AssistantReply 모양으로 맞춘다.
 *
 * @param {string} text 사용자가 입력한 메시지
 * @returns {Promise<AssistantReply>}
 */
export async function sendMessage(text) {
  if (!isApiConfigured()) {
    await new Promise((resolve) => setTimeout(resolve, 2400));
    return mockReply(text);
  }
  const res = await apiFetch("/ai-assistant/chat", { method: "POST", body: { message: text } });
  return { reply: res.reply, sources: [], draft: null };
}

/**
 * 사진 한 장을 가족 기록으로 올린다. TODO: 자동 전송 동의 확인, 분류 결과 표시.
 * @param {{ uri: string, name?: string, type?: string }} file expo-image-picker 등에서 받은 파일
 */
export function uploadPhoto(file) {
  const form = new FormData();
  form.append("file", { uri: file.uri, name: file.name ?? "photo.jpg", type: file.type ?? "image/jpeg" });
  return apiFetch("/ai-assistant/photos", { method: "POST", body: form });
}
