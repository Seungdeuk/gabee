import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Pressable, Share, StyleSheet, Text, View } from "react-native";

import { colors, font, fonts, radius } from "@/theme";

import PlayIcon from "../components/PlayIcon";
import PlayScreen from "../components/PlayScreen";
import { GAME_LIST } from "../games";
import { BEST, RANKING_BY } from "../mock";

const TABS = [
  { key: "week", label: "이번 주" },
  { key: "month", label: "이번 달" },
  { key: "all", label: "전체" },
];
// 와이어프레임 3번: 1위는 노랑, 나는 얇은 테두리, 나머지는 흰색 카드
const AVATAR = { mom: [colors.peach, colors.text], me: ["#553B29", "#FFFCF7"], dad: [colors.successSoft, "#2F4A3B"], daughter: ["#F3ECE4", colors.text], son: [colors.peachSoft, colors.text] };

/** 순위: 이번 주/이번 달/전체. 줄을 누르면 점수가 어디서 왔는지 내역이 펼쳐진다. 게임별 최고 기록, 점수 받는 법(3줄). */
export default function PlayRankingScreen() {
  const [tab, setTab] = useState("week");
  const [open, setOpen] = useState(null);

  const rows = RANKING_BY[tab];
  const changeTab = (k) => {
    setTab(k);
    setOpen(null);
  };
  return (
    <PlayScreen title="순위">
      <View style={styles.tabs}>
        {TABS.map((t) => (
          <Pressable key={t.key} onPress={() => changeTab(t.key)} accessibilityRole="tab" accessibilityState={{ selected: tab === t.key }} style={[styles.tab, tab === t.key && styles.tabOn]}>
            <Text style={[styles.tabText, tab === t.key && styles.tabTextOn]}>{t.label}</Text>
          </Pressable>
        ))}
      </View>
      <View style={styles.list}>
        {rows.map((r, i) => {
          const [bg, fg] = AVATAR[r.id] ?? AVATAR.daughter;
          const idle = r.score === 0;
          const isOpen = open === r.id && !idle;
          return (
            <View key={r.id} style={[styles.card, i === 0 && styles.first, r.id === "me" && styles.me]}>
              <Pressable onPress={() => !idle && setOpen(isOpen ? null : r.id)} disabled={idle} accessibilityRole="button" accessibilityState={{ expanded: isOpen }} accessibilityLabel={`${i + 1}위 ${r.name} ${r.score}점. 누르면 점수 내역`} style={styles.row}>
                <Text style={[styles.no, i === 0 && styles.noFirst]}>{i + 1}</Text>
                <View style={[styles.avatar, { backgroundColor: bg }]}>
                  <Text style={[styles.avatarText, { color: fg }]}>{r.name.slice(0, 1)}</Text>
                </View>
                <View style={styles.rowText}>
                  <Text style={styles.name}>{r.name}</Text>
                </View>
                {idle ? (
                  <Pressable onPress={() => Share.share({ message: `${r.name}야, 가족 놀이터에서 같이 놀자!` }).catch(() => {})} accessibilityRole="button" accessibilityLabel={`${r.name} 초대하기`} hitSlop={8}>
                    <Text style={styles.invite}>초대하기</Text>
                  </Pressable>
                ) : (
                  <>
                    <Text style={styles.score}>{r.score.toLocaleString("ko-KR")}점</Text>
                    <Ionicons name={isOpen ? "chevron-up" : "chevron-down"} size={16} color={colors.textSub} />
                  </>
                )}
              </Pressable>
              {isOpen ? (
                <View style={styles.detail}>
                  <Detail label="가족 골든벨" count={r.n[0]} points={r.quiz} />
                  <Detail label="이게 뭐게" count={r.n[1]} points={r.draw} />
                  <Detail label="찰칵! 탐정단" count={r.n[2]} points={r.photo} />
                  <Detail label="문장 폭탄" count={r.n[3]} points={r.bomb} />
                  <Detail label="참여 · 문제 내기" points={r.etc} />
                </View>
              ) : null}
            </View>
          );
        })}
      </View>
      <Text style={styles.h2}>게임별 최고 기록</Text>
      <View style={styles.grid}>
        {GAME_LIST.map((g) => {
          const b = BEST[tab][g.key];
          return (
            <View key={g.key} style={styles.best} accessible accessibilityLabel={`${g.name} 최고 기록 ${b.who} ${b.value}`}>
              <View style={styles.bestIcon}>
                <PlayIcon icon={g.icon} size={26} />
              </View>
              <Text style={styles.bestName}>{g.name}</Text>
              <Text style={styles.bestLine} numberOfLines={1}>
                <Text style={styles.bestWho}>{b.who} </Text>
                <Text style={styles.bestValue}>{b.value}</Text>
              </Text>
            </View>
          );
        })}
      </View>
      <View style={styles.rule}>
        <Text style={styles.ruleTitle}>점수 받는 법</Text>
        <Text style={styles.ruleText}>{"문제 내면 +20 / 참여하면 +10\n(문제 출제는 하루 3개까지, 가족이 풀면 받아요)\n정답 맞추면 +20 / 폭탄 우승은 +30\n매주 월요일에 이번 주 순위가 새로 시작돼요"}</Text>
      </View>
    </PlayScreen>
  );
}

