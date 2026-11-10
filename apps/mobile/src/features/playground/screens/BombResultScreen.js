import { useLocalSearchParams, useRouter } from "expo-router";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import Avatar from "@/shared/components/Avatar";
import Button from "@/shared/components/Button";
import { colors, font, fonts, radius } from "@/theme";

import PlayScreen from "../components/PlayScreen";
import { SCORE } from "../games";
import { playLive } from "../hooks";
import { LiveBombResult } from "./BombLiveScreens";

const ROW_H = 64;
const VISIBLE = 3; // 순위는 3줄만 보이고 나머지는 목록 안에서 스크롤

const RANK = [
  { id: "dad", name: "아빠", sub: "생명 1개 · 끝까지 살아남음", points: SCORE.join + SCORE.bombWin },
  { id: "mom", name: "엄마", sub: "6라운드에서 탈락", points: SCORE.join },
  { id: "grandpa", name: "할아버지", sub: "5라운드에서 탈락", points: SCORE.join },
  { id: "daughter", name: "딸", sub: "4라운드에서 탈락", points: SCORE.join },
  { id: "grandma", name: "할머니", sub: "3라운드에서 탈락", points: SCORE.join },
  { id: "me", name: "나", sub: "2라운드에서 탈락", points: SCORE.join },
  { id: "son", name: "아들", sub: "1라운드에서 탈락", points: SCORE.join },
];

/** 문장 폭탄 결과: 최후의 1인, 이번 판 기록(가족 신기록), 순위와 점수. */
function MockBombResultScreen() {
  const router = useRouter();
  const mine = RANK.find((r) => r.id === "me");
  return (
    <PlayScreen
      title="결과"
      close
      fixed
      footer={
        <View style={styles.footerRow}>
          <View style={styles.footerCell}>
            <Button label="닫기" variant="secondary" onPress={() => router.replace("/play")} />
          </View>
          <View style={styles.footerCell}>
            <Button label="한 판 더" onPress={() => router.replace("/play/bomb-lobby")} />
          </View>
        </View>
      }
    >
      <View style={styles.top}>
        <View style={[styles.box, styles.winner]}>
          <Text style={[styles.tag, { color: colors.accent }]}>최후의 1인</Text>
          <Text style={styles.big}>아빠</Text>
        </View>
        <View style={[styles.box, styles.record]}>
          <Text style={[styles.tag, { color: "#2F4A3B" }]}>이번 판 기록</Text>
          <Text style={[styles.big, { color: "#2F4A3B" }]}>14개</Text>
          <Text style={styles.recordNote}>
            우리 가족 신기록이에요{"\n"}(이전 11개)
          </Text>
        </View>
      </View>
      <Text style={styles.section}>순위</Text>
      <ScrollView style={styles.list} contentContainerStyle={styles.listContent} showsVerticalScrollIndicator={false}>
      {RANK.map((r, i) => (
        <View key={r.id} style={[styles.row, r.id === "me" && styles.rowMine, i === 0 && styles.rowFirst]}>
          <Text style={styles.no}>{i + 1}</Text>
          <Avatar name={r.name} userId={r.id} size={40} />
          <View style={styles.rowText}>
            <Text style={styles.rowName}>{r.name}</Text>
            <Text style={styles.rowSub}>{r.sub}</Text>
          </View>
          <Text style={styles.points}>+{r.points}점</Text>
        </View>
      ))}
      </ScrollView>
      <View style={styles.mine}>
        <Text style={styles.mineBig}>내가 받은 점수 {mine.points}점</Text>
        <Text style={styles.mineSub}>
          참여 +{SCORE.join} 우승하면 +{SCORE.bombWin}
        </Text>
      </View>
    </PlayScreen>
  );
}

const styles = StyleSheet.create({
  footerRow: { flexDirection: "row", gap: 10 }, // 닫기 · 한 판 더를 1행 2열로
  footerCell: { flex: 1 },
  top: { flexDirection: "row", gap: 12 }, // 최후의 1인과 이번 판 기록을 반반
  box: { flex: 1, padding: 16, borderRadius: radius.card, alignItems: "center", justifyContent: "flex-start", gap: 4 },
  winner: { backgroundColor: colors.surfaceStrong },
  record: { backgroundColor: colors.successSoft },
  tag: { fontSize: 13, lineHeight: 18, fontFamily: fonts.bold, textAlign: "center" },
  big: { fontSize: 28, lineHeight: 36, fontFamily: fonts.bold, color: colors.text, textAlign: "center" },
  recordNote: { ...font.caption, color: "#2F4A3B", textAlign: "center" },
  list: { flexGrow: 0, flexShrink: 1, maxHeight: ROW_H * VISIBLE + 8 * (VISIBLE - 1) },
  listContent: { gap: 8 },
  section: { ...font.cardTitle, color: colors.text },
  row: { minHeight: ROW_H, flexDirection: "row", alignItems: "center", gap: 14, paddingHorizontal: 16, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  rowFirst: { borderColor: colors.surfaceStrong, backgroundColor: colors.surfaceStrong }, // 1등 줄은 노랗게
  rowMine: { borderWidth: 2, borderColor: "#E3CFB0", paddingHorizontal: 15 }, // 내 줄은 색은 그대로 두고 테두리만 조금 두껍게(안쪽 여백 1을 줄여 크기 유지)
  no: { width: 24, fontSize: 18, fontFamily: fonts.bold, color: colors.textSub },
  rowText: { flex: 1 },
  rowName: { ...font.bodyStrong, color: colors.text },
  rowSub: { ...font.caption, color: colors.textSub },
  points: { ...font.bodyStrong, color: colors.text },
  mine: { padding: 14, borderRadius: radius.lg, backgroundColor: colors.surface, alignItems: "center", gap: 2 },
  mineBig: { ...font.bodyStrong, color: colors.text },
  mineSub: { ...font.caption, color: colors.textSub },
});

export default function BombResultScreen() {
  const { id } = useLocalSearchParams();
  return playLive() && id ? <LiveBombResult id={id} /> : <MockBombResultScreen />;
}
