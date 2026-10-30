import { usePathname } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState } from "react-native";

import { listRooms } from "./api";
import { totalUnread } from "./listUtils";
import { waitForPendingMarkRead } from "./pendingRead";

export const UNREAD_POLL_MS = 30000;
const UNREAD_POLL_MAX_MS = 300000;

/**
 * 소통 탭 아이콘에 보일 전체 안 읽은 메시지 수(모든 방의 합계).
 * 앱이 앞에 있는 동안 30초마다, 그리고 화면(경로)이 바뀔 때마다 방 목록을 한 번 불러와 합산한다(채팅방을 나오면 바로 줄어든다).
 * 실패하면(로그아웃·가족 없음·네트워크) 조용히 0 으로 두고 간격을 늘린다(최대 5분). 대화 글자는 쓰지 않고 AI 를 부르지 않는다.
 * @returns {number}
 */
export default function useTotalUnread() {
  const pathname = usePathname();
  const [count, setCount] = useState(0);
  const alive = useRef(true);
  const failures = useRef(0);
  const timer = useRef(null);
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    if (inFlight.current || AppState.currentState === "background") return;
    inFlight.current = true;
    try {
      await waitForPendingMarkRead(); // 방을 막 나왔다면 읽음 올리기가 끝난 뒤에 합계를 가져온다(소통 탭 목록과 같은 기준)
      const rooms = await listRooms();
      failures.current = 0;
      if (alive.current) setCount(totalUnread(rooms));
    } catch {
      failures.current += 1;
      if (alive.current) setCount(0);
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    const schedule = () => {
      const delay = Math.min(UNREAD_POLL_MAX_MS, UNREAD_POLL_MS * 2 ** Math.min(failures.current, 4));
      timer.current = setTimeout(async () => {
        await load();
        if (alive.current) schedule();
      }, delay);
    };
    schedule();
    const sub = AppState.addEventListener("change", (next) => {
      if (next === "active") load();
    });
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
      sub.remove();
    };
  }, [load]);

  // 화면(경로)이 바뀔 때마다 한 번 새로 불러온다
  useEffect(() => {
    load();
  }, [pathname, load]);

  return count;
}
