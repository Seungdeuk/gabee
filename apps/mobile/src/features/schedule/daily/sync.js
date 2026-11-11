// 데일리 체크 저장 보조(순수 도구). 타이머와 줄 세우기를 따로 둬서 시험에서 가짜 시계로 돌려 본다.
// 화면은 entrySync.js 를 통해 쓰고, 이 파일을 직접 부르는 곳은 entrySync.js 뿐이다.

/**
 * 디바운스 저장기. 같은 key 에 여러 번 set 하면 마지막 value 만 delay ms 뒤에 save(key, value) 한다.
 * flush(key) 는 기다리지 않고 바로 보낸다(화면을 떠나거나 앱이 백그라운드로 갈 때 남은 값을 보낸다).
 */
export function createDebouncedSaver({ delay = 400, save, setTimer = setTimeout, clearTimer = clearTimeout }) {
  const pending = new Map(); // key → { value, timer }

  function flush(key) {
    const entry = pending.get(key);
    if (!entry) return Promise.resolve();
    clearTimer(entry.timer);
    pending.delete(key);
    return Promise.resolve(save(key, entry.value));
  }

  return {
    set(key, value) {
      const prev = pending.get(key);
      if (prev) clearTimer(prev.timer);
      const timer = setTimer(() => flush(key), delay);
      pending.set(key, { value, timer });
    },
    has: (key) => pending.has(key),
    get: (key) => pending.get(key)?.value,
    flush,
    flushAll: () => Promise.all([...pending.keys()].map((key) => flush(key))),
  };
}

/**
 * 키별 줄 세우기. 같은 key 의 작업은 앞의 것이 끝난 뒤에 하나씩 실행한다(서버에 같은 항목을 순서대로 보낸다).
 * 다른 key 끼리는 동시에 간다. 앞 작업이 실패해도 뒤 작업은 계속 간다.
 */
export function createKeyedQueue() {
  const tails = new Map();
  return function enqueue(key, task) {
    const prev = tails.get(key) ?? Promise.resolve();
    const run = prev.then(() => task());
    const tail = run.then(
      () => undefined,
      () => undefined,
    );
    tails.set(key, tail);
    tail.then(() => {
      if (tails.get(key) === tail) tails.delete(key);
    });
    return run;
  };
}

/**
 * 낙관적 갱신의 롤백 판정. 요청을 보낼 때의 변경 번호(requestSeq)가 지금의 최근 번호(latestSeq)와 같을 때만
 * 응답(성공·실패)을 화면에 반영한다. 그 뒤에 더 새 변경이 있으면 그 변경이 화면을 정하므로 옛 응답은 무시한다.
 */
export function isLatestChange(requestSeq, latestSeq) {
  return requestSeq === latestSeq;
}
