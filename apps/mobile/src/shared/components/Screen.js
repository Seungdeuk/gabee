import { ScrollView, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, spacing } from "@/theme";

import ScreenHeader from "./ScreenHeader";

/**
 * 헤더 + 스크롤 본문으로 이루어진 기본 화면 틀.
 * @param {{ title: string, right?: import("react").ReactNode, children: import("react").ReactNode }} props
 */
export default function Screen({ title, right, children }) {
  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScreenHeader title={title} right={right} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.body}>{children}</View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    paddingBottom: spacing.xxl,
  },
  body: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.sm,
    gap: spacing.xl,
  },
});
