import { useCallback, useEffect, useState } from "react";

import { getMyGroup, getMyJoinRequest, listJoinRequests, listNicknames } from "./api";
import { familyErrorMessage } from "./messages";

const MANAGER = ["owner", "admin"];

/** 404(그룹 없음) 같은 "없음"은 오류가 아니라 빈 값으로 본다. */
const orNull = (promise) => promise.catch((e) => (e?.status === 404 ? null : Promise.reject(e)));

/**
 * 내 가족 그룹 상태.
 * - loading → none(그룹도 대기 요청도 없음) | pending(승인 대기 중) | member(구성원) | error
 * - member 이고 관리자(owner/admin)면 pendingCount 에 승인 대기 요청 수가 들어 있다(조회 실패는 0으로 둔다).
 * - member 이면 nicknames 에 내가 붙인 별명이 구성원 id 별로 들어 있다.
 * @returns {{ status: "loading" | "none" | "pending" | "member" | "error", group: object | null, request: object | null, isManager: boolean, pendingCount: number, nicknames: Record<string, { nickname: string | null, memo: string | null }>, error: string, reload: () => Promise<void> }}
 */
export default function useFamilyState() {
  const [state, setState] = useState({ status: "loading", group: null, request: null, pendingCount: 0, nicknames: {}, error: "" });

  const reload = useCallback(async () => {
    try {
      const [group, request] = await Promise.all([orNull(getMyGroup()), orNull(getMyJoinRequest())]);
      if (group) {
        const manager = MANAGER.includes(group.my_role);
        const pendingCount = manager ? await listJoinRequests().then((rows) => rows.length, () => 0) : 0;
        // 내가 붙인 별명(내 화면에만 쓴다). 못 불러와도 가족 화면은 보여 준다
        const nicknames = await listNicknames().then(
          (rows) => Object.fromEntries(rows.map((r) => [r.target_user_id, r])),
          () => ({}),
        );
        setState({ status: "member", group, request, pendingCount, nicknames, error: "" });
      } else {
        setState({ status: request?.status === "pending" ? "pending" : "none", group: null, request, pendingCount: 0, nicknames: {}, error: "" });
      }
    } catch (e) {
      setState((prev) => ({ ...prev, status: "error", error: familyErrorMessage(e) }));
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  return { ...state, isManager: MANAGER.includes(state.group?.my_role), reload };
}
