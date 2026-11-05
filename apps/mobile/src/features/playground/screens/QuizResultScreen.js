import { useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, fonts, radius } from "@/theme";

import AnswerRow, { bySolved } from "../components/AnswerRow";
import PlayScreen from "../components/PlayScreen";
import { SCORE } from "../games";

// 정답 공개 시안 데이터
const RESULTS = [
  { q: "엄마 생신은 12월이다", answer: "X", mine: "X", rows: [["아빠", "X", "09:30"], ["딸", "X", "11:05"], ["아들", "O", "12:00"]] },
  { q: "아빠가 제일 좋아하는 반찬은?", answer: "계란말이", mine: "멸치볶음", note: "아빠는 어릴 때부터 계란말이만 먹었대", rows: [["아빠", "멸치볶음", "09:30"], ["딸", "계란말이", "11:05"], ["아들", "계란말이", "12:00"]] },
  { q: "우리 가족이 처음 같이 간 여행지는?", answer: "제주도", mine: "제주도", rows: [["아빠", "제주도", "09:30"], ["딸", "제주도", "11:05"], ["아들", "강릉", "12:00"]] },
];

/** 골든벨 정답 공개: 맞힌 개수와 받은 점수, 문제별 정답·내 답·한마디·가족 결과. */
export default function QuizResultScreen() {
  const router = useRouter();
  const right = RESULTS.filter((r) => r.answer === r.mine).length;
  // 정답 점수는 세트 전체가 20점이고 맞힌 비율만큼 받는다(문제 수를 늘려도 점수가 늘지 않게)
  const quizPoints = Math.round((SCORE.correct * right) / RESULTS.length);
  const score = SCORE.join + quizPoints;
  return (
    <PlayScreen
      title="정답 공개"
      close
      footer={<Button label="나도 퀴즈 내기" variant="secondary" onPress={() => router.push("/play/quiz-create")} />}
    >
      <View style={styles.hero}>
        <Text style={styles.heroSub}>엄마가 낸 퀴즈 {RESULTS.length}문제</Text>
        <Text style={styles.heroBig}>
          {right}/{RESULTS.length} 맞혔어요
        </Text>
        <Text style={styles.heroSub}>
          <Text style={styles.heroScore}>{`점수 +${score}`}</Text>
          {` (참여 +${SCORE.join} 정답 +${quizPoints})`}
        </Text>
      </View>
      {RESULTS.map((r, i) => {
        const ok = r.answer === r.mine;
        return (
          <View key={r.q} style={[styles.card, ok ? styles.ok : styles.no]}>
            <Text style={[styles.tag, { color: ok ? colors.success : colors.danger }]}>
              {i + 1}번 {ok ? "맞혔어요" : "아쉬워요"}
            </Text>
            <Text style={styles.q}>{r.q}</Text>
            <Text style={styles.ans}>
              정답 <Text style={styles.bold}>{r.answer}</Text>{"   "}내 답 {r.mine}
            </Text>
            {r.note ? <Text style={styles.memo}>엄마의 한마디{`\n"${r.note}"`}</Text> : null}
            <View style={styles.rows}>
              {bySolved(r.rows, 2).map(([name, a]) => (
                <AnswerRow key={name} name={name} answer={a} ok={a === r.answer} />
              ))}
            </View>
          </View>
        );
      })}
    </PlayScreen>
  );
}

const styles = StyleSheet.create({
  hero: { padding: 18, borderRadius: radius.card, backgroundColor: colors.successSoft, gap: 4 },
  heroBig: { fontSize: 24, fontFamily: fonts.bold, color: "#2F4A3B" },
  heroScore: { fontSize: 16, fontFamily: fonts.bold },
  heroSub: { ...font.caption, color: "#2F4A3B" },
  card: { padding: 16, borderRadius: radius.lg, borderWidth: 1, gap: 6, backgroundColor: colors.card },
  ok: { borderColor: colors.successSoft },
  no: { borderColor: colors.dangerSoft },
  tag: { fontSize: 13, fontFamily: fonts.bold },
  q: { ...font.bodyStrong, color: colors.text },
  ans: { ...font.body, color: colors.textSub },
  bold: { fontFamily: fonts.bold, color: colors.text },
  memo: { padding: 10, borderRadius: radius.md, overflow: "hidden", backgroundColor: colors.surface, ...font.caption, color: colors.textSub },
  rows: { gap: 6 },
});
