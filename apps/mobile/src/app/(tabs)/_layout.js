import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

// 디자인의 하단 탭 5개. 기타(가족 그룹·설정)는 탭이 아니라 상단 ⋮ 메뉴로 들어간다.
const tabs = [
  { name: "chat", title: "AI 채팅", icon: "chatbubble-ellipses-outline" },
  { name: "family-chat", title: "소통", icon: "people-outline" },
  { name: "schedule", title: "일정", icon: "calendar-outline" },
  { name: "billing", title: "가계", icon: "wallet-outline" },
  { name: "care", title: "돌봄", icon: "heart-outline" },
];

export default function TabLayout() {
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
        },
      }}
    >
      {tabs.map(({ name, title, icon }) => (
        <Tabs.Screen
          key={name}
          name={name}
          options={{
            title,
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
});
