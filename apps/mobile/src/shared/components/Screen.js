import { ScrollView, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, spacing } from "@/theme";

import PageHeader from "./PageHeader";

/**
 * 큰 제목 + 스크롤 본문으로 이루어진 탭 화면 틀.
 * `pinned` 를 주면 제목 아래에 고정되는 영역(스크롤해도 화면 위에 남는다)이 생긴다.
 * settings 를 주면 제목 줄 오른쪽 맨 끝에 설정 버튼이 붙는다(탭 화면용).
 * @param {{ title: string, subtitle?: string, left?: import("react").ReactNode, right?: import("react").ReactNode, pinned?: import("react").ReactNode, settings?: boolean, children: import("react").ReactNode }} props
 */
export default function Screen({ title, subtitle, left, right, pinned, settings = false, children }) {
  const header = <PageHeader title={title} subtitle={subtitle} left={left} right={right} settings={settings} />;
  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
        stickyHeaderIndices={pinned ? [1] : undefined}
      >
        {pinned ? (
          [
            // stickyHeaderIndices 는 ScrollView 의 바로 아래 자식에만 적용된다
            <View key="header" style={styles.headerBlock}>
              {header}
            </View>,
            <View key="pinned" style={styles.pinned}>
              {pinned}
            </View>,
            <View key="body" style={styles.bodyRest}>
              {children}
            </View>,
          ]
        ) : (
          <View style={styles.body}>
            {header}
            {children}
          </View>
        )}
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
  headerBlock: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.xl,
    paddingBottom: spacing.md,
  },
  pinned: {
    backgroundColor: colors.background,
  },
  bodyRest: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.lg,
    gap: spacing.xl,
  },
});
