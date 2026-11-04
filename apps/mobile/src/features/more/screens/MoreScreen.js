import { Ionicons } from "@expo/vector-icons";
import Constants from "expo-constants";
import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { useAuth } from "@/shared/auth/AuthProvider";
import Screen from "@/shared/components/Screen";
import { colors, font, radius, spacing } from "@/theme";

import { versionText } from "../appInfo";
import HeaderActions from "../components/HeaderActions";
import MenuList from "../components/MenuList";
import ProfileCard from "../components/ProfileCard";
import ShortcutGrid from "../components/ShortcutGrid";
import { itemAction, MENU, menuSections, SHORTCUTS, SOON_MESSAGE } from "../menuItems";

const NOTICE_MS = 2200;

/**
 * 마이 페이지(하단 탭): 오른쪽 위 알림설정·환경설정 버튼(이름 표시, 아직 "준비 중"), 프로필 카드, 카드 하나에 담은 바로가기 4칸, 묶음(가족 및 AI 서비스·계정 및 고객지원)별 카드 목록, 맨 아래 로그아웃·앱 버전 버튼 두 개.
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

  // 가입 요청 건수는 초대 코드·가입 요청을 다루는 "가족 초대" 바로가기에 붙는다
  const shortcuts = SHORTCUTS.map((item) => (item.key === "invite" && pendingCount > 0 ? { ...item, badge: `${pendingCount}` } : item));

  return (
    <View style={styles.root}>
      <Screen
        title="마이페이지"
        right={
          <HeaderActions
            items={[
              { key: "notifications", icon: "notifications-outline", label: "알림설정", onPress: () => showNotice(SOON_MESSAGE) },
              { key: "settings", icon: "settings-outline", label: "환경설정", onPress: () => showNotice(SOON_MESSAGE) },
            ]}
          />
        }
      >
      <ProfileCard user={user} status={status} displayName={displayName} photoUrl={photoUrl} groupName={groupName} roleText={roleText} onEdit={canEdit ? () => router.push("/family-profile") : undefined} onLogin={() => router.push("/login")} onRetry={restore} />
      <ShortcutGrid items={shortcuts} onPressItem={open} />
      <MenuList sections={menuSections(MENU)} onPressItem={open} />
      <View style={styles.footer}>
        {status === "authenticated" ? (
          <Pressable
            disabled={busy}
            style={[styles.footerButton, styles.logout]}
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
            <Ionicons name="log-out-outline" size={20} color={colors.text} />
            <Text style={styles.footerText}>{busy ? "로그아웃 중..." : "로그아웃"}</Text>
          </Pressable>
        ) : null}
        <View style={[styles.footerButton, styles.version]} accessibilityLabel="앱 버전" testID="app-version">
          <Ionicons name="information-circle-outline" size={20} color={colors.textSub} />
          <Text style={styles.versionText}>{`앱 버전 · ${versionText(Constants.expoConfig?.version)}`}</Text>
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
  footer: { flexDirection: "row", gap: spacing.sm, paddingVertical: spacing.sm },
  footerButton: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, minHeight: 48, borderRadius: radius.card },
  logout: { backgroundColor: colors.peachSoft },
  version: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.divider },
  footerText: { ...font.bodyStrong, color: colors.text },
  versionText: { ...font.caption, color: colors.textSub },
});
