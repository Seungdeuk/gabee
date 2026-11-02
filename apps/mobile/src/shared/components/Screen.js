import { KeyboardAvoidingView, ScrollView, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, spacing } from "@/theme";

import PageHeader from "./PageHeader";

/**
 * 큰 제목 + 스크롤 본문으로 이루어진 탭 화면 틀.
 * `pinned` 를 주면 제목 아래에 고정되는 영역(스크롤해도 화면 위에 남는다)이 생긴다.
 * settings 를 주면 제목 줄 오른쪽 맨 끝에 설정 버튼이 붙는다(탭 화면용).
 * 아래쪽은 안드로이드 내비게이션 바(탭 화면에서는 탭 바가 이미 막아 0)를 피하고, 키보드가 올라오면 본문이 줄어들어 스크롤로 아래 입력칸까지 볼 수 있다.
 * centered 를 주면 제목 줄을 가운데 정렬한다.
 * @param {{ title: string, subtitle?: string, left?: import("react").ReactNode, right?: import("react").ReactNode, pinned?: import("react").ReactNode, settings?: boolean, centered?: boolean, children: import("react").ReactNode }} props
 */
export default function Screen({ title, subtitle, left, right, pinned, settings = false, centered = false, children }) {
  const header = <PageHeader title={title} subtitle={subtitle} left={left} right={right} settings={settings} centered={centered} />;
  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <KeyboardAvoidingView style={styles.flex} behavior="padding">
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
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
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
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
