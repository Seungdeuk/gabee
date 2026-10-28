import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import MoreButtons from "../components/MoreButtons";
import SectionHeader from "../components/SectionHeader";
import SegmentedControl from "../components/SegmentedControl";
import StatusBadge from "../components/StatusBadge";
import { ME_ID, members } from "../mock";
import { receivedStatus, sentStatus } from "../model";
import { useRequests } from "../requests";
import { pageUpcoming } from "../upcoming";
import { formatDateLong, todayKey } from "../utils/date";

const TAB_OPTIONS = [
  { key: "received", label: "받은" },
  { key: "sent", label: "보낸" },
];

/** 지난 구역에서 먼저 보이는 개수. 나머지는 "이전 기록 더 보기". */
const PAST_PREVIEW = 3;


const nameOf = (id) => members.find((m) => m.id === id)?.name ?? "";

/**
 * 주고 받은(전 현황): 같이의 메인 화면. [받은 | 보낸] 두 탭(처음엔 받은), 구역은 "답을 기다려요" / "함께해요"(수락됐고 아직 날짜가 안 지난 것) / "지난"(숫자 없이 최근 몇 개 + 이전 기록 더 보기).
 * 구역 제목을 누르면 각각 접고 편다: 답을 기다려요는 전부 보이고, 함께해요는 앞으로 한 달치 중 5개(마지막과 같은 날짜는 모두)만 보인 뒤 "더보기"를 누를 때마다 5개씩 펴며, 지난은 기본 접혀 있다.
 * 받은 탭의 카드는 받기 화면으로, 보낸 탭의 카드는 보낸 것 상세로 간다. 오른쪽 위 "같이하기"로 새로 보내고, ‹는 일정 메인으로 돌아간다.
 * 보내기에서 돌아오면 tab=sent 로 열려 방금 보낸 것이 보인다.
 */
