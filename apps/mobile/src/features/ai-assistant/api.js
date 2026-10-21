import { apiFetch, isApiConfigured } from "@/shared/api/client";

/**
 * AI 비서에게 메시지를 보내고 답변을 받는다.
 * 서버 주소(EXPO_PUBLIC_API_URL)가 없으면 화면 확인용 임시(mock) 답변을 돌려준다.
 *
 * @param {string} text 사용자가 입력한 메시지
 * @returns {Promise<string>} 비서의 답변
 */
export async function sendMessage(text) {
  if (!isApiConfigured()) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    return `"${text}"에 대한 답변이에요. 아직 서버와 연결되지 않은 임시 응답입니다.`;
  }
  const res = await apiFetch("/ai-assistant/chat", { method: "POST", body: { message: text } });
  return res.reply;
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
