// 날짜별 기록·메모의 저장 로직(리액트와 떨어진 순수 객체). dayRecords.js 의 훅이 이 객체를 감싸고, 시험은 tests/schedule_daily_store.test.js 가 가짜 서버로 돌린다.
// - 오늘의 체크·횟수는 화면의 기존 저장 보조(sync, entrySync.js)가 맡는다. 여기서는 오늘 값을 읽어 그 보조에 넘긴다.
// - 지난 날의 체크·횟수는 날짜마다 entrySync 를 하나씩 만든다(낙관 갱신·디바운스·롤백을 오늘과 같은 방식으로).
// - 메모는 모든 날짜가 같다: 누르는 즉시 화면에 두고 서버에 보낸다. 항목·날짜마다 줄을 세우고 가장 최근 변경의 응답만 화면에 반영한다.
//   실패하면 서버가 마지막으로 확인한 메모로 되돌리고 onError 를 부른다.
// - 기록 응답은 기록만, 메모 응답은 메모만 쓴다(요청이 달라서 한쪽 응답이 다른 쪽을 지우지 않는다).
import { createEntrySync } from "./entrySync";
import { applyCheck, applyStep, nowClock } from "./logic";
import { createKeyedQueue, isLatestChange } from "./sync";

const memoKey = (date, itemId) => `${date}|${itemId}`;

/** 날짜별 객체의 값을 넣는다. value 가 undefined 면 지운다. */
function put(box, date, itemId, value) {
  const day = { ...box[date] };
  if (value === undefined) delete day[itemId];
  else day[itemId] = value;
  box[date] = day;
}

/**
 * @param {object} deps
 * @param {() => { today: string, sync: object }} deps.getDeps 오늘 날짜 키와 오늘 저장 보조(entrySync)를 매번 읽는다
 * @param {(item: object, entry: object, date: string) => Promise<object>} deps.saveEntry 지난 날 기록 저장(api.setEntry)
 * @param {(item: object, date: string, memo: object | null) => Promise<object>} deps.saveNote 메모 저장(api.setNote)
 * @param {() => void} deps.onChange 화면 값이 바뀌었을 때 부른다(화면을 다시 그린다)
 * @param {(error: unknown) => void} deps.onError 저장 실패를 알린다(값은 되돌린 뒤에 부른다)
 * @param {number} [deps.delay] 횟수 디바운스 시간(ms)
 * @param {Function} [deps.setTimer]
 * @param {Function} [deps.clearTimer]
 */
