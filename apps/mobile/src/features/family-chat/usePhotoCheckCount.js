import { useEffect, useState } from "react";

import { listMyPhotoChecks } from "./api";

/**
 * 서랍을 열 때마다 "내가 올린 사진 중 확인이 필요한 장수"만 가볍게 묻는다(사진 한 장 분량만 받는다). 가족 전체방에서만 부른다.
 * 모르면(조회 실패·아직 받는 중·서랍이 닫힘) null 이라 진입 행이 보이지 않는다 — 실패를 0장으로 단정하지도, 행을 억지로 보이지도 않는다.
 * @param {{ enabled: boolean }} args enabled 는 서랍이 열려 있고 가족 전체방일 때만 true
 * @returns {number | null}
 */
export default function usePhotoCheckCount({ enabled }) {
  const [count, setCount] = useState(null);

  useEffect(() => {
    if (!enabled) return undefined;
    let alive = true;
    setCount(null); // 열 때마다 옛 숫자가 잠깐 보이지 않게
    listMyPhotoChecks({ limit: 1 }).then(
      (page) => {
        if (alive) setCount(Number.isInteger(page?.needs_review_count) ? page.needs_review_count : null);
      },
      () => {
        if (alive) setCount(null);
      },
    );
    return () => {
      alive = false;
    };
  }, [enabled]);

  return enabled ? count : null;
}
