/**
 * Refresh Token 보관소. 실제 저장소(expo-secure-store)는 밖에서 넣어 준다 — 그래서 이 파일은 앱 없이도 시험할 수 있다.
 * Access Token 은 짧게 쓰고 메모리에만 두며, 저장하는 것은 Refresh Token 하나뿐이다.
 * 저장소를 쓸 수 없는 환경(웹 등)에서는 이번 실행 동안만 메모리에 둔다(앱을 다시 켜면 로그인이 풀린다).
 */
const KEY = "gabee.refresh_token";

/**
 * @param {{ getItemAsync: (k: string) => Promise<string | null>, setItemAsync: (k: string, v: string) => Promise<void>, deleteItemAsync: (k: string) => Promise<void> } | null} backend
 */
export function createTokenStore(backend) {
  let memory = "";
  return {
    /** @returns {Promise<string>} 저장된 Refresh Token, 없으면 "" */
    async load() {
      if (!backend) return memory;
      try {
        return (await backend.getItemAsync(KEY)) ?? "";
      } catch {
        return memory;
      }
    },
    /** @param {string} token */
    async save(token) {
      memory = token;
      if (!backend) return;
      try {
        await backend.setItemAsync(KEY, token);
      } catch {
        // 저장에 실패해도 이번 실행에서는 메모리 세션으로 계속 쓴다
      }
    },
    async clear() {
      memory = "";
      if (!backend) return;
      try {
        await backend.deleteItemAsync(KEY);
      } catch {
        // 이미 없거나 지울 수 없는 경우: 다음 복원에서 서버가 거부한다
      }
    },
  };
}
