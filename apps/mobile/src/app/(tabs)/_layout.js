import { Tabs } from "expo-router";

export default function TabLayout() {
  return (
    <Tabs>
      <Tabs.Screen name="index" options={{ title: "AI 비서" }} />
      <Tabs.Screen name="family-chat" options={{ title: "소통" }} />
      <Tabs.Screen name="schedule" options={{ title: "일정" }} />
      <Tabs.Screen name="billing" options={{ title: "가계" }} />
      <Tabs.Screen name="care" options={{ title: "돌봄" }} />
    </Tabs>
  );
}
