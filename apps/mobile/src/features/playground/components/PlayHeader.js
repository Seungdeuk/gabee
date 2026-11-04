import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, spacing } from "@/theme";

/** 놀이터 화면 공통 상단바: 뒤로(또는 닫기), 가운데 제목, 오른쪽 자리. */
export default function PlayHeader({ title, titleIcon, close = false, right, fallback = "/play", onBack }) {
  const router = useRouter();
  const back = () => (onBack ? onBack() : router.canGoBack() ? router.back() : router.replace(fallback));
  return (
    <View style={styles.bar}>
      <Pressable onPress={back} style={styles.side} accessibilityRole="button" accessibilityLabel={close ? "닫기" : "뒤로"}>
        <Ionicons name={close ? "close" : "chevron-back"} size={24} color={colors.text} />
      </Pressable>
      <View style={styles.titleRow}>
        {titleIcon}
        <Text style={styles.title} accessibilityRole="header">
          {title}
        </Text>
      </View>
      <View style={styles.side}>{right}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { height: 56, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.sm },
  side: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { ...font.title, color: colors.text },
});
