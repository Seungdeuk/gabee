import { useCallback, useEffect, useRef, useState } from "react";

import { listRooms, setRoomMuted } from "./api";
import { roomMutedById } from "./listUtils";
import { familyRoomId } from "./searchUtils";

/**
 * 채팅방 안(서랍)에서 쓰는 "이 방 알림" 상태. 방 목록에서 이 방의 muted 값을 읽고(roomId 가 없으면 가족 전체방),
 * 켜고 끌 때는 화면에 먼저 반영한 뒤 저장하고 실패하면 되돌린다. 값을 알기 전에는 muted 가 null 이다.
 * 저장 중에는 다시 눌러도 무시하고, 저장 중에 도착한 목록 응답은 낙관적 값을 덮어쓰지 않는다.
 * @param {{ roomId: string | null, enabled?: boolean }} args roomId 가 null 이면 가족 전체방. enabled 가 true 가 될 때마다 목록을 다시 읽는다
 * @returns {{ muted: boolean | null, toggle: (muted: boolean) => Promise<boolean | null> }} toggle 은 저장에 성공하면 true, 실패하면 false, 무시했으면 null
 */
export default function useRoomMute({ roomId, enabled = true }) {
  const [muted, setMuted] = useState(null);
  const alive = useRef(true);
  const pending = useRef(false);
  const idRef = useRef(roomId);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    if (!pending.current) setMuted(null); // 다시 열 때 지난번 값을 보이지 않고, 새로 읽을 때까지 스위치를 비활성으로 둔다
    (async () => {
      try {
        const rooms = await listRooms();
        const id = roomId ?? familyRoomId(rooms);
        if (cancelled || !alive.current || !id) return;
        idRef.current = id;
        if (pending.current) return; // 저장 중이면 낙관적 값을 지킨다
        setMuted(roomMutedById(rooms, id));
      } catch {
        // 값을 못 읽으면 스위치가 비활성으로 남는다
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [roomId, enabled]);

  const toggle = useCallback(async (next) => {
    const id = idRef.current ?? null;
    if (!id || pending.current) return null; // 값을 모르거나 저장 중이라 무시한 누름은 실패가 아니다
    pending.current = true;
    setMuted(next);
    try {
      await setRoomMuted(id, next);
      return true;
    } catch {
      if (alive.current) setMuted(!next);
      return false;
    } finally {
      pending.current = false;
    }
  }, []);

  return { muted, toggle };
}
