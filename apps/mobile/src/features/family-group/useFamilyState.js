import { useCallback, useEffect, useState } from "react";

import { getMyGroup, getMyJoinRequest, listJoinRequests } from "./api";
import { familyErrorMessage } from "./messages";

const MANAGER = ["owner", "admin"];

/** 404(그룹 없음) 같은 "없음"은 오류가 아니라 빈 값으로 본다. */
const orNull = (promise) => promise.catch((e) => (e?.status === 404 ? null : Promise.reject(e)));

/**
 * 내 가족 그룹 상태.
 * - loading → none(그룹도 대기 요청도 없음) | pending(승인 대기 중) | member(구성원) | error
 * - member 이고 관리자(owner/admin)면 pendingCount 에 승인 대기 요청 수가 들어 있다(조회 실패는 0으로 둔다).
 * @returns {{ status: "loading" | "none" | "pending" | "member" | "error", group: object | null, request: object | null, isManager: boolean, pendingCount: number, error: string, reload: () => Promise<void> }}
 */
export default function useFamilyState() {
  const [state, setState] = useState({ status: "loading", group: null, request: null, pendingCount: 0, error: "" });

  const reload = useCallback(async () => {
    try {
      const [group, request] = await Promise.all([orNull(getMyGroup()), orNull(getMyJoinRequest())]);
      if (group) {
        const manager = MANAGER.includes(group.my_role);
        const pendingCount = manager ? await listJoinRequests().then((rows) => rows.length, () => 0) : 0;
        setState({ status: "member", group, request, pendingCount, error: "" });
      } else {
        setState({ status: request?.status === "pending" ? "pending" : "none", group: null, request, pendingCount: 0, error: "" });
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
