/**
 * 가족 AI 동의 안내 문구와 켜기 확인 흐름의 순수 함수.
 * 문구는 서버 동작의 사실에 맞춰야 한다. 서버가 가명화(개인정보 가리기)를 다른 AI 기능으로 넓히면 이 파일의 상수만 고친다.
 * 근거(서버): 가족 AI 동의 `ai_guard.is_enabled` 하나가 가족 채팅 AI(대화 분석 analysis, 답장·주제 포함), AI 비서(assistant_chat),
 * 문서 질문(doc_summary·doc_answer), 일정·가계·돌봄 도우미(schedule·billing_agent·care_agent)의 관문이다.
 * 가려서 보내는 것은 가족 채팅 AI 의 대화뿐이고 나머지는 질문 글만 규칙으로 일부 가리거나(일정·가계·돌봄) 전혀 가리지 않는다.
 */

export const CONSENT_TITLE = "AI 기능 켜기 전에 확인해 주세요";

/** 카드에 항상 보이는 요약(2~4줄). */
export const CONSENT_SUMMARY = [
  "대화 분석(요약·일정·할 일 후보·답장 추천·대화 주제 추천)은 개인정보를 가려서 외부 AI(Claude)로 보내요.",
  "AI 비서·문서 질문·일정·가계·돌봄 도우미도 함께 쓸 수 있게 돼요. 이 기능들은 질문과 기록이 가려지지 않거나 일부만 가려진 채 전달될 수 있어요.",
  "종단간 암호화가 아니라 서버가 내용을 읽어 처리해요. 소유자·관리자는 언제든 끌 수 있어요.",
];

/** "자세히 보기"를 펼치면 보이는 상세. 기능별로 서버 동작 그대로 쓴다. */
export const CONSENT_DETAILS = [
  "켜면 우리 가족 모두의 AI 기능을 쓸 수 있게 돼요. 가족 소유자·관리자만 켜고 끌 수 있고, 구성원 개인이 다른 사람 대신 동의하는 것이 아니에요.",
  "대화 분석(요약·일정·할 일 후보·답장 추천·대화 주제 추천): 전화번호·이메일·주소·이름 등을 가린 뒤 Claude 로 한 번에 보내요. 주민번호·카드·계좌·비밀번호가 든 메시지는 보내지 않아요. 규칙으로 찾기 때문에 놓칠 수 있어요. 1:1 대화는 보내지 않아요. 보내기 전에 매번 확인 카드에서 가려지는 내용을 보여 드리고, 'AI에 보내기'를 눌러야만 전송돼요.",
  "AI 비서: 질문과 앞 대화(최근 10개)를 가리지 않고 보내요. 다만 주민번호·카드·계좌·비밀번호가 든 입력은 서버가 막아요. 질문에 따라 가계·돌봄 도우미를 불러 지출·위치 결과가 나갈 수도 있어요.",
  "일정·가계·돌봄 도우미: 질문은 규칙으로 일부만 가려요. 조회 결과(이름·금액·동의한 구성원의 위치)는 가리지 않고 보내요.",
  "문서 질문: 문서를 저장할 때 규칙으로 가린 글자를 써요. 완전하지 않아서 문서·질문은 대화 분석보다 약하게 가려져요.",
  "모든 AI 기능은 종단간 암호화(E2EE)가 아니에요. 서버가 내용을 평문으로 처리하고 Claude 로 나가요.",
  "끄면 위 AI 기능이 모두 멈추고 저장된 분석 결과도 지워져요. 다시 켜기 전까지 Claude 로는 나가지 않아요. (파일 자동 분류가 별도 외부 분류 서비스를 쓰도록 설정된 서버에서는 이 동의와 무관하게 문서 글자가 그 서비스로 갈 수 있어요.)",
];

export const CONSENT_DISABLE_LABEL = "AI 끄기";
export const CONSENT_DISABLE_CONFIRM_LABEL = "끄기";
export const CONSENT_DISABLE_TITLE = "AI 기능을 끌까요?";
export const CONSENT_DISABLE_BODY = "끄면 AI 비서·문서 질문·일정·가계·돌봄 도우미까지 모두 멈추고 저장된 분석 결과가 지워져요";
/** 켜진 상태에서 구성원(비관리자)에게 보이는 안내. */
export const CONSENT_ON_MEMBER_NOTE = "가족 소유자나 관리자만 AI 기능을 끌 수 있어요";
export const CONSENT_ENABLE_LABEL = "AI 기능 켜기";
export const CONSENT_CONFIRM_LABEL = "확인하고 켜기";
export const CONSENT_CANCEL_LABEL = "취소";
export const CONSENT_DETAILS_OPEN_LABEL = "자세히 보기";
export const CONSENT_DETAILS_CLOSE_LABEL = "자세히 접기";

/** 소유자·관리자가 아닌 구성원에게 보이는 안내(서버도 403 not_manager 로 막는다). */
export const CONSENT_NEED_MANAGER = "가족 소유자나 관리자만 켜고 끌 수 있어요. 구성원 개인이 다른 사람 대신 동의할 수 없어요";

/**
 * 동의를 바꾸기 전에 안내 확인이 필요한가. 꺼진 상태에서 켤 때만 true(이미 켜짐·끄기는 확인 없음).
 * @param {boolean} currentEnabled 지금 서버에 저장된 동의
 * @param {boolean} nextEnabled 바꾸려는 값
 * @returns {boolean}
 */
export function needsEnableConfirm(currentEnabled, nextEnabled) {
  return currentEnabled !== true && nextEnabled === true;
}

/**
 * 자세히 보기 토글 라벨(접근성 라벨과 버튼 글자가 같다).
 * @param {boolean} open
 * @returns {string}
 */
export function detailsToggleLabel(open) {
  return open ? CONSENT_DETAILS_CLOSE_LABEL : CONSENT_DETAILS_OPEN_LABEL;
}

/**
 * 카드 전체를 한 번에 읽어 주는 접근성 문장(제목 + 요약).
 * @returns {string}
 */
export function consentA11ySummary() {
  return [CONSENT_TITLE, ...CONSENT_SUMMARY].join(" ");
}
