import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";

import { getMyGroup } from "@/features/family-group/api";
import { isApiConfigured } from "@/shared/api/client";
import useResource from "@/shared/hooks/useResource";

import { bombPath, bombScreen, boardView, rankingView } from "./adapt";
import { getBoard, getBomb, getBombOpen, getDrawRecs, getItem, getPhotoRecs, getQuizRecs, getQuota, getRanking } from "./api";
import { ME, MOCK_DRAW_RECS, MOCK_PHOTO_RECS, MOCK_RECS, makeLeft, openSent, PAST, RANKING_BY, SENT_PAST, TODO, WAITING } from "./mock";

/** 서버 주소가 있으면 서버에서, 없으면 시안(mock.js)으로 동작한다. */
export const playLive = () => isApiConfigured();

const mockBoard = () => ({ todo: TODO, waiting: WAITING, past: PAST, sent: openSent(), sentPast: SENT_PAST });

/**
 * 놀이터 현황판 { todo, waiting, past, sent, sentPast }. 다른 화면에 다녀오면 다시 불러온다(useResource).
 * @returns {{ data: ReturnType<typeof boardView> | null, error: string, loading: boolean, reload: () => Promise<void> }}
 */
export function usePlayBoard() {
  const loader = useCallback(async () => (playLive() ? boardView(await getBoard()) : mockBoard()), []);
  return useResource(loader);
}

/** 순위 줄 목록(점수 높은 순). period: "week" | "month" | "all" */
export function usePlayRanking(period) {
  const loader = useCallback(async () => (playLive() ? rankingView(await getRanking(period)) : RANKING_BY[period]), [period]);
  return useResource(loader);
}

/** 문제 한 건(서버 PlayItemOut). 서버 주소가 없거나 id 가 없으면 null — 화면은 시안 데이터로 그린다. */
export function usePlayItem(id) {
  const loader = useCallback(async () => (playLive() && id ? getItem(id) : null), [id]);
  return useResource(loader);
}

/** 내 사용자 id(순위에서 나를 표시). 서버 주소가 없으면 시안의 "me". 불러오지 못하면 null. */
export function useMyId() {
  const loader = useCallback(async () => (playLive() ? (await getMyGroup()).my_id : ME.id), []);
  return useResource(loader).data ?? null;
}

/** 누구에게 낼지 고를 가족(나 제외): [{ id, name }]. 서버 주소가 없으면 시안의 엄마·아빠·딸. */
export function useAudience() {
  const loader = useCallback(async () => {
    if (!playLive()) return ["엄마", "아빠", "딸"].map((name) => ({ id: name, name }));
    const group = await getMyGroup();
    return group.members.filter((m) => m.id !== group.my_id).map((m) => ({ id: m.id, name: m.display_name || m.name }));
  }, []);
  return useResource(loader).data ?? [];
}

/** 골든벨 가비 추천 { state, items }. 서버 주소가 없으면 시안(MOCK_RECS). 서버는 하루 한 번만 만들고 같은 날은 같은 묶음을 준다(실패일 때만 다시 만든다). */
export function useQuizRecs() {
  const loader = useCallback(async () => (playLive() ? getQuizRecs() : MOCK_RECS), []);
  return useResource(loader);
}

/** 이게 뭐게 가비 추천 { state, items }. 서버 주소가 없으면 시안(MOCK_DRAW_RECS). 처음 열 때는 그림을 만드느라 15~40초쯤 걸릴 수 있고, 같은 날은 같은 묶음을 준다. */
export function useDrawRecs() {
  const loader = useCallback(async () => (playLive() ? getDrawRecs() : MOCK_DRAW_RECS), []);
  return useResource(loader);
}

/** 찰칵! 탐정단 가비 추천 { state, items }. 서버 주소가 없으면 시안(MOCK_PHOTO_RECS). */
export function usePhotoRecs() {
  const loader = useCallback(async () => (playLive() ? getPhotoRecs() : MOCK_PHOTO_RECS), []);
  return useResource(loader);
}

