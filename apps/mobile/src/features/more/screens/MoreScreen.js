import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { useAuth } from "@/shared/auth/AuthProvider";
import Screen from "@/shared/components/Screen";
import { colors, font, radius, spacing } from "@/theme";

import HeaderActions from "../components/HeaderActions";
import MenuList from "../components/MenuList";
import ProfileCard from "../components/ProfileCard";
import ShortcutGrid from "../components/ShortcutGrid";
import { itemAction, MENU, menuSections, SHORTCUTS, SOON_MESSAGE } from "../menuItems";

const NOTICE_MS = 2200;

/**
 * 마이 페이지(하단 탭): 오른쪽 위 톱니 환경설정 아이콘(환경설정 화면 `/settings` 로 이동), 프로필 카드, 카드 하나에 담은 바로가기 4칸, 묶음(가족 및 AI 서비스·계정 및 고객지원)별 카드 목록. 그 밖의 설정은 환경설정 화면에 있다.
 * 가족 정보는 다른 기능이라 라우트가 읽어서 넘겨 준다(groupName·roleText·pendingCount). "준비 중" 항목은 안내 문구만 잠깐 보인다.
 * displayName·photoUrl 은 가족 안에서 쓰는 내 이름과 사진이고(없으면 계정 이름·사진), canEdit 이 true 일 때만 "내 정보 수정"이 보인다.
 * bell 은 오른쪽 위 맨 끝 알림 종이다(라우트에서 조립한다. 환경설정 아이콘은 그 왼쪽에 있다).
 * @param {{ displayName?: string | null, photoUrl?: string | null, groupName?: string | null, roleText?: string | null, canEdit?: boolean, pendingCount?: number, bell?: import("react").ReactNode }} props
 * @returns {import("react").ReactElement}
 */
export default function MoreScreen({ displayName = null, photoUrl = null, groupName = null, roleText = null, canEdit = false, pendingCount = 0, bell = null }) {
  const router = useRouter();
  const { status, user, restore } = useAuth();
  const [notice, setNotice] = useState("");
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
          <View style={styles.right}>
            <HeaderActions
              items={[
                { key: "settings", icon: "settings-outline", label: "환경설정", onPress: () => router.push("/settings") },
              ]}
            />
            {bell}
          </View>
        }
      >
      <ProfileCard user={user} status={status} displayName={displayName} photoUrl={photoUrl} groupName={groupName} roleText={roleText} onEdit={canEdit ? () => router.push("/family-profile") : undefined} onLogin={() => router.push("/login")} onRetry={restore} />
      <ShortcutGrid items={shortcuts} onPressItem={open} />
      <MenuList sections={menuSections(MENU)} onPressItem={open} />
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
  // 이름 붙은 버튼(키가 큼)과 종이 같은 윗선에 놓이도록 위쪽 정렬한다. 간격은 HeaderActions 줄과 같다
  right: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  toast: { position: "absolute", left: spacing.xl, right: spacing.xl, bottom: spacing.xxl, alignItems: "center" },
  toastText: { ...font.caption, color: colors.card, backgroundColor: colors.text, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderRadius: radius.pill, overflow: "hidden" },
});
