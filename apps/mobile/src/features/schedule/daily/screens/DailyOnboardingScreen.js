import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, radius, spacing } from "@/theme";

import ConfirmSheet from "../components/ConfirmSheet";
import { finishOnboarding, listItems } from "../api";
import { RECOMMENDED_NAMES } from "../mock";
import { SELECT_BG, onboardingChoices, onboardingToSave } from "../logic";
import { failureNotice } from "../serverMap";

/**
 * 처음 시작하기: 매일 챙길 일을 골라 서버에 습관으로 만든다. 서버에 습관이 없고 온보딩을 안 마쳤을 때만 온다.
 * 카드는 2열 × 3행(여섯 개)을 행 단위로 그린다. 선택 카드는 외곽선 없이 노란 채움만.
 * 순서: "+ 직접 만들기" → "이대로 시작하기" → "건너뛰기".
 * "직접 만들기"는 고른 항목을 먼저 만들고(이미 있는 이름은 뺀다) 항목 추가 화면으로 간다. 온보딩 완료를 남기므로 돌아와도 온보딩은 다시 뜨지 않는다.
 */
export default function DailyOnboardingScreen() {
  const router = useRouter();
  const choices = useMemo(() => onboardingChoices(RECOMMENDED_NAMES), []);
  const [picked, setPicked] = useState(() => choices.filter((c) => c.preselected).map((c) => c.name));
  const [busy, setBusy] = useState(false);
  const [sheet, setSheet] = useState(null); // 안내 팝업 내용. null 이면 닫힘

  const toggle = (name) => setPicked((prev) => (prev.includes(name) ? prev.filter((x) => x !== name) : [...prev, name]));

  // 고른 항목을 만들고 온보딩 완료를 남긴다. 이미 있는 이름은 다시 넣지 않는다.
  const saveChosen = async (names) => {
    const existing = (await listItems()).map((x) => x.name);
    await finishOnboarding(onboardingToSave(choices, names, existing));
  };

  const fail = (error) => {
    const notice = failureNotice(error);
    setBusy(false);
    setSheet({ title: notice.title, body: notice.body, confirmLabel: "확인" });
  };

  const finish = async (names) => {
    if (busy) return;
    setBusy(true);
    try {
      await saveChosen(names);
      router.replace("/schedule/daily-check");
    } catch (error) {
      fail(error);
    }
  };

  // 직접 만들기: 고른 것을 먼저 만들고, 항목 추가 화면으로 간다(그 화면에서 나오면 데일리 체크 메인).
  const createOwn = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await saveChosen(picked);
      router.replace({ pathname: "/schedule/daily-item", params: { fromOnboarding: "1" } });
    } catch (error) {
      fail(error);
    }
  };

  const rows = [];
  for (let i = 0; i < choices.length; i += 2) rows.push(choices.slice(i, i + 2));

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.top}>
          <Text style={styles.eyebrow}>처음 시작하기</Text>
          <Text style={styles.title} accessibilityRole="header" numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}>
            매일 습관을 골라 주세요
          </Text>
          <Text style={styles.sub}>{"가비가 3가지를 먼저 골라 뒀어요\n언제든지 고치거나 지울 수 있어요"}</Text>
        </View>

        <View style={styles.grid}>
          {rows.map((row, r) => (
            <View key={`row-${r}`} style={styles.row}>
              {row.map((c) => {
                const on = picked.includes(c.name);
                return (
                  <Pressable
                    key={c.name}
                    onPress={() => toggle(c.name)}
                    style={[styles.card, on ? styles.cardOn : styles.cardOff]}
                    accessibilityRole="button"
                    accessibilityLabel={c.name}
                    accessibilityState={{ selected: on }}
                  >
                    <Text style={[styles.cardText, on ? styles.cardTextOn : null]} numberOfLines={1}>
                      {c.name}
                    </Text>
                    {on ? <Ionicons name="checkmark" size={20} color={colors.text} /> : null}
                  </Pressable>
                );
              })}
            </View>
          ))}
        </View>

        <Pressable
          onPress={createOwn}
          style={styles.custom}
          accessibilityRole="button"
          accessibilityLabel="직접 만들기"
          accessibilityState={{ disabled: busy }}
        >
          <Text style={styles.customText}>+ 직접 만들기</Text>
        </Pressable>

        <Pressable
          onPress={() => finish(picked)}
          style={[styles.start, busy && styles.off]}
          accessibilityRole="button"
          accessibilityLabel="이대로 시작하기"
          accessibilityState={{ disabled: busy }}
        >
          <Text style={styles.startText}>이대로 시작하기</Text>
        </Pressable>
        <Pressable
          onPress={() => finish([])}
          style={styles.skip}
          accessibilityRole="button"
          accessibilityLabel="건너뛰기"
          accessibilityState={{ disabled: busy }}
        >
          <Text style={styles.skipText}>건너뛰기</Text>
        </Pressable>
      </ScrollView>
      <ConfirmSheet
        visible={sheet !== null}
        title={sheet?.title ?? ""}
        body={sheet?.body}
        confirmLabel={sheet?.confirmLabel ?? "확인"}
        onConfirm={() => setSheet(null)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingHorizontal: spacing.xl, paddingTop: 40, paddingBottom: spacing.xl, gap: 24 },
  top: { gap: 10 },
  eyebrow: { fontSize: 14, fontWeight: "500", color: colors.accent },
  title: { fontSize: 26, fontWeight: "700", lineHeight: 35, color: colors.text },
  sub: { fontSize: 16, lineHeight: 25, color: colors.textSub },
  // 2열 격자: 행마다 두 칸이 같은 폭(flex 1), 칸 사이 10, 행 사이 10
  grid: { gap: 10 },
  row: { flexDirection: "row", gap: 10 },
  card: {
    flex: 1,
    height: 64,
    borderRadius: 20,
    paddingHorizontal: 16,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  // 선택 카드는 외곽선 없이 노란 채움만(테두리 색을 바탕색과 같게 둬 크기만 맞춘다)
  cardOn: { borderWidth: 1, borderColor: SELECT_BG, backgroundColor: SELECT_BG },
  cardOff: { borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  cardText: { flex: 1, fontSize: 16, fontWeight: "500", color: colors.text },
  cardTextOn: { fontWeight: "700" },
  custom: {
    height: 56,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    alignItems: "center",
    justifyContent: "center",
  },
  customText: { fontSize: 16, fontWeight: "500", color: colors.textSub },
  start: { height: 56, borderRadius: radius.button, backgroundColor: colors.peach, alignItems: "center", justifyContent: "center" },
  startText: { fontSize: 16, fontWeight: "700", color: colors.text },
  skip: { minHeight: 44, alignItems: "center", justifyContent: "center" },
  skipText: { fontSize: 15, color: colors.textSub },
  off: { opacity: 0.55 },
});
