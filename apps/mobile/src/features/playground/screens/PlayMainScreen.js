import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useEffect } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, fonts, radius } from "@/theme";

import PlayIcon from "../components/PlayIcon";
import PlayScreen from "../components/PlayScreen";
import TurnRow from "../components/TurnRow";
import { GAME_LIST } from "../games";
import { useMakeLeft, usePlayBoard, usePlayRanking } from "../hooks";
import { reopenRooms } from "../mock";

const SHOWN = 3; // 홈 "내 차례"는 3개까지. 나머지는 + 로 현황판에서 본다

/** 가족 놀이터 메인: 내 차례(최대 3개), 새 게임 시작하기(2×2), 이번 주 순위 요약. */
export default function PlayMainScreen() {
  const router = useRouter();
  useEffect(() => reopenRooms(), []); // 시안: 닫았던 폭탄 방을 다시 열어 둔다
  const board = usePlayBoard();
  const todo = board.data?.todo ?? [];
  const top = (usePlayRanking("week").data ?? []).slice(0, 3);
  const makeLeft = useMakeLeft(); // 오늘 문제 내기 +20점을 더 받을 수 있는 횟수(불러오기 전·실패하면 null)
  return (
    <PlayScreen
      title="가족 놀이터"
      right={
        <Pressable onPress={() => router.push("/play/ranking")} accessibilityRole="button" accessibilityLabel="순위 보기" hitSlop={8}>
          <Ionicons name="trophy-outline" size={22} color={colors.text} />
        </Pressable>
      }
    >
      <View style={styles.section}>
        <View style={styles.turnHead}>
          <Text style={styles.h2}>내 차례예요</Text>
          <View style={styles.turnRight}>
            <Text style={styles.count}>{todo.length}개</Text>
            <Pressable onPress={() => router.push("/play/board")} accessibilityRole="button" accessibilityLabel="받은·보낸 현황 보기" hitSlop={8} style={styles.boardBtn}>
              <Ionicons name="file-tray-full-outline" size={22} color={colors.text} />
            </Pressable>
          </View>
        </View>
        {board.data && todo.length === 0 ? <Text style={styles.empty}>지금은 내 차례인 놀이가 없어요</Text> : null}
        {todo.slice(0, SHOWN).map((item, i) => (
          <TurnRow key={item.id} item={item} strong={i === 0 && item.strong} />
        ))}
      </View>

      <View style={styles.section}>
        <View style={styles.startHead}>
          <Text style={styles.h2}>새 게임 시작하기</Text>
          {makeLeft != null ? <Text style={styles.makeLeft}>문제를 내면 +20점, 오늘 {makeLeft}번 남았어요</Text> : null}
        </View>
        <View style={styles.grid}>
          {GAME_LIST.map((g) => (
            <Pressable key={g.key} onPress={() => router.push(g.create)} accessibilityRole="button" accessibilityLabel={`${g.name}. ${g.tagline}`} style={styles.card}>
              <View style={styles.cardIcon}>
                <PlayIcon icon={g.icon} size={26} />
              </View>
              <Text style={styles.cardName}>{g.name}</Text>
              <Text style={styles.cardTag}>{g.tagline}</Text>
            </Pressable>
          ))}
        </View>
      </View>

      <Pressable onPress={() => router.push("/play/ranking")} accessibilityRole="button" accessibilityLabel="이번 주 가족 순위 전체 보기" style={styles.rank}>
        <View style={styles.rankHead}>
          <Text style={styles.rankTitle}>이번 주 가족 순위</Text>
          <Text style={styles.rankAll}>전체 보기</Text>
        </View>
        <View style={styles.podium}>
          {top.map((r, i) => (
            <View key={r.id} style={[styles.pod, i === 0 && styles.podFirst]}>
              <Text style={[styles.podNo, i === 0 && styles.podNoFirst]}>{i + 1}위</Text>
              <Text style={styles.podName}>{r.name}</Text>
              <Text style={styles.podScore}>{r.score}점</Text>
            </View>
          ))}
        </View>
      </Pressable>
    </PlayScreen>
  );
}

const styles = StyleSheet.create({
  section: { gap: 10 },
  turnHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  turnRight: { flexDirection: "row", alignItems: "center", gap: 4 },
  boardBtn: { width: 32, height: 32, marginRight: -4, alignItems: "center", justifyContent: "center" }, // 테두리 없이 아이콘만
  h2: { ...font.cardTitle, color: colors.text },
  count: { ...font.caption, color: colors.textSub },
  startHead: { flexDirection: "row", alignItems: "baseline", gap: 8 },
  makeLeft: { ...font.caption, color: colors.textSub, flexShrink: 1 },
  empty: { ...font.caption, color: colors.textSub, paddingVertical: 12, textAlign: "center" },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  card: { width: "48%", flexGrow: 1, padding: 14, borderRadius: radius.lg, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, gap: 4 },
  cardIcon: { width: 48, height: 48, borderRadius: 14, backgroundColor: colors.surfaceStrong, alignItems: "center", justifyContent: "center", marginBottom: 4 },
  cardName: { ...font.bodyStrong, color: colors.text },
  cardTag: { ...font.caption, color: colors.textSub },
  rank: { padding: 16, borderRadius: 18, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, gap: 12 },
  rankHead: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between" },
  rankTitle: { fontSize: 17, fontFamily: fonts.bold, color: colors.text },
  rankAll: { ...font.caption, color: colors.textSub },
  podium: { flexDirection: "row", justifyContent: "center", gap: 8 }, // 1~2명이어도 칸은 1/3 크기, 가운데 정렬
  pod: { width: "31.5%", aspectRatio: 1, borderRadius: 14, backgroundColor: "#F7F0E6", alignItems: "center", justifyContent: "center", gap: 6 },
  podFirst: { backgroundColor: colors.surfaceStrong },
  podNo: { fontSize: 13, lineHeight: 16, includeFontPadding: false, fontFamily: fonts.bold, color: colors.textSub },
  podNoFirst: { color: "#8A5A2B" },
  podName: { fontSize: 16, lineHeight: 20, includeFontPadding: false, fontFamily: fonts.bold, color: colors.text },
  podScore: { ...font.caption, lineHeight: 16, includeFontPadding: false, color: colors.textSub },
});
