/**
 * AI 비서에게 메시지를 보내고 답변을 받는다.
 *
 * TODO: 서버(FastAPI)의 채팅 API가 생기면 shared/api 래퍼로 교체한다.
 * 지금은 화면 확인용 임시(mock) 응답이다.
 *
 * @param {string} text 사용자가 입력한 메시지
 * @returns {Promise<string>} 비서의 답변
 */
export async function sendMessage(text) {
  await new Promise((resolve) => setTimeout(resolve, 800));
  return `"${text}"에 대한 답변이에요. 아직 서버와 연결되지 않은 임시 응답입니다.`;
}
