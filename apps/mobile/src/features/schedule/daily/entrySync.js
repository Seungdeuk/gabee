// 오늘 기록 저장 보조. 누르면 화면에 먼저 보이고(낙관적 갱신), 서버 저장은 항목마다 줄을 세워 하나씩 보낸다.
// 횟수 +/− 는 디바운스로 마지막 값만 보낸다. 실패하면 서버가 마지막으로 확인한 값으로 되돌리고 onError 를 부른다.
// send 는 주입받는다(api.js 의 setEntry 가 기본 자리). 그래서 시험에서 가짜 서버로 롤백을 확인할 수 있다.
import { createDebouncedSaver, createKeyedQueue, isLatestChange } from "./sync";

/**
 * @param {object} deps
 * @param {(item: object, entry: object) => Promise<{ entry: object }>} deps.send 서버 저장(항목 모양과 entry 를 받아 서버가 준 항목을 돌려준다)
 * @param {(id: string, entry: object | undefined) => void} deps.show 화면에 보일 값을 바꾼다(낙관·서버 확인·롤백 모두 여기로)
 * @param {(error: unknown) => void} deps.onError 저장 실패를 알린다(화면은 되돌려진 뒤 안내한다)
 * @param {number} [deps.delay=400] 횟수 디바운스 시간(ms)
 */
export function createEntrySync({ send, show, onError, delay = 400, setTimer, clearTimer }) {
  const local = {}; // 화면에 보이는 값(항목 id → entry)
  const committed = {}; // 서버가 확인한 마지막 값(롤백할 값)
  const seq = {}; // 항목별 최근 변경 번호
  const inflight = {}; // 항목별 저장 중인 요청 수
  const enqueue = createKeyedQueue();

  const latest = (id) => seq[id] ?? 0;

  function push(item, entry) {
    const id = item.id;
    const mine = latest(id);
    inflight[id] = (inflight[id] ?? 0) + 1;
    return enqueue(id, () => send(item, entry)).then(
      (saved) => {
        inflight[id] -= 1;
        committed[id] = saved.entry;
        if (isLatestChange(mine, latest(id))) {
          local[id] = saved.entry;
          show(id, saved.entry);
        }
      },
      (error) => {
        inflight[id] -= 1;
        if (!isLatestChange(mine, latest(id))) return; // 그 뒤에 더 새 변경이 있으면 그 변경이 화면을 정한다
        const back = committed[id];
        local[id] = back;
        show(id, back);
        onError(error);
      },
    );
  }

  const saver = createDebouncedSaver({
    delay,
    setTimer,
    clearTimer,
    save: (id, value) => push(value.item, value.entry),
  });

  return {
    /**
     * 서버에서 읽은 기록을 받아 맞춘다. 저장이 남아 있는 항목은 화면 값(local)을 우선하고, 나머지는 서버 값을 쓴다.
     * @param {Record<string, object | undefined>} serverEntries 항목 id → 서버 entry
     * @returns {Record<string, object | undefined>} 화면에 넣을 기록 전체
     */
    seed(serverEntries) {
      const merged = {};
      for (const [id, entry] of Object.entries(serverEntries)) {
        committed[id] = entry;
        const busy = saver.has(id) || (inflight[id] ?? 0) > 0;
        if (!busy) local[id] = entry;
        merged[id] = busy && id in local ? local[id] : entry;
      }
      return merged;
    },
    /** 화면에 지금 보이는 값(연타 중에도 최신). */
    valueOf: (id) => local[id],
    /**
     * 기록을 바꾼다. debounced 가 true 면 마지막 값만 잠시 뒤에 보내고(횟수 +/−), 아니면 바로 보낸다(한 번 체크).
     * @param {object} item 항목(id·type 이 필요하다)
     * @param {object} entry 바꾼 뒤의 기록
     */
    change(item, entry, { debounced = false } = {}) {
      const id = item.id;
      local[id] = entry;
      seq[id] = latest(id) + 1;
      show(id, entry);
      if (debounced) saver.set(id, { item, entry });
      else push(item, entry);
    },
    /** 대기 중인 횟수 저장을 바로 보낸다(화면을 떠나기 전, 앱이 백그라운드로 가기 전). */
    flushAll: () => saver.flushAll(),
  };
}
