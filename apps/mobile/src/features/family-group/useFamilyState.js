import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";

import { getMyGroup, getMyJoinRequest, listJoinRequests, listNicknames } from "./api";
import { familyErrorMessage } from "./messages";

const MANAGER = ["owner", "admin"];

/** 404(그룹 없음) 같은 "없음"은 오류가 아니라 빈 값으로 본다. */
const orNull = (promise) => promise.catch((e) => (e?.status === 404 ? null : Promise.reject(e)));

/**
 * 내 가족 그룹 상태.
 * - loading → none(그룹도 대기 요청도 없음) | pending(승인 대기 중) | member(구성원) | error
 * - member 이고 관리자(owner/admin)면 pendingRequests 에 승인 대기 요청 목록, pendingCount 에 그 수가 들어 있다(조회 실패는 빈 목록).
 * - member 이면 nicknames 에 내가 붙인 별명이 구성원 id 별로 들어 있다.
 * - 화면이 다시 보일 때마다 새로 불러오고, pollMs 를 주면 그 간격으로도 조용히(로딩 표시 없이) 다시 불러온다 — 가입 요청이 들어오거나 승인되는 것을 바로 보여 주려는 것이다.
 * @param {{ pollMs?: number }} [options] pollMs: 0(기본)이면 주기적으로 불러오지 않는다
 * @returns {{ status: "loading" | "none" | "pending" | "member" | "error", group: object | null, request: object | null, isManager: boolean, pendingCount: number, pendingRequests: object[], nicknames: Record<string, { nickname: string | null, memo: string | null }>, error: string, reload: () => Promise<void> }}
 */
export default function useFamilyState({ pollMs = 0 } = {}) {
  const [state, setState] = useState({ status: "loading", group: null, request: null, pendingCount: 0, pendingRequests: [], nicknames: {}, error: "" });
  const loading = useRef(false);
  const again = useRef(false);

  const reload = useCallback(async function load() {
    if (loading.current) {
      again.current = true; // 진행 중이면 겹쳐 부르지 않고, 끝난 뒤 한 번 더 불러온다(방금 한 승인·거절이 바로 보이게)
      return;
    }
    loading.current = true;
    try {
      const [group, request] = await Promise.all([orNull(getMyGroup()), orNull(getMyJoinRequest())]);
      if (group) {
        const manager = MANAGER.includes(group.my_role);
        const pendingRequests = manager ? await listJoinRequests().catch(() => []) : [];
        // 내가 붙인 별명(내 화면에만 쓴다). 못 불러와도 가족 화면은 보여 준다
        const nicknames = await listNicknames().then(
          (rows) => Object.fromEntries(rows.map((r) => [r.target_user_id, r])),
          () => ({}),
        );
        setState({ status: "member", group, request, pendingCount: pendingRequests.length, pendingRequests, nicknames, error: "" });
      } else {
        setState({ status: request?.status === "pending" ? "pending" : "none", group: null, request, pendingCount: 0, pendingRequests: [], nicknames: {}, error: "" });
      }
    } catch (e) {
      setState((prev) => ({ ...prev, status: "error", error: familyErrorMessage(e) }));
    } finally {
      loading.current = false;
      if (again.current) {
        again.current = false;
        load();
      }
    }
  }, []);

  // 화면이 처음 열릴 때와 다른 화면에서 돌아올 때마다 새로 불러온다
  useFocusEffect(
    useCallback(() => {
      reload();
    }, [reload]),
  );

  useEffect(() => {
    if (!pollMs) return undefined;
    const timer = setInterval(reload, pollMs);
    return () => clearInterval(timer);
  }, [pollMs, reload]);

  return { ...state, isManager: MANAGER.includes(state.group?.my_role), reload };
}
