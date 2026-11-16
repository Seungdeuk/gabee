/**
 * 카카오톡 앱으로 로그인하고 돌아온 주소(gabee://kakao?code=…&state=…)를 받는 라우트(`app/kakao.js`)와
 * 진행 중인 로그인 버튼(`SocialButtons`)을 이어 주는 작은 알림 통.
 * 카카오톡 앱이 인증을 처리하면 인증 창(Custom Tab) 쪽 결과가 "닫힘"으로 끝나고 코드는 이 주소로만 들어오기 때문에,
 * 라우트가 코드를 버리지 않고 여기로 알린다. React·RN 에 기대지 않아 단위 시험이 된다.
 */

/**
 * 알림 통을 만든다(앱에서는 아래 `kakaoReturnBus` 하나만 쓰고, 시험은 따로 만들어 쓴다).
 * @returns {{ subscribe: (listener: (params: Record<string, unknown>) => void) => () => void, publish: (params: Record<string, unknown>) => void }}
 */
export function createKakaoReturnBus() {
  const listeners = new Set();
  return {
    /**
     * 구독한다. 돌려주는 함수를 부르면 해제된다.
     * @param {(params: Record<string, unknown>) => void} listener
     * @returns {() => void} 구독 해제 함수
     */
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    /**
     * 구독자 모두에게 알린다. 한 구독자가 오류를 내도 나머지는 받는다.
     * @param {Record<string, unknown>} params 복귀 주소의 검색 값(code, state, error 등)
     * @returns {void}
     */
    publish(params) {
      for (const listener of [...listeners]) {
        try {
          listener(params);
        } catch {
          // 한 쪽의 오류가 다른 구독자나 라우트 이동을 막지 않게 삼킨다
        }
      }
    },
  };
}

/** 앱 전체에서 쓰는 카카오 복귀 알림 통. */
export const kakaoReturnBus = createKakaoReturnBus();