export function createDayStore({ getDeps, saveEntry, saveNote, onChange, onError, delay, setTimer, clearTimer }) {
  const pastEntries = {}; // 지난 날 기록(화면 값): 날짜 → { 항목 id: entry }
  const pastSyncs = {}; // 지난 날 저장 보조: 날짜 → entrySync
  const memos = {}; // 메모(화면 값, 모든 날짜): 날짜 → { 항목 id: { note, noteShared } }
  const committed = {}; // 메모(서버가 확인한 값, 롤백용): 날짜 → { 항목 id: memo }
  const memoSeq = {}; // 메모 최근 변경 번호: 날짜|항목
  const memoBusy = {}; // 저장 중인 메모 요청 수: 날짜|항목
  const enqueueMemo = createKeyedQueue();

  function pastSyncOf(date) {
    if (!pastSyncs[date]) {
      pastSyncs[date] = createEntrySync({
        send: (item, entry) => saveEntry(item, entry, date),
        show: (id, entry) => {
          put(pastEntries, date, id, entry);
          onChange();
        },
        onError,
        delay,
        setTimer,
        clearTimer,
      });
    }
    return pastSyncs[date];
  }

  /** 기록을 바꾸는 저장 보조: 오늘은 화면의 것, 지난 날은 날짜별 것. */
  const syncFor = (date) => (date === getDeps().today ? getDeps().sync : pastSyncOf(date));

  /** 바꾸기 전에 읽는 최신 기록(연타에도 최신 값). */
  const latestOf = (item, date) =>
    date === getDeps().today ? getDeps().sync.valueOf(item.id) : pastEntries[date]?.[item.id];

  /** 화면에 보일 지난 날 기록(오늘은 화면 상태가 들고 있으므로 쓰지 않는다). */
  const pastEntryOf = (itemId, date) => pastEntries[date]?.[itemId];

  /** 한 번 체크를 누른다(켜져 있으면 끈다). */
  function checkItem(item, date) {
    syncFor(date).change(item, applyCheck(latestOf(item, date), nowClock()));
  }

  /** 횟수를 delta 만큼 바꾼다. 디바운스로 마지막 값만 보낸다. */
  function stepItem(item, date, delta) {
    syncFor(date).change(item, applyStep(item, latestOf(item, date), delta, nowClock()), { debounced: true });
  }

  /** 지난 날 목록을 받았을 때 그날 기록을 맞춘다(저장이 남은 항목은 화면 값을 우선한다). items 는 itemFromServer 결과다. */
  function seedEntries(date, items) {
    const serverEntries = Object.fromEntries(items.map((item) => [item.id, item.entry]));
    pastEntries[date] = pastSyncOf(date).seed(serverEntries);
    onChange();
  }

  /** 날짜의 목록을 받았을 때 그날 메모를 맞춘다(저장이 남은 항목은 화면 값을 우선한다). items 는 itemFromServer 결과다. */
  function seedMemos(date, items) {
    const serverMemos = {};
    for (const item of items) {
      if (item.memo) serverMemos[item.id] = item.memo;
    }
    committed[date] = serverMemos;
    const shown = {};
    for (const item of items) {
      const busy = (memoBusy[memoKey(date, item.id)] ?? 0) > 0;
      const value = busy ? memos[date]?.[item.id] : serverMemos[item.id];
      if (value) shown[item.id] = value;
    }
    memos[date] = shown;
    onChange();
  }

  /** 그날 메모({ note, noteShared }) 또는 없음(undefined). */
  const memoOf = (itemId, date) => memos[date]?.[itemId];

  /**
   * 메모를 저장하거나 지운다(memo 가 null 이면 지운다). 기록(체크)과 따로 보낸다.
   * 화면에는 바로 보이고, 서버 응답의 메모로 맞춘다. 실패하면 서버가 마지막으로 확인한 메모로 되돌리고 알린다.
   */
  function saveMemo(item, date, memo) {
    const key = memoKey(date, item.id);
    const mine = (memoSeq[key] ?? 0) + 1;
    memoSeq[key] = mine;
    put(memos, date, item.id, memo ?? undefined);
    memoBusy[key] = (memoBusy[key] ?? 0) + 1;
    onChange();
    enqueueMemo(key, () => saveNote(item, date, memo ?? null)).then(
      (saved) => {
        memoBusy[key] -= 1;
        put(committed, date, item.id, saved.memo);
        if (isLatestChange(mine, memoSeq[key])) {
          put(memos, date, item.id, saved.memo);
          onChange();
        }
      },
      (error) => {
        memoBusy[key] -= 1;
        if (!isLatestChange(mine, memoSeq[key])) return; // 그 뒤에 더 새 변경이 있으면 그 변경이 화면을 정한다
        put(memos, date, item.id, committed[date]?.[item.id]);
        onChange();
        onError(error);
      },
    );
  }

  /** 대기 중인 저장을 모두 바로 보낸다(화면을 떠나거나 앱이 백그라운드로 갈 때). 오늘과 지난 날의 기록 모두. */
  function flushAll() {
    return Promise.all([getDeps().sync.flushAll(), ...Object.values(pastSyncs).map((s) => s.flushAll())]);
  }

  return { pastEntryOf, memoOf, checkItem, stepItem, seedEntries, seedMemos, saveMemo, flushAll };
}
