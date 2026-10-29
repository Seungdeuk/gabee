import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";

import { getRoomInfo, listScheduleEvents, listTogetherRequests } from "./api";
import { isNoGroup } from "./chatUtils";
import { memberName } from "./listUtils";
import { buildBrief, dateKey } from "./togetherUtils";

/**
 * 서랍 "가족 할 일" 화면의 내역: 일정 탭의 할 일 + 함께하기를 간소화해서 모은다. 화면이 보일 때와 새로고침(refresh)으로만 불러온다(폴링 없음).
 * 일정·요청 둘 중 하나만 실패해도 받은 쪽은 보여 주고, 둘 다 실패하면 오류로 본다. 제목은 로그에 남기지 않는다.
 * @returns {{ status: "loading" | "ready" | "none" | "error", error: string, items: ReturnType<typeof buildBrief>, refreshing: boolean, reload: () => Promise<void>, refresh: () => Promise<void> }}
 */
export default function useFamilyTogether() {
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [items, setItems] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const seq = useRef(0);

  const load = useCallback(async () => {
    seq.current += 1;
    const mine = seq.current;
    let group;
    try {
      group = await getRoomInfo(); // 별명이 입혀진 이름
    } catch (e) {
      if (seq.current !== mine) return;
      if (isNoGroup(e)) setStatus("none");
      else {
        setStatus("error");
        setError("불러오지 못했어요. 다시 시도해 주세요");
      }
      return;
    }
    const [events, requests] = await Promise.allSettled([listScheduleEvents(), listTogetherRequests()]);
    if (seq.current !== mine) return;
    if (events.status === "rejected" && requests.status === "rejected") {
      setStatus("error");
      setError("불러오지 못했어요. 다시 시도해 주세요");
      return;
    }
    const names = Object.fromEntries((group.members ?? []).map((m) => [m.id, memberName(m)]));
    setItems(
      buildBrief({
        events: events.status === "fulfilled" ? events.value : [],
        requests: requests.status === "fulfilled" ? requests.value : [],
        myId: group.my_id ?? null,
        today: dateKey(new Date()),
        nameOf: (id) => names[id],
      }),
    );
    setError("");
    setStatus("ready");
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
      return () => {
        seq.current += 1; // 화면을 떠나면 늦게 온 응답은 버린다
      };
    }, [load]),
  );

  const refresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  return { status, error, items, refreshing, reload: load, refresh };
}
