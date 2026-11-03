import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import { colors, font, spacing } from "@/theme";

import SegmentedControl from "../../components/SegmentedControl";
import { listCheers, toggleCheerThanked } from "../api";
import { cheerKindLabel, cheerTone, formatClock, groupCheersByDate } from "../logic";
import { useDailyScope } from "../scope";
import { todayKey } from "../../utils/date";

const KIND_ICON = { love: "heart", best: "thumbs-up", well: "star" };

/**
 * 응원 모아보기: 받은·보낸 응원을 날짜별로 본다(최근 날짜 먼저). 카드 전체는 응원 종류별 색(cheerTone)이다.
 * 받은 응원은 "고마워 보내기"(종류 진한색 채움, 흰 글자)와 "고마워 보냄"(옅은 바탕, 종류 글자색)을 같은 크기 칩으로 보여 준다.
 */
export default function DailyCheerHistoryScreen() {
  const router = useRouter();
  const scope = useDailyScope();
  const today = todayKey();
  const [tab, setTab] = useState("received");
  const [cheers, setCheers] = useState([]);

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      listCheers(scope).then((list) => alive && setCheers(list));
      return () => {
        alive = false;
      };
    }, [scope]),
  );

  const groups = useMemo(
    () => groupCheersByDate(cheers.filter((c) => c.direction === tab), today),
    [cheers, tab, today],
  );
  const receivedCount = cheers.filter((c) => c.direction === "received").length;
  const sentCount = cheers.filter((c) => c.direction === "sent").length;

  const thank = async (id) => {
    await toggleCheerThanked(scope, id);
    setCheers(await listCheers(scope));
  };

  const back = () => (router.canGoBack() ? router.back() : router.replace("/schedule/daily-check"));

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.head}>
        <IconButton name="chevron-back" label="뒤로" onPress={back} />
        <Text style={styles.title} accessibilityRole="header">
          응원 모아보기
        </Text>
      </View>

      <View style={styles.segment}>
        <SegmentedControl
          options={[
            { key: "received", label: `받은 응원 ${receivedCount}` },
            { key: "sent", label: `보낸 응원 ${sentCount}` },
          ]}
          value={tab}
          onChange={setTab}
          full
        />
      </View>

      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {groups.length ? (
          groups.map((group) => (
            <View key={group.date} style={styles.group}>
              <Text style={styles.groupLabel}>{group.label}</Text>
              {group.items.map((c) => {
                const tone = cheerTone(c.kind);
                const who = c.direction === "received" ? c.fromName : c.toName;
                return (
                  <View key={c.id} style={[styles.card, { backgroundColor: tone.bg, borderColor: tone.border }]}>
                    <View style={styles.row}>
                      <View style={styles.titleRow}>
                        <Ionicons name={KIND_ICON[c.kind] ?? "heart"} size={18} color={tone.icon} />
                        <Text style={styles.name}>{`${who} · ${cheerKindLabel(c.kind)}`}</Text>
                      </View>
                      <Text style={styles.time}>{formatClock(c.time)}</Text>
                    </View>
                    <Text style={styles.quote}>{`“${c.text}”`}</Text>
                    {c.direction === "received" ? (
                      c.thanked ? (
                        <View style={[styles.chip, styles.chipDone]}>
                          <Text style={[styles.chipText, { color: tone.text }]}>고마워 보냄</Text>
                        </View>
                      ) : (
                        <Pressable
                          onPress={() => thank(c.id)}
                          style={[styles.chip, { backgroundColor: tone.strong }]}
                          accessibilityRole="button"
                          accessibilityLabel={`${c.fromName} 응원에 고마워 보내기`}
                        >
                          <Text style={[styles.chipText, styles.chipTextWhite]}>고마워 보내기</Text>
                        </Pressable>
                      )
                    ) : (
                      <View style={styles.sentRow}>
                        <Ionicons name="paper-plane-outline" size={14} color={colors.textSub} />
                        <Text style={styles.sentText}>{c.groupChat ? "가족 대화방에도 남김 표시" : "나만 보냄"}</Text>
                      </View>
                    )}
                  </View>
                );
              })}
            </View>
          ))
        ) : (
          <Text style={styles.empty}>{tab === "received" ? "받은 응원이 아직 없어요" : "보낸 응원이 아직 없어요"}</Text>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  head: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.md, paddingTop: spacing.sm, gap: 4 },
  title: { ...font.title, color: colors.text },
  segment: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.sm },
  content: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxl, gap: spacing.lg },
  group: { gap: 8 },
  groupLabel: { fontSize: 13, fontWeight: "700", color: colors.textSub },
  // 카드: 종류 색 바탕과 테두리, 둥글기 16, 패딩 14/16
  card: { borderRadius: 16, borderWidth: 1, paddingVertical: 14, paddingHorizontal: 16, gap: 8 },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 6, flexShrink: 1 },
  name: { fontSize: 15, fontWeight: "700", color: colors.text },
  time: { fontSize: 13, color: colors.textSub },
  quote: { fontSize: 16, lineHeight: 24, color: colors.text },
  // "고마워 보냄"과 "고마워 보내기"는 같은 크기·모양 칩(패딩 4/10, 둥근 pill, 글자 13 bold)
  chip: { alignSelf: "flex-start", paddingVertical: 4, paddingHorizontal: 10, borderRadius: 999 },
  chipDone: { backgroundColor: colors.background },
  chipText: { fontSize: 13, fontWeight: "700" },
  chipTextWhite: { color: "#FFFFFF" },
  sentRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  sentText: { fontSize: 13, color: colors.textSub },
  empty: { ...font.caption, color: colors.textSub, textAlign: "center", paddingVertical: spacing.xl },
});
