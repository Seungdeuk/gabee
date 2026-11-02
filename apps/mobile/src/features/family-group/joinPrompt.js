/**
 * 홈(AI 채팅) 인사말 아래 "가족 만들기"·"가족 코드로 참여" 버튼을 보일지. 가족 그룹도 대기 중인 참여 요청도 없을 때만 보인다
 * (불러오는 중·오류일 때는 깜빡이지 않게 숨기고, 승인 대기 중이면 이미 신청한 것이라 숨긴다).
 * @param {"loading" | "none" | "pending" | "member" | "error" | string} status useFamilyState 의 status
 * @returns {boolean}
 */
export const joinPromptVisible = (status) => status === "none";