function Detail({ label, count, points }) {
  return (
    <View style={styles.detailRow}>
      <Text style={styles.detailLabel}>{count === undefined ? label : `${label} ${count}회`}</Text>
      <Text style={styles.detailPoints}>+{points}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  tabs: { flexDirection: "row", padding: 4, borderRadius: 14, backgroundColor: "#F3ECE4" },
  tab: { flex: 1, height: 40, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  tabOn: { backgroundColor: colors.card },
  tabText: { fontSize: 15, fontFamily: fonts.regular, color: colors.textSub },
  tabTextOn: { fontFamily: fonts.bold, color: colors.text },
  list: { gap: 8 },
  card: { borderRadius: 16, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  first: { backgroundColor: colors.surfaceStrong, borderColor: colors.surfaceStrong },
  me: { borderColor: "#D9C7B4" },
  row: { minHeight: 64, paddingHorizontal: 16, flexDirection: "row", alignItems: "center", gap: 12 },
  no: { width: 20, fontSize: 18, fontFamily: fonts.bold, color: colors.textSub },
  noFirst: { color: "#8A5A2B" },
  avatar: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  avatarText: { fontSize: 15, fontFamily: fonts.bold },
  rowText: { flex: 1 },
  name: { fontSize: 16, fontFamily: fonts.bold, color: colors.text },
  sub: { ...font.caption, color: colors.textSub },
  score: { fontSize: 17, fontFamily: fonts.bold, color: colors.text },
  invite: { fontSize: 14, fontFamily: fonts.bold, color: "#8A5A2B", paddingVertical: 8, marginRight: 28 }, // 점수 오른쪽 화살표(16) + 간격(12)만큼 비워 점수와 오른쪽 끝을 맞춘다
  detail: { paddingHorizontal: 16, paddingBottom: 12, paddingTop: 2 },
  detailRow: { flexDirection: "row", justifyContent: "space-between", paddingLeft: 48 },
  detailLabel: { fontSize: 13, fontFamily: fonts.regular, color: colors.textSub },
  detailPoints: { fontSize: 13, fontFamily: fonts.bold, color: colors.text },
  h2: { ...font.cardTitle, color: colors.text },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  best: { width: "48%", flexGrow: 1, padding: 14, borderRadius: radius.lg, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, gap: 4 },
  bestIcon: { width: 48, height: 48, borderRadius: 14, backgroundColor: colors.surfaceStrong, alignItems: "center", justifyContent: "center", marginBottom: 4 },
  bestName: { ...font.bodyStrong, color: colors.text },
  bestLine: { ...font.caption },
  bestWho: { fontFamily: fonts.bold, color: colors.text },
  bestValue: { fontFamily: fonts.bold, color: "#8A5A2B" },
  rule: { padding: 16, borderRadius: radius.lg, backgroundColor: "#F7F0E6", gap: 6 },
  ruleTitle: { fontSize: 14, fontFamily: fonts.bold, color: colors.text },
  ruleText: { fontSize: 13, lineHeight: 21, fontFamily: fonts.regular, color: colors.textSub },
});