/** 오늘 문제 내기 점수(+20)를 받을 수 있는 남은 횟수. 불러오기 전·실패하면 null(안내를 숨긴다). */
export function useMakeLeft() {
  const loader = useCallback(async () => (playLive() ? (await getQuota()).left : makeLeft()), []);
  return useResource(loader).data ?? null;
}

const ROOMS_POLL_MS = 3000;

/** 우리 가족의 열린 폭탄방 목록. 화면이 보이는 동안 3초마다 새로 받는다. rooms 가 null 이면 아직 못 받은 것. */
export function useBombRooms() {
  const [rooms, setRooms] = useState(null);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    try {
      setRooms(await getBombOpen());
      setError("");
    } catch (e) {
      setError(e.message || "방 목록을 불러오지 못했어요");
    }
  }, []);
  useFocusEffect(
    useCallback(() => {
      refresh();
      const timer = setInterval(refresh, ROOMS_POLL_MS);
      return () => clearInterval(timer);
    }, [refresh]),
  );
  return { rooms, error, refresh };
}

const BOMB_POLL_MS = 1000;

/**
 * 폭탄방 상태를 1초마다 물어서 받는다(폴링). 화면이 보일 때만 돈다.
 * - act(action): 말하기·시작 같은 요청을 보내고, 돌려받은 상태를 바로 화면에 반영한다. 실패하면 error 에 문구를 두고 null 을 돌려준다.
 * - left: 지금 차례의 남은 초(받은 값에서 시계로 줄인다), cheerLeft: 다음 응원까지 남은 초
 * @param {string | null | undefined} id 방 id
 */
export function useBombRoom(id) {
  const [room, setRoom] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [, setTick] = useState(0);
  const receivedAt = useRef(Date.now());
  const alive = useRef(true);
  const inflight = useRef(false);

  const apply = useCallback((next) => {
    receivedAt.current = Date.now();
    setRoom(next);
    setError("");
  }, []);

  const refresh = useCallback(async () => {
    if (!id || inflight.current) return;
    inflight.current = true;
    try {
      const next = await getBomb(id);
      if (alive.current) apply(next);
    } catch (e) {
      if (alive.current) setError(e.message || "연결이 불안정해요");
    } finally {
      inflight.current = false;
    }
  }, [id, apply]);

  useFocusEffect(
    useCallback(() => {
      alive.current = true;
      refresh();
      const poll = setInterval(refresh, BOMB_POLL_MS);
      const clock = setInterval(() => setTick((n) => n + 1), 250); // 남은 시간 막대를 부드럽게
      return () => {
        alive.current = false;
        clearInterval(poll);
        clearInterval(clock);
      };
    }, [refresh]),
  );

  const act = useCallback(
    async (action) => {
      setBusy(true);
      try {
        const next = await action();
        if (alive.current) apply(next);
        return next;
      } catch (e) {
        if (alive.current) setError(e.message || "잠시 뒤 다시 해 주세요");
        return null;
      } finally {
        if (alive.current) setBusy(false);
      }
    },
    [apply],
  );

  const elapsed = (Date.now() - receivedAt.current) / 1000;
  const left = room?.turn ? Math.max(0, room.turn.seconds_left - (room.vote ? 0 : elapsed)) : null; // 투표 중에는 게임 시계가 멈춘다
  const voteLeft = room?.vote ? Math.max(0, room.vote.seconds_left - elapsed) : null;
  const cheerLeft = room ? Math.max(0, room.cheer_wait - elapsed) : 0;
  const chatLeft = room ? Math.max(0, (room.chat_wait ?? 0) - elapsed) : 0;
  return { room, error, busy, act, left, voteLeft, cheerLeft, chatLeft };
}

/** 방 상태에 맞지 않는 폭탄 화면에 있으면 알맞은 화면으로 옮겨 간다(게임이 시작되면 로비 → 게임, 탈락하면 게임 → 관전, 끝나면 결과). */
export function useBombRedirect(room, self, enabled = true) {
  const router = useRouter();
  const target = room ? bombScreen(room, self) : self;
  const id = room?.id;
  useEffect(() => {
    if (enabled && id && target !== self) router.replace(bombPath(target, id));
  }, [enabled, id, target, self, router]);
}
