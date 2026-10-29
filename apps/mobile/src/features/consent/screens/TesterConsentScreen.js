import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useAuth } from "@/shared/auth/AuthProvider";
import { colors } from "@/theme";

import { saveTesterConsent } from "../api";
import { CONSENT_VERSION, DETAIL_SECTIONS, SUMMARY_LINES } from "../consentCopy";
import { declineForNow } from "../consentState";

/**
 * 로그인 뒤 처음(또는 동의서 버전이 바뀐 뒤) 한 번 보여 주는 AI 테스트 참여 동의 화면.
 * 요약을 먼저 보이고 "자세히 보기"로 전체 안내를 펼친다. 동의하면 버전과 시각을 서버에 저장한다.
 */
export default function TesterConsentScreen() {
  const router = useRouter();
  const { user, refreshUser } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const agree = async () => {
    setBusy(true);
    setError("");
    try {
      await saveTesterConsent(CONSENT_VERSION);
      await refreshUser();
      router.replace("/chat");
    } catch {
      setError("저장하지 못했어요. 잠시 뒤 다시 눌러 주세요.");
      setBusy(false);
    }
  };

  const decline = () => {
    if (user?.id) declineForNow(user.id);
    router.replace("/chat");
  };

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.iconWrap}>
          <Ionicons name="shield-checkmark-outline" size={30} color={colors.text} />
        </View>
        <Text style={styles.title}>AI 테스트 참여 동의</Text>
        <Text style={styles.version}>동의서 {CONSENT_VERSION}</Text>

        <View style={styles.summary}>
          {SUMMARY_LINES.map((line) => (
            <Text key={line} style={styles.summaryLine}>
              {line}
            </Text>
          ))}
        </View>

        <Pressable onPress={() => setOpen((v) => !v)} accessibilityRole="button" accessibilityState={{ expanded: open }} style={styles.more}>
          <Text style={styles.moreText}>{open ? "접기" : "자세히 보기"}</Text>
          <Ionicons name={open ? "chevron-up" : "chevron-down"} size={16} color={colors.accent} />
        </Pressable>

        {open
          ? DETAIL_SECTIONS.map((section) => (
              <View key={section.title} style={styles.section}>
                <Text style={styles.sectionTitle}>{section.title}</Text>
                {section.body.map((line) => (
                  <Text key={line} style={styles.sectionBody}>
                    {line}
                  </Text>
                ))}
              </View>
            ))
          : null}
      </ScrollView>

      <View style={styles.footer}>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <Pressable onPress={agree} disabled={busy} accessibilityRole="button" style={({ pressed }) => [styles.agree, (pressed || busy) && styles.pressed]}>
          {busy ? <ActivityIndicator color={colors.onDark} /> : <Text style={styles.agreeText}>동의하고 시작</Text>}
        </Pressable>
        <Pressable onPress={decline} disabled={busy} accessibilityRole="button" style={styles.decline}>
          <Text style={styles.declineText}>동의하지 않아요</Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { paddingHorizontal: 20, paddingTop: 32, paddingBottom: 16, gap: 12 },
  iconWrap: { width: 64, height: 64, borderRadius: 32, backgroundColor: colors.surfaceStrong, alignItems: "center", justifyContent: "center", alignSelf: "center" },
  title: { fontSize: 20, fontWeight: "700", color: colors.text, textAlign: "center" },
  version: { fontSize: 12, color: colors.textMuted, textAlign: "center" },
  summary: { backgroundColor: colors.surface, borderRadius: 16, padding: 16, gap: 8 },
  summaryLine: { fontSize: 14, lineHeight: 21, color: colors.text },
  more: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4, paddingVertical: 8 },
  moreText: { fontSize: 14, fontWeight: "600", color: colors.accent },
  section: { borderTopWidth: 1, borderTopColor: colors.divider, paddingTop: 12, gap: 4 },
  sectionTitle: { fontSize: 14, fontWeight: "700", color: colors.text },
  sectionBody: { fontSize: 13, lineHeight: 20, color: colors.textSub },
  footer: { paddingHorizontal: 20, paddingTop: 8, paddingBottom: 12, gap: 8 },
  error: { fontSize: 13, color: colors.danger, textAlign: "center" },
  agree: { minHeight: 52, borderRadius: 26, alignItems: "center", justifyContent: "center", backgroundColor: colors.dark },
  pressed: { opacity: 0.85 },
  agreeText: { fontSize: 16, fontWeight: "600", color: colors.onDark },
  decline: { minHeight: 44, alignItems: "center", justifyContent: "center" },
  declineText: { fontSize: 14, color: colors.textMuted },
});
