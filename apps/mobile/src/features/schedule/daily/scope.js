import { useMemo } from "react";

import { useMeUserId, useMembers } from "../store";

import { withDevFamily } from "./logic";

/**
 * 가족 탭 순서·숨김을 폰에 저장할 때 쓰는 사용자 구분 글자. 로그인한 사람의 서버 사용자 id 를 쓰고,
 * 아직 id 를 못 읽었으면(서버 없음 등) "local" 을 쓴다. favorites_hook.js 와 같은 규칙이다.
 * @returns {string}
 */
export function useDailyScope() {
  const meUserId = useMeUserId();
  return meUserId || "local";
}

/**
 * 데일리 체크가 쓰는 가족 구성원 목록(나 포함). 서버 가족 목록을 그대로 쓰고,
 * 개발 빌드에서 실제 가족이 한 명도 없을 때만 가상 가족(엄마·아빠 …)을 읽기 전용으로 덧붙인다(logic.js withDevFamily).
 * @returns {{ id: string, name: string, hasAccount?: boolean }[]}
 */
export function useDailyMembers() {
  const members = useMembers();
  return useMemo(() => withDevFamily(members, __DEV__), [members]);
}
