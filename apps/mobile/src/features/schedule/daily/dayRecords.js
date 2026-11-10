// 날짜별 기록·메모의 화면 쪽 자리. 화면은 이 훅의 함수만 부른다. 저장 로직은 dayStore.js(순수)가 맡고, 여기서는 화면과 api.js 를 이어 준다.
// - 오늘의 체크·횟수는 기존 저장 보조(entrySync: 누르는 즉시 반영·디바운스·롤백)를 그대로 쓴다.
// - 지난 날의 체크·횟수와 모든 날짜의 메모는 서버에 보낸다(api.js setEntry·setNote). 실패하면 되돌리고 onError 로 알린다.
// 읽기(entryOf·memoOf)와 쓰기(checkItem·stepItem·saveMemo)가 이 한 곳에 모여 있다.
import { useReducer, useRef, useState } from "react";

import { setEntry, setNote } from "./api";
import { createDayStore } from "./dayStore";

/**
 * @param {object} deps
 * @param {string} deps.today 오늘(한국 날짜 키)
 * @param {Record<string, object | undefined>} deps.entries 오늘 기록(화면 값, 항목 id → entry)
 * @param {{ valueOf: (id: string) => object | undefined, change: Function, flushAll: () => Promise<unknown> }} deps.sync 오늘 저장 보조(entrySync 객체)
 * @param {(error: unknown) => void} deps.onError 지난 날 기록·메모 저장 실패 안내
 */
export function useDayRecords({ today, entries, sync, onError }) {
  const [, rerender] = useReducer((n) => n + 1, 0);
  // 훅 인수는 매번 새 값이므로, 저장 객체는 가장 최근 값을 ref 로 읽는다(저장 객체 자체는 한 번만 만든다)
  const depsRef = useRef({ today, sync });
  depsRef.current = { today, sync };
  const errorRef = useRef(onError);
  errorRef.current = onError;
  const [store] = useState(() =>
    createDayStore({
      getDeps: () => depsRef.current,
      saveEntry: setEntry,
      saveNote: setNote,
      onChange: () => rerender(),
      onError: (error) => errorRef.current?.(error),
    }),
  );

  /** 화면에 보일 기록. 오늘은 화면 상태(entries), 지난 날은 저장 객체가 든 값을 쓴다. */
  const entryOf = (itemId, date) => (date === today ? entries[itemId] : store.pastEntryOf(itemId, date));

  return {
    entryOf,
    memoOf: store.memoOf,
    checkItem: store.checkItem,
    stepItem: store.stepItem,
    saveMemo: store.saveMemo,
    seedEntries: store.seedEntries,
    seedMemos: store.seedMemos,
    flushAll: store.flushAll,
  };
}
