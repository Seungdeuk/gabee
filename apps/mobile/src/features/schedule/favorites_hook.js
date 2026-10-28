import { useEffect, useState } from "react";

import { hideId, pruneHidden, showId } from "./favorites";
import { loadHiddenWho, saveHiddenWho } from "./favorites_store";
import { useMeUserId } from "./store";

/**
 * "누구" 칩 줄에서 뺀 사람 목록과 빼기·다시 넣기(이 폰에만 저장, 내 사용자 id 별로 따로).
 * name 이 다르면 칩 줄마다 따로 저장한다. name 이 비면 등록 화면이 예전부터 쓰던 저장 키 그대로다.
 * @param {string} name 칩 줄 이름("", "filter", "together", "share" …)
 * @param {{ id: string }[]} all 이 칩 줄에 나올 수 있는 사람 전체(가족이 바뀌어 없어진 id 는 정리한다)
 * @returns {{ hidden: string[], hide: (id: string) => void, show: (id: string) => void }}
 */
export function useHiddenWho(name, all) {
  const meUserId = useMeUserId();
  const base = meUserId || "local";
  const scope = name ? `${base}.${name}` : base;
  const [hidden, setHidden] = useState([]);

  // 저장된 목록을 읽는다. 읽기에 실패하면 아무도 안 뺀 상태.
  useEffect(() => {
    let alive = true;
    loadHiddenWho(scope).then((ids) => alive && setHidden(ids));
    return () => {
      alive = false;
    };
  }, [scope]);

  const commit = (next) => {
    const kept = pruneHidden(next, all);
    setHidden(kept);
    saveHiddenWho(scope, kept);
  };
  return { hidden, hide: (id) => commit(hideId(hidden, id)), show: (id) => commit(showId(hidden, id)) };
}
