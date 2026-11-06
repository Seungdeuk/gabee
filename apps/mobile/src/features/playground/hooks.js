import { useCallback } from "react";

import { getMyGroup } from "@/features/family-group/api";
import { isApiConfigured } from "@/shared/api/client";
import useResource from "@/shared/hooks/useResource";

import { boardView, rankingView } from "./adapt";
import { getBoard, getItem, getQuota, getRanking } from "./api";
import { ME, makeLeft, openSent, PAST, RANKING_BY, SENT_PAST, TODO, WAITING } from "./mock";

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

/** 오늘 문제 내기 점수(+20)를 받을 수 있는 남은 횟수. 불러오기 전·실패하면 null(안내를 숨긴다). */
export function useMakeLeft() {
  const loader = useCallback(async () => (playLive() ? (await getQuota()).left : makeLeft()), []);
  return useResource(loader).data ?? null;
}
