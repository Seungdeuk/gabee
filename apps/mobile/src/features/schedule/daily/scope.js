import { useFocusEffect } from "expo-router";
import { useCallback, useMemo, useState } from "react";

import { useMeUserId, useMembers } from "../store";

import { loadDevFamily } from "./api";
import { withDevFamily } from "./logic";

/**
 * 데일리 체크 저장 키에 쓰는 사용자 구분 글자. 로그인한 사람(서버 사용자 id)마다 따로 저장하고,
 * 아직 id 를 못 읽었으면(mock 모드 등) "local" 을 쓴다. favorites_hook.js 와 같은 규칙이다.
 * @returns {string}
 */
export function useDailyScope() {
  const meUserId = useMeUserId();
  return meUserId || "local";
}

/**
 * 데일리 체크가 쓰는 가족 구성원 목록(나 포함). 실제 가족에 개발용 가상 가족(엄마·아빠)을 더할지는 플래그로 정한다.
 * 플래그는 화면에 올 때마다 다시 읽는다(편집 화면에서 켜거나 끈 뒤 돌아오면 반영된다).
 * @returns {{ id: string, name: string, hasAccount?: boolean }[]}
 */
export function useDailyMembers() {
  const members = useMembers();
  const scope = useDailyScope();
  const [devOn, setDevOn] = useState(false);

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      loadDevFamily(scope).then((on) => alive && setDevOn(on));
      return () => {
        alive = false;
      };
    }, [scope]),
  );

  // 개발 빌드에서 실제 가족이 없으면 플래그와 상관없이 가상 엄마·아빠를 보인다.
  return useMemo(() => withDevFamily(members, devOn, __DEV__), [members, devOn]);
}
