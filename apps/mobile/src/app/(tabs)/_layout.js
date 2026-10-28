import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import useTotalUnread from "@/features/family-chat/useTotalUnread";
import { unreadBadgeText } from "@/features/family-chat/listUtils";
import { colors, font } from "@/theme";

// 디자인의 하단 탭 5개. 기타(가족 그룹·설정)는 탭이 아니라 상단 ⋮ 메뉴로 들어간다.
const TAB_CONTENT_HEIGHT = 64;

const tabs = [
  { name: "chat", title: "AI 채팅", icon: "chatbubble-ellipses-outline" },
  { name: "family-chat", title: "소통", icon: "people-outline" },
  { name: "schedule", title: "일정", icon: "calendar-outline" },
  { name: "billing", title: "가계", icon: "wallet-outline" },
  { name: "care", title: "돌봄", icon: "heart-outline" },
];

export default function TabLayout() {
  // 소통 탭 아이콘에 모든 방의 안 읽은 메시지 수를 보인다(0 이면 숨김, 99 넘으면 99+)
  const unread = useTotalUnread();
  // 알약(30)+이름 글자가 들어갈 높이를 직접 정하고, 시스템 바 자리만큼 아래를 더한다(기본 높이는 이름이 잘린다)
  const insets = useSafeAreaInsets();
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.text,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarStyle: {
          backgroundColor: colors.background,
          borderTopWidth: 0,
          elevation: 0,
          paddingTop: 6,
          height: TAB_CONTENT_HEIGHT + insets.bottom,
          paddingBottom: insets.bottom + 6,
        },
      }}
    >
      {tabs.map(({ name, title, icon }) => (
        <Tabs.Screen
          key={name}
          name={name}
          options={{
            title,
            tabBarBadge: name === "family-chat" && unread > 0 ? unreadBadgeText(unread) : undefined,
            tabBarBadgeStyle: styles.badge,
            tabBarLabel: ({ focused, color }) => (
              <Text style={[styles.label, { color }, focused && styles.labelActive]}>{title}</Text>
            ),
            // 선택된 탭은 아이콘 뒤에 옅은 꿀색 알약이 깔린다
            tabBarIcon: ({ focused, color }) => (
              <View style={[styles.pill, focused && styles.pillActive]}>
                <Ionicons name={icon} size={22} color={color} />
              </View>
            ),
          }}
        />
      ))}
    </Tabs>
  );
}

const styles = StyleSheet.create({
  label: { ...font.tab },
  labelActive: { fontWeight: "700" },
  pill: {
    width: 52,
    height: 30,
    borderRadius: 15,
    alignItems: "center",
    justifyContent: "center",
  },
  pillActive: { backgroundColor: colors.surfaceStrong },
  badge: { backgroundColor: colors.peach, color: colors.text, ...font.tab },
});
