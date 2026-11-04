import { KeyboardAvoidingView, ScrollView, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, spacing } from "@/theme";

import PlayHeader from "./PlayHeader";

/**
 * 놀이터 화면 틀: 상단바 + 스크롤 본문 + (선택) 아래 고정 영역(footer). footerInScroll 이면 footer 를 스크롤 맨 끝에 두고, fixed 면 본문을 스크롤 없이 한 화면에 고정한다.
 * @param {{ title: string, close?: boolean, right?: import("react").ReactNode, footer?: import("react").ReactNode, children: import("react").ReactNode }} props
 */
export default function PlayScreen({ title, titleIcon, close, right, footer, children, onBack, scrollEnabled = true, footerInScroll = false, fixed = false }) {
  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <PlayHeader title={title} titleIcon={titleIcon} close={close} right={right} onBack={onBack} />
      <KeyboardAvoidingView style={styles.flex} behavior="padding">
        {fixed ? (
          // 화면 고정: 본문은 스크롤하지 않고 남은 높이에 맞춘다(안에 있는 목록만 스크롤)
          <View style={[styles.content, styles.fixed]}>{children}</View>
        ) : (
          <ScrollView scrollEnabled={scrollEnabled} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
            {children}
            {footer && footerInScroll ? <View style={styles.footerInline}>{footer}</View> : null}
          </ScrollView>
        )}
        {footer && !footerInScroll ? <View style={[styles.footer, fixed && styles.footerPlain]}>{footer}</View> : null}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  content: { paddingHorizontal: spacing.xl, paddingTop: spacing.xs, paddingBottom: spacing.lg, gap: spacing.lg },
  footerPlain: { borderTopWidth: 0 }, // 고정 화면은 아래 영역과 본문 사이에 줄을 긋지 않는다
  fixed: { flex: 1, overflow: "hidden" },
  footerInline: { gap: spacing.sm, paddingTop: spacing.sm }, // 스크롤 맨 끝에 같이 놓는 안내·보내기 버튼
  footer: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.lg, borderTopWidth: 1, borderTopColor: colors.border, gap: spacing.sm },
});
