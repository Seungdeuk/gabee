import { Ionicons } from "@expo/vector-icons";
import Constants from "expo-constants";
import { useRouter } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import Card from "@/shared/components/Card";
import ListItem from "@/shared/components/ListItem";
import { colors, font } from "@/theme";

import { versionText } from "../appInfo";

/** 앱 관리: 알림함으로 가는 줄과 앱 버전. */
export default function AppManageCard() {
  const router = useRouter();
  return (
    <Card tone="white">
      <Pressable onPress={() => router.push("/notifications")} accessibilityRole="button" accessibilityLabel="알림함 열기">
        <ListItem icon="notifications-outline" tone="orange" title="알림함" subtitle="가족 그룹 가입 요청과 승인 소식" right={<Ionicons name="chevron-forward" size={20} color={colors.textMuted} />} />
      </Pressable>
      <View accessibilityLabel="앱 버전" testID="app-version">
        <ListItem icon="information-circle-outline" tone="gray" title="앱 버전" right={<Text style={styles.value}>{versionText(Constants.expoConfig?.version)}</Text>} />
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  value: { ...font.caption, color: colors.textMuted },
});
