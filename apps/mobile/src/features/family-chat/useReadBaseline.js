import { useEffect, useRef, useState } from "react";

import { getUnread } from "./api";

export const BASELINE_MAX_MS = 1200; // 이 시간 안에 못 받으면 구분선 없이 지금처럼 연다

/**
 * 방에 들어온 시점의 내 읽음 위치와 안 읽은 수를 한 번만 받아 고정한다("여기까지 읽었습니다" 구분선 기준).
 * 방 정보가 준비되면 바로 GET /family-chat/unread 를 한 번 부른다(읽음 올리기는 약 0.8초 뒤라 그보다 먼저 값을 잡는다).
 * 방이 바뀌면 초기화하고, 실패하거나 시간이 지나면 baseline 은 null 이고 status 는 "failed" 다. 대화 글자는 쓰지 않는다.
 * @param {{ roomId?: string | null, enabled?: boolean }} options roomId 가 없으면 가족 전체방
 * @returns {{ status: "pending" | "ready" | "failed", baseline: { lastRead: number, unread: number } | null }}
 */
export default function useReadBaseline({ roomId = null, enabled = true }) {
  const [state, setState] = useState({ key: null, status: "pending", baseline: null });
  const key = roomId ?? "family";
  const asked = useRef(null); // 방마다 한 번만 부른다

  useEffect(() => {
    if (!enabled || asked.current === key) return undefined;
    asked.current = key;
    let alive = true;
    const give = (next) => {
      if (alive) setState((prev) => (prev.key === key && prev.status !== "pending" ? prev : { key, ...next }));
    };
    const timer = setTimeout(() => give({ status: "failed", baseline: null }), BASELINE_MAX_MS);
    getUnread(roomId)
      .then((res) => {
        const lastRead = Number(res?.last_read_message_id);
        const unread = Number(res?.unread);
        if (Number.isFinite(lastRead) && Number.isFinite(unread)) give({ status: "ready", baseline: { lastRead, unread } });
        else give({ status: "failed", baseline: null });
      })
      .catch(() => give({ status: "failed", baseline: null }));
    return () => {
      alive = false;
      clearTimeout(timer);
      asked.current = null; // 개발 중 효과가 다시 돌아도 다시 받는다
    };
  }, [enabled, key, roomId]);

  if (state.key !== key) return { status: "pending", baseline: null };
  return { status: state.status, baseline: state.baseline };
}
