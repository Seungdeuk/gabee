import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, spacing } from "@/theme";

/** 놀이터 화면 공통 상단바: 뒤로(또는 닫기), 가운데 제목, 오른쪽 자리. */
export default function PlayHeader({ title, titleIcon, close = false, right, fallback = "/play", onBack, compact = false, wide = false }) {
  const router = useRouter();
  const back = () => (onBack ? onBack() : router.canGoBack() ? router.back() : router.replace(fallback));
  return (
    <View style={[styles.bar, compact && styles.barSm]}>
      <Pressable onPress={back} style={[styles.side, wide && styles.sideLeftWide]} accessibilityRole="button" accessibilityLabel={close ? "닫기" : "뒤로"}>
        <Ionicons name={close ? "close" : "chevron-back"} size={24} color={colors.text} />
      </Pressable>
      <View style={styles.titleRow}>
        {titleIcon}
        <Text style={styles.title} accessibilityRole="header">
          {title}
        </Text>
      </View>
      <View style={[styles.side, wide && styles.sideRightWide]}>{right}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  barSm: { height: 40 }, // 키보드가 올라왔을 때
  bar: { height: 56, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.sm },
  side: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  sideLeftWide: { width: 88, alignItems: "flex-start" }, // 오른쪽에 아이콘이 둘일 때 제목이 가운데에 오도록 양쪽 폭을 같게 한다
  sideRightWide: { width: 88, flexDirection: "row", justifyContent: "flex-end" },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { ...font.title, color: colors.text },
});
