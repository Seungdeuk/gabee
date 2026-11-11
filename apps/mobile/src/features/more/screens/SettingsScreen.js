import Constants from "expo-constants";
import { useRouter } from "expo-router";
import { useState } from "react";

import { useAuth } from "@/shared/auth/AuthProvider";
import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";

import { versionText } from "../appInfo";
import MenuList from "../components/MenuList";
import { settingsAction, settingsSections } from "../settingsItems";

/**
 * 환경설정: 일반(앱 버전)·시스템 설정(준비 중)·알림설정(푸시 설정 화면으로 이동)·개인 보안(로그아웃) 네 구역.
 * 로그아웃이 끝나면 처음(시작) 화면으로 돌아간다. 로그인 전에는 로그아웃 줄(개인 보안 구역)을 보이지 않는다.
 * @returns {import("react").ReactElement}
 */
export default function SettingsScreen() {
  const router = useRouter();
  const { status, signOut } = useAuth();
  const [busy, setBusy] = useState(false);

  const sections = settingsSections(versionText(Constants.expoConfig?.version))
    .map((section) => ({
      ...section,
      items: section.items
        .filter((item) => item.action !== "logout" || status === "authenticated")
        .map((item) => (item.action === "logout" && busy ? { ...item, title: "로그아웃 중..." } : item)),
    }))
    .filter((section) => section.items.length > 0);

  /**
   * 줄을 눌렀을 때: 화면 이동, 로그아웃, 또는 아무 일 없음.
   * @param {{ route?: string, action?: string, static?: boolean }} item
   * @returns {Promise<void>}
   */
  const open = async (item) => {
    const action = settingsAction(item);
    if (action.type === "route") router.push(action.path);
    else if (action.type === "logout" && !busy) {
      setBusy(true);
      try {
        await signOut();
        router.replace("/"); // 처음(시작) 화면으로 돌아간다
      } finally {
        setBusy(false);
      }
    }
  };

  return (
    <Screen
      title="환경설정"
      left={<IconButton name="chevron-back" label="뒤로" onPress={() => (router.canGoBack() ? router.back() : router.replace("/my"))} />}
    >
      <MenuList sections={sections} onPressItem={open} />
    </Screen>
  );
}
