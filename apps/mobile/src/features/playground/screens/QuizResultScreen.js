import { useLocalSearchParams, useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, fonts, radius } from "@/theme";

import { quizResultView } from "../adapt";
import AnswerRow from "../components/AnswerRow";
import LoadNote from "../components/LoadNote";
import PlayScreen from "../components/PlayScreen";
import { SCORE } from "../games";
import { playLive, useMyId, usePlayItem } from "../hooks";

// 정답 공개 시안 데이터
const RESULTS = [
  { q: "엄마 생신은 12월이다", answer: "X", mine: "X", rows: [["아빠", "X", "09:30"], ["딸", "X", "11:05"], ["아들", "O", "12:00"]] },
  { q: "아빠가 제일 좋아하는 반찬은?", answer: "계란말이", mine: "멸치볶음", note: "아빠는 어릴 때부터 계란말이만 먹었대", rows: [["아빠", "멸치볶음", "09:30"], ["딸", "계란말이", "11:05"], ["아들", "계란말이", "12:00"]] },
  { q: "우리 가족이 처음 같이 간 여행지는?", answer: "제주도", mine: "제주도", rows: [["아빠", "제주도", "09:30"], ["딸", "제주도", "11:05"], ["아들", "강릉", "12:00"]] },
];

/** 시안 데이터를 서버 결과와 같은 모양으로 맞춘다. 정답 점수는 세트 전체가 20점이고 맞힌 비율만큼 받는다. */
function mockView() {
  const questions = RESULTS.map((r) => ({
    q: r.q,
    answer: r.answer,
    mine: r.mine,
    hit: r.answer === r.mine,
    note: r.note ?? "",
    rows: [...r.rows].sort((a, b) => a[2].localeCompare(b[2])).map(([name, text]) => ({ name, text, ok: text === r.answer })),
  }));
  const right = questions.filter((q) => q.hit).length;
  const correct = Math.round((SCORE.correct * right) / RESULTS.length);
  return { maker: "엄마", total: RESULTS.length, right, score: { total: SCORE.join + correct, join: SCORE.join, correct, hint: 0 }, hasScore: true, questions };
}

/** 골든벨 정답 공개: 맞힌 개수와 받은 점수, 문제별 정답·내 답·한마디·가족 결과. 서버에 연결되면 id 로 결과를 불러온다. */
export default function QuizResultScreen() {
  const { id } = useLocalSearchParams();
  const live = playLive() && Boolean(id);
  const res = usePlayItem(live ? id : null);
  const myId = useMyId();
  const view = live ? (res.data ? quizResultView(res.data, myId) : null) : mockView();
  if (!view) {
    return (
      <PlayScreen title="정답 공개" close>
        <LoadNote {...res} what="결과" />
      </PlayScreen>
    );
  }
  return <QuizResultBody view={view} />;
}

function QuizResultBody({ view }) {
  const router = useRouter();
  const { score } = view;
  return (
    <PlayScreen
      title="정답 공개"
      close
      footer={<Button label="나도 퀴즈 내기" variant="secondary" onPress={() => router.push("/play/quiz-create")} />}
    >
      <View style={styles.hero}>
        <Text style={styles.heroSub}>{view.maker}가 낸 퀴즈 {view.total}문제</Text>
        {view.hasScore ? (
          <>
            <Text style={styles.heroBig}>
              {view.right}/{view.total} 맞혔어요
            </Text>
            <Text style={styles.heroSub}>
              <Text style={styles.heroScore}>{`점수 +${score.total}`}</Text>
              {` (참여 +${score.join} 정답 +${score.correct}${score.hint ? ` 힌트 ${score.hint}` : ""})`}
            </Text>
          </>
        ) : null}
      </View>
      {view.questions.map((r, i) => {
        const answered = r.mine != null;
        return (
          <View key={r.q} style={[styles.card, !answered ? null : r.hit ? styles.ok : styles.no]}>
            {answered ? (
              <Text style={[styles.tag, { color: r.hit ? colors.success : colors.danger }]}>
                {i + 1}번 {r.hit ? "맞혔어요" : "아쉬워요"}
              </Text>
            ) : (
              <Text style={styles.tag}>{i + 1}번</Text>
            )}
            <Text style={styles.q}>{r.q}</Text>
            <Text style={styles.ans}>
              정답 <Text style={styles.bold}>{r.answer}</Text>
              {answered ? `   내 답 ${r.mine}` : ""}
            </Text>
            {r.note ? <Text style={styles.memo}>{view.maker}의 한마디{`
"${r.note}"`}</Text> : null}
            <View style={styles.rows}>
              {r.rows.map((row) => (
                <AnswerRow key={row.name} name={row.name} answer={row.text} ok={row.ok} />
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
