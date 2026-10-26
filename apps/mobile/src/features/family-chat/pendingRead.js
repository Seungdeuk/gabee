// 진행 중인 읽음 올리기(markRead) 호출을 모듈 수준에서 추적한다. 소통 탭이 배지를 부르기 전에 끝나기를 기다리는 데 쓴다(대화 글자 없음).

const inflight = new Set();

/**
 * 진행 중인 읽음 호출로 등록한다. 끝나면(성공·실패 모두) 자동으로 빠진다.
 * @param {Promise<unknown>} promise
 * @returns {Promise<unknown>} 받은 promise 그대로
 */
export function trackMarkRead(promise) {
  const done = promise.then(
    () => undefined,
    () => undefined,
  );
  inflight.add(done);
  done.then(() => inflight.delete(done));
  return promise;
}

/**
 * 진행 중인 읽음 호출이 있으면 끝나기를 기다린다(실패해도 던지지 않는다). 오래 걸려도 timeoutMs 뒤에는 넘어간다.
 * @param {number} [timeoutMs] 최대 대기(기본 3000)
 * @returns {Promise<void>}
 */
export async function waitForPendingMarkRead(timeoutMs = 3000) {
  if (inflight.size === 0) return;
  let timer;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(resolve, timeoutMs);
  });
  await Promise.race([Promise.all([...inflight]), timeout]);
  clearTimeout(timer);
}

/**
 * 진행 중인 읽음 호출이 있는지.
 * @returns {boolean}
 */
export const hasPendingMarkRead = () => inflight.size > 0;
