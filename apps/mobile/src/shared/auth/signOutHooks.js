// 로그아웃하기 직전(세션이 아직 살아 있을 때)에 해야 하는 일을 기능이 등록해 둔다. 예: 푸시 토큰 해제.
// 공통(shared)이 기능(features)을 불러오지 않도록, 기능이 여기에 등록하는 방향으로 둔다.

const hooks = new Set();

/**
 * 로그아웃 직전에 실행할 함수를 등록한다.
 * @param {() => void | Promise<void>} fn
 * @returns {() => void} 등록을 지우는 함수
 */
export function onBeforeSignOut(fn) {
  hooks.add(fn);
  return () => hooks.delete(fn);
}

/**
 * 등록된 함수를 순서대로 실행한다. 하나가 실패하거나 오래 걸려도 로그아웃을 막지 않는다.
 * @param {number} [timeoutMs] 함수 하나를 기다리는 최대 시간(기본 3초)
 * @returns {Promise<void>}
 */
export async function runBeforeSignOut(timeoutMs = 3000) {
  for (const fn of [...hooks]) {
    let timer;
    try {
      const timeout = new Promise((resolve) => {
        timer = setTimeout(resolve, timeoutMs);
      });
      await Promise.race([Promise.resolve().then(fn), timeout]);
    } catch {
      // 한 기능의 정리 실패가 로그아웃을 막지 않는다
    } finally {
      clearTimeout(timer);
    }
  }
}