export default function TogetherStatusScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const requests = useRequests();
  const [tab, setTab] = useState(params.tab === "sent" ? "sent" : "received");
  const [morePast, setMorePast] = useState(false);
  const [togetherPages, setTogetherPages] = useState(1);
  const [fold, setFold] = useState({ waiting: false, together: false, past: true });
  const toggleFold = (key) => setFold((f) => ({ ...f, [key]: !f[key] }));

  // 보내기 화면에서 돌아올 때마다(at 이 바뀔 때) 보낸 탭으로 옮긴다.
  useEffect(() => {
    if (params.tab === "sent" || params.tab === "received") setTab(params.tab);
  }, [params.tab, params.at]);

  const today = todayKey();
  const isSent = tab === "sent";
  const mine = requests
    .filter((r) => (isSent ? r.fromId === ME_ID : r.fromId !== ME_ID && r.toIds.includes(ME_ID) && !r.cancelled))
    .map((r) => ({ request: r, status: isSent ? sentStatus(r) : receivedStatus(r, ME_ID) }));
  const waiting = mine.filter(({ status }) => status === "pending");
  // 답했고(수락이든 어렵다든) 아직 날짜가 지나지 않은 것은 함께해요에 둔다. 아직 바꿀 수 있기 때문이다.
  // 지난은 날짜가 지난 것과 보낸 사람이 취소한 것이다.
  const answered = ({ status }) => status === "accepted" || status === "declined";
  const together = mine
    .filter((m) => answered(m) && m.request.date >= today)
    .sort((a, b) => a.request.date.localeCompare(b.request.date));
  const past = mine
    .filter((m) => m.status === "cancelled" || (answered(m) && m.request.date < today))
    .sort((a, b) => b.request.date.localeCompare(a.request.date));
  const pastShown = morePast ? past : past.slice(0, PAST_PREVIEW);
  const togetherPage = pageUpcoming(together, today, togetherPages, { dateOf: (m) => m.request.date });

  // 일정 메인에서 들어왔으므로 ‹는 일정 메인으로 간다.
  const leave = () => router.dismissTo("/(tabs)/schedule");
  const open = (id) => router.push({ pathname: isSent ? "/schedule/together-detail" : "/schedule/together-receive", params: { id } });

  const card = ({ request: r, status }) => (
    <Pressable key={r.id} onPress={() => open(r.id)} style={styles.card} accessibilityRole="button">
      <View style={styles.cardMain}>
        <Text style={styles.cardTitle}>{r.title}</Text>
        <Text style={styles.cardSub}>
          {`${isSent ? r.toIds.map(nameOf).join(", ") : nameOf(r.fromId)} · ${formatDateLong(r.date)}${r.startTime ? ` ${r.startTime}` : ""}`}
        </Text>
      </View>
      <StatusBadge status={status} />
    </Pressable>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.body}>
          <View style={styles.top}>
            <View style={styles.titleBox}>
              <IconButton name="chevron-back" label="뒤로" onPress={leave} />
              <Text style={styles.title} accessibilityRole="header">
                주고 받은
              </Text>
            </View>
            <Pressable
              onPress={() => router.push({ pathname: "/schedule/together", params: { from: "status" } })}
              style={styles.send}
              accessibilityRole="button"
            >
              <Text style={styles.sendText}>같이하기</Text>
            </Pressable>
          </View>

          <SegmentedControl options={TAB_OPTIONS} value={tab} onChange={setTab} full dark />

          {mine.length === 0 ? (
            <Text style={styles.empty}>{isSent ? "보낸 게 아직 없어요" : "받은 게 아직 없어요"}</Text>
          ) : (
            <>
              <View style={styles.section}>
                <SectionHeader
                  title="답을 기다려요"
                  count={waiting.length > 0 ? `${waiting.length}개` : undefined}
                  collapsed={fold.waiting}
                  onToggle={() => toggleFold("waiting")}
                />
                {fold.waiting ? null : waiting.length === 0 ? <Text style={styles.empty}>기다리는 게 없어요</Text> : waiting.map(card)}
              </View>

              {together.length > 0 ? (
                <View style={styles.section}>
                  <SectionHeader
                    title="함께해요"
                    count={`${together.length}개`}
                    collapsed={fold.together}
                    onToggle={() => toggleFold("together")}
                  />
                  {fold.together ? null : (
                    <>
                      {togetherPage.shown.length === 0 ? <Text style={styles.empty}>앞으로 한 달 안에는 함께할 일이 없어요</Text> : togetherPage.shown.map(card)}
                      <MoreButtons
                        remaining={togetherPage.remaining}
                        expanded={togetherPages > 1}
                        onMore={() => setTogetherPages((n) => n + 1)}
                        onFold={() => setTogetherPages(1)}
                      />
                    </>
                  )}
                </View>
              ) : null}

              {past.length > 0 ? (
                <View style={styles.section}>
                  <SectionHeader title="지난" collapsed={fold.past} onToggle={() => toggleFold("past")} />
                  {fold.past ? null : (
                    <>
                      {pastShown.map(card)}
                      {!morePast && past.length > PAST_PREVIEW ? (
                        <Pressable onPress={() => setMorePast(true)} style={styles.more} accessibilityRole="button">
                          <Text style={styles.moreText}>이전 기록 더 보기</Text>
                        </Pressable>
                      ) : null}
                    </>
                  )}
                </View>
              ) : null}
            </>
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingBottom: spacing.xxl },
  body: { paddingHorizontal: spacing.xxl, paddingTop: spacing.xl, gap: 18 },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  titleBox: { flexDirection: "row", alignItems: "center", flexShrink: 1, marginLeft: -spacing.sm },
  send: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.pill, backgroundColor: colors.peach },
  sendText: { fontSize: 14, fontWeight: "700", color: colors.text },
  title: { ...font.page, color: colors.text },
  section: { gap: 6 },
  empty: { ...font.body, color: colors.textMuted },
  card: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.card,
  },
  cardMain: { flex: 1, gap: 2 },
  cardTitle: { fontSize: 16, color: colors.text },
  cardSub: { ...font.caption, color: colors.textMuted },
  more: {
    alignItems: "center",
    paddingVertical: spacing.md,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.button,
  },
  moreText: { fontSize: 14, fontWeight: "500", color: colors.textMuted },
});
