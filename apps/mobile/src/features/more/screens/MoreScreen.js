import Constants from "expo-constants";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { useAuth } from "@/shared/auth/AuthProvider";
import Screen from "@/shared/components/Screen";
import { colors, font, spacing } from "@/theme";

import { versionText } from "../appInfo";
import MenuList from "../components/MenuList";
import ProfileCard from "../components/ProfileCard";
import ShortcutGrid from "../components/ShortcutGrid";
import { itemAction, MENU, SHORTCUTS, SOON_MESSAGE } from "../menuItems";

const NOTICE_MS = 2200;

/**
 * 마이 페이지(하단 탭): 프로필 카드, 바로가기 4칸, 목록 5줄, 맨 아래 로그아웃과 앱 버전.
 * 가족 정보는 다른 기능이라 라우트가 읽어서 넘겨 준다(groupName·roleText·pendingCount). "준비 중" 항목은 안내 문구만 잠깐 보인다.
 * @param {{ groupName?: string | null, roleText?: string | null, pendingCount?: number }} props
 * @returns {import("react").ReactElement}
 */
export default function MoreScreen({ groupName = null, roleText = null, pendingCount = 0 }) {
  const router = useRouter();
  const { status, user, signOut } = useAuth();
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = setTimeout(() => setNotice(""), NOTICE_MS);
    return () => clearTimeout(timer);
  }, [notice]);

  /**
   * 바로가기·목록 항목을 눌렀을 때: 화면이 있으면 이동하고, 아니면 "준비 중" 안내를 보인다.
   * @param {{ route?: string, soon?: boolean }} item
   */
  const open = (item) => {
    const action = itemAction(item);
    if (action.type === "route") router.push(action.path);
    else setNotice(SOON_MESSAGE);
  };

  const menu = MENU.map((item) => (item.key === "family" && pendingCount > 0 ? { ...item, badge: `가입 요청 ${pendingCount}건` } : item));

  return (
    <Screen title="마이페이지">
      <ProfileCard user={user} status={status} groupName={groupName} roleText={roleText} onEdit={() => router.push("/family-profile")} onLogin={() => router.push("/login")} />
      <ShortcutGrid items={SHORTCUTS} onPressItem={open} />
      <MenuList items={menu} onPressItem={open} />
      {notice ? (
        <Text style={styles.notice} accessibilityRole="alert" accessibilityLiveRegion="polite">
          {notice}
        </Text>
      ) : null}
      <View style={styles.footer}>
        {status === "authenticated" ? (
          <Pressable
            disabled={busy}
            accessibilityRole="button"
            accessibilityLabel="로그아웃"
            onPress={async () => {
              setBusy(true);
              await signOut();
              setBusy(false);
              router.replace("/"); // 처음(시작) 화면으로 돌아간다
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
  );
}

const styles = StyleSheet.create({
  notice: { ...font.caption, color: colors.textSub, textAlign: "center" },
  footer: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: spacing.sm },
  footerText: { ...font.caption, color: colors.textMuted },
});
