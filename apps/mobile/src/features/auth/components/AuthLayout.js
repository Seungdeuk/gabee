import { useRouter } from "expo-router";
import { KeyboardAvoidingView, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import Logo from "@/shared/components/Logo";
import { colors, font, spacing } from "@/theme";

/**
 * 로그인·가입 계열 화면의 틀: 뒤로 가기, 로고, 제목, 키보드가 올라와도 가려지지 않는 스크롤 본문.
 * @param {{ title: string, subtitle?: string, back?: boolean, children: import("react").ReactNode }} props
 */
export default function AuthLayout({ title, subtitle, back = true, children }) {
  const router = useRouter();
  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView style={styles.flex} behavior="padding">
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <View style={styles.top}>
            {back ? (
              <IconButton
                name="chevron-back"
                label="뒤로"
                onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))}
              />
            ) : null}
            <Logo size={22} />
          </View>
          <Text style={styles.title} accessibilityRole="header">
            {title}
          </Text>
          {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
          <View style={styles.body}>{children}</View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  content: { padding: spacing.xl, paddingBottom: spacing.xxl * 2, gap: spacing.md },
  top: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginLeft: -10, marginBottom: spacing.md },
  title: { ...font.page, color: colors.text },
  subtitle: { ...font.body, color: colors.textSub },
  body: { marginTop: spacing.md, gap: spacing.lg },
});
