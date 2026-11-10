import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, fonts, radius } from "@/theme";

import { BOMB_RED, PlayerStrip, TimeBar } from "../components/bomb/BombParts";
import PlayScreen from "../components/PlayScreen";

const VOTE_SEC = 8;
const VOTERS = 3;

/** 판정 결과: 문장을 끝냈다는 판정과 이의 투표(과반이면 취소). 8초 안에 정한다. */
export default function BombObjectionScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const sentence = params.sentence || "누가 어제 학교에서 강아지와 춤을 신나게 췄다!";
  const who = params.who || "엄마";
  const [left, setLeft] = useState(VOTE_SEC);
  const [votes, setVotes] = useState(1); // 시안: 이미 1명이 이의를 냈다
  const [mine, setMine] = useState(false);

  useEffect(() => {
    const t = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, []);
  const cancelled = votes > VOTERS / 2;

  const objection = () => {
    if (mine) return;
    setMine(true);
    setVotes((v) => v + 1);
  };
  const players = [
    { id: "mom", name: "엄마", lives: 2, total: 3, out: false },
    { id: "dad", name: "아빠", lives: 2, total: 3, out: false },
    { id: "me", name: "나", lives: 3, total: 3, out: false },
  ];

  return (
    <PlayScreen
      title="판정 결과"
      close
      footer={
        cancelled ? (
          <>
            <Text style={styles.cancel}>이의가 받아들여졌어요 · 생명이 줄지 않아요</Text>
            <Button label="게임으로 돌아가기" onPress={() => router.replace("/play/bomb-play")} />
          </>
        ) : (
          <View style={styles.btns}>
            <View style={styles.btn}>
              <Button label="판정이 맞아요" onPress={() => router.replace("/play/bomb-result")} />
            </View>
            <View style={styles.btn}>
              <Button label={mine ? "이의를 냈어요" : "이의 있어요"} variant="secondary" disabled={mine || left <= 0} onPress={objection} />
            </View>
          </View>
        )
      }
    >
      <PlayerStrip players={players} activeId={null} />
      <View style={styles.card}>
        <Text style={styles.cardTitle}>{who === "나" ? "내가" : `${who}가`} 문장을 끝냈어요</Text>
        <Text style={styles.sentence}>{sentence}</Text>
        <Text style={styles.judge}>판정: 끝나는 말이에요 (-았다) · {who} 생명 -1</Text>
      </View>
      <Text style={styles.note}>판정이 이상하면 이의를 낼 수 있어요</Text>
      <View style={styles.vote}>
        <View style={styles.voteHead}>
          <Text style={styles.voteText}>
            이의 있어요 {votes} / {VOTERS}명 · 절반을 넘으면 취소돼요
          </Text>
          <Text style={styles.left}>{left}초 남음</Text>
        </View>
        <TimeBar left={left} total={VOTE_SEC} danger={left <= 3} />
      </View>
    </PlayScreen>
  );
}

const styles = StyleSheet.create({
  card: { padding: 18, borderRadius: radius.card, backgroundColor: colors.dangerSoft, gap: 8 },
  cardTitle: { fontSize: 16, fontFamily: fonts.bold, color: BOMB_RED },
  sentence: { fontSize: 18, lineHeight: 28, fontFamily: fonts.bold, color: colors.text },
  judge: { ...font.caption, color: colors.textSub },
  note: { ...font.caption, color: colors.textSub, textAlign: "center" },
  vote: { gap: 8, padding: 14, borderRadius: radius.lg, backgroundColor: colors.surface },
  voteHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 },
  voteText: { flex: 1, ...font.caption, color: colors.text },
  left: { fontSize: 13, fontFamily: fonts.bold, color: BOMB_RED },
  btns: { flexDirection: "row", gap: 8 },
  btn: { flex: 1 },
  cancel: { ...font.caption, color: colors.success, textAlign: "center", fontFamily: fonts.bold },
});
