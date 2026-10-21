import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router";

import { colors, font } from "@/theme";

const tabs = [
  { name: "index", title: "AI 비서", icon: "chatbubble-ellipses" },
  { name: "family-chat", title: "소통", icon: "people" },
  { name: "schedule", title: "일정", icon: "calendar" },
  { name: "billing", title: "가계", icon: "wallet" },
  { name: "care", title: "돌봄", icon: "heart" },
  { name: "more", title: "기타", icon: "ellipsis-horizontal-circle" },
];

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.text,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarLabelStyle: { ...font.tab },
        tabBarStyle: {
          backgroundColor: colors.background,
          borderTopColor: colors.surfaceStrong,
        },
      }}
    >
      {tabs.map(({ name, title, icon }) => (
        <Tabs.Screen
          key={name}
          name={name}
          options={{
            title,
            tabBarIcon: ({ color, size, focused }) => (
              <Ionicons name={focused ? icon : `${icon}-outline`} size={size} color={color} />
            ),
          }}
        />
      ))}
    </Tabs>
  );
}
