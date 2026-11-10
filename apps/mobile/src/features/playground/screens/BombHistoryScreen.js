import { useLocalSearchParams } from "expo-router";
import { useCallback } from "react";
import { StyleSheet, Text, View } from "react-native";

import useResource from "@/shared/hooks/useResource";
import { colors, font, fonts, radius } from "@/theme";

import { bombHistoryView } from "../adapt";
import { getBombHistory } from "../api";
import { BOMB_RED } from "../components/bomb/BombParts";
import LoadNote from "../components/LoadNote";
import PlayScreen from "../components/PlayScreen";

/** 사람마다 다른 칩 색(adapt.HISTORY_TONES 개). 탈락한 말은 모두 빨강이라 빨강 계열은 쓰지 않는다. */
const TONES = [{ bg: "#F7F0E6" }, { bg: "#E3EEFA" }, { bg: "#E4F3E3" }, { bg: "#EDE7F6" }, { bg: "#DDF1F0" }, { bg: "#FDF3CF" }];

/** 지난 폭탄 방 기록: 방 요약과 판마다 이어 말한 문장 전체. 사람마다 칩 색이 다르고(판 제목 옆에 범례), 탈락한 말과 시간 초과는 글자만 빨갛게 취소선. 방에 참여한 가족만 볼 수 있다. */
export default function BombHistoryScreen() {
  const { id } = useLocalSearchParams();
  const loader = useCallback(async () => (id ? bombHistoryView(await getBombHistory(id)) : null), [id]);
  const state = useResource(loader);
  const view = state.data;
  return (
    <PlayScreen title="문장 폭탄 방" close>
      <LoadNote {...state} what="기록" />
      {view ? (
        <>
          <View style={styles.card}>
            <Text style={styles.head}>우리 가족 방</Text>
            <Text style={styles.sub}>{view.summary}</Text>
            {view.winLine ? <Text style={styles.sub}>{view.winLine}</Text> : null}
          </View>
          {view.rounds.length === 0 ? <Text style={styles.note}>아직 끝난 판이 없어요</Text> : null}
          {view.rounds.map((r) => (
            <View key={r.id} style={styles.card}>
              <View style={styles.titleRow}>
                <Text style={styles.cardTitle}>{r.title}</Text>
                {view.players.map((pl) => (
                  <Text key={pl.id} style={[styles.legend, { backgroundColor: TONES[pl.tone].bg }]}>
                    {pl.name}
                  </Text>
                ))}
              </View>
              <View style={styles.words}>
                {r.items.length === 0 ? <Text style={styles.sub}>말하지 못했어요</Text> : null}
                {r.items.map((w) => (
                  <Text key={w.id} style={[styles.word, { backgroundColor: TONES[w.tone].bg }, w.out && styles.wordOut]}>
                    {w.text}
                  </Text>
                ))}
              </View>
            </View>
          ))}
          <Text style={styles.note}>지난 결과는 3일 동안 볼 수 있어요</Text>
        </>
      ) : null}
    </PlayScreen>
  );
}

const styles = StyleSheet.create({
  card: { padding: 14, gap: 6, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  head: { ...font.cardTitle, color: colors.text },
  cardTitle: { fontSize: 14, fontFamily: fonts.bold, color: colors.text },
  sub: { ...font.caption, color: colors.textSub },
  titleRow: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 4 },
  legend: { paddingVertical: 0, paddingHorizontal: 6, borderRadius: 6, overflow: "hidden", fontSize: 11, lineHeight: 16, fontFamily: fonts.regular, color: colors.textSub },
  words: { flexDirection: "row", flexWrap: "wrap", gap: 4 },
  word: { paddingVertical: 1, paddingHorizontal: 8, borderRadius: 8, overflow: "hidden", fontSize: 14, lineHeight: 20, fontFamily: fonts.regular, color: colors.text, backgroundColor: "#F7F0E6" },
  wordOut: { color: BOMB_RED, textDecorationLine: "line-through" }, // 칩 색은 그 사람 색 그대로, 글자만 빨갛게 취소선
  note: { ...font.caption, color: colors.textSub, textAlign: "center" },
});
