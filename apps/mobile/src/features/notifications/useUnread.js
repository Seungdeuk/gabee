import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";

import { getUnreadCount } from "./api";
import { safeTotal } from "./format";

/**
 * 안 읽은 알림 개수. 화면에 돌아올 때마다 다시 읽고, 못 읽으면 0 이다(예외를 던지지 않는다).
 * @returns {{ total: number, refresh: () => Promise<void> }}
 */
export default function useUnread() {
  const [total, setTotal] = useState(0);
  const refresh = useCallback(async () => {
    setTotal(await safeTotal(getUnreadCount()));
  }, []);
  useFocusEffect(
    useCallback(() => {
      refresh();
    }, [refresh]),
  );
  return { total, refresh };
}
