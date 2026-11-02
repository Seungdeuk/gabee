import Constants from "expo-constants";
import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { useAuth } from "@/shared/auth/AuthProvider";
import Screen from "@/shared/components/Screen";
import { colors, font, radius, spacing } from "@/theme";

import { versionText } from "../appInfo";
import MenuList from "../components/MenuList";
import ProfileCard from "../components/ProfileCard";
import ShortcutGrid from "../components/ShortcutGrid";
import { itemAction, MENU, SHORTCUTS, SOON_MESSAGE } from "../menuItems";

const NOTICE_MS = 2200;

/**
 * 마이 페이지(하단 탭): 프로필 카드, 바로가기 4칸, 목록 5줄, 맨 아래 로그아웃과 앱 버전.
 * 가족 정보는 다른 기능이라 라우트가 읽어서 넘겨 준다(groupName·roleText·pendingCount). "준비 중" 항목은 안내 문구만 잠깐 보인다.
 * displayName·photoUrl 은 가족 안에서 쓰는 내 이름과 사진이고(없으면 계정 이름·사진), canEdit 이 true 일 때만 "내 정보 수정"이 보인다.
 * @param {{ displayName?: string | null, photoUrl?: string | null, groupName?: string | null, roleText?: string | null, canEdit?: boolean, pendingCount?: number }} props
 * @returns {import("react").ReactElement}
 */
export default function MoreScreen({ displayName = null, photoUrl = null, groupName = null, roleText = null, canEdit = false, pendingCount = 0 }) {
  const router = useRouter();
  const { status, user, signOut, restore } = useAuth();
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);

  useEffect(() => () => clearTimeout(timer.current), []);

  /**
   * 안내 문구를 잠깐 띄운다(같은 문구를 연달아 눌러도 시간이 다시 시작된다).
   * @param {string} text
   * @returns {void}
   */
  const showNotice = (text) => {
    clearTimeout(timer.current);
    setNotice(text);
    timer.current = setTimeout(() => setNotice(""), NOTICE_MS);
  };

  /**
   * 바로가기·목록 항목을 눌렀을 때: 화면이 있으면 이동하고, 아니면 "준비 중" 안내를 보인다.
   * @param {{ route?: string, soon?: boolean }} item
   * @returns {void}
   */
  const open = (item) => {
    const action = itemAction(item);
    if (action.type === "route") router.push(action.path);
    else showNotice(SOON_MESSAGE);
  };

  const menu = MENU.map((item) => (item.key === "family" && pendingCount > 0 ? { ...item, badge: `요청 ${pendingCount}건` } : item));

  return (
    <View style={styles.root}>
      <Screen title="마이페이지">
      <ProfileCard user={user} status={status} displayName={displayName} photoUrl={photoUrl} groupName={groupName} roleText={roleText} onEdit={canEdit ? () => router.push("/family-profile") : undefined} onLogin={() => router.push("/login")} onRetry={restore} />
      <ShortcutGrid items={SHORTCUTS} onPressItem={open} />
      <MenuList items={menu} onPressItem={open} />
      <View style={styles.footer}>
        {status === "authenticated" ? (
          <Pressable
            disabled={busy}
            hitSlop={spacing.md}
            style={styles.logout}
            accessibilityRole="button"
            accessibilityLabel="로그아웃"
            onPress={async () => {
              setBusy(true);
              try {
                await signOut();
                router.replace("/"); // 처음(시작) 화면으로 돌아간다
              } finally {
                setBusy(false);
              }
            }}
          >
            <Text style={styles.footerText}>{busy ? "로그아웃 중..." : "로그아웃"}</Text>
          </Pressable>
        ) : (
          <View />
        )}
        <View accessibilityLabel="앱 버전" testID="app-version">
          <Text style={styles.footerText}>{`앱 버전 · ${versionText(Constants.expoConfig?.version)}`}</Text>
        </View>
      </View>
      </Screen>
      {notice ? (
        <View style={styles.toast} pointerEvents="none" accessibilityRole="alert" accessibilityLiveRegion="polite">
          <Text style={styles.toastText}>{notice}</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  toast: { position: "absolute", left: spacing.xl, right: spacing.xl, bottom: spacing.xxl, alignItems: "center" },
  toastText: { ...font.caption, color: colors.card, backgroundColor: colors.text, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderRadius: radius.pill, overflow: "hidden" },
  footer: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: spacing.sm },
  logout: { minHeight: 44, justifyContent: "center" },
  footerText: { ...font.caption, color: colors.textMuted },
});
