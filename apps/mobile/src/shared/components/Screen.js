import { ScrollView, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, spacing } from "@/theme";

import PageHeader from "./PageHeader";

/**
 * 큰 제목 + 스크롤 본문으로 이루어진 탭 화면 틀.
 * @param {{ title: string, subtitle?: string, left?: import("react").ReactNode, right?: import("react").ReactNode, children: import("react").ReactNode }} props
 */
export default function Screen({ title, subtitle, left, right, children }) {
  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.body}>
          <PageHeader title={title} subtitle={subtitle} left={left} right={right} />
          {children}
        </View>
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
    paddingTop: spacing.xl,
    gap: spacing.xl,
  },
});
