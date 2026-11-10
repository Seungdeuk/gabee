import { useLocalSearchParams, useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import Svg, { Circle, Path } from "react-native-svg";

import AuthImage from "@/shared/components/AuthImage";
import Button from "@/shared/components/Button";
import { colors, font, fonts, radius } from "@/theme";

import { drawResultView } from "../adapt";
import AnswerRow from "../components/AnswerRow";
import LoadNote from "../components/LoadNote";
import PlayScreen from "../components/PlayScreen";
import ScoreBox from "../components/ScoreBox";
import { SCORE } from "../games";
import { playLive, useMyId, usePlayItem } from "../hooks";

// 시안: 정답과 이것도 정답, 내가 정답으로 인정받은 답, 연 힌트 수
const ANSWER = "강아지";
const ALT = ["멍멍이", "개"];
const MINE = "멍멍이";
const HINTS = 2;
const HINT2 = "동물이야";
// 가족이 낸 답(푼 시각은 정렬에만 쓴다): 이름, 답, 시각, 쓴 힌트 수
const ROWS = [["아빠", ["고양이", "토끼", "곰", "사자", "호랑이", "여우", "늑대", "다람쥐", "원숭이", "기린"].join(" · "), "13:00", 1], ["엄마", "강아지", "09:20", 0]];

/** 시안 데이터를 서버 결과와 같은 모양으로 맞춘다. */
function mockView() {
  const correct = SCORE.correct;
  return {
    maker: "아들",
    imageUrl: null,
    heroText: `${ANSWER} (${ALT.join(", ")})`,
    mineText: MINE,
    hint1: HINTS >= 1 ? `${ANSWER.length}글자` : null,
    hint2: HINTS >= 2 ? HINT2 : null,
    hasScore: true,
    score: { total: SCORE.join + correct - SCORE.hintCost * HINTS, join: SCORE.join, correct, hint: -SCORE.hintCost * HINTS },
    rows: [...ROWS].sort((a, b) => a[2].localeCompare(b[2])).map(([name, text, , hints]) => ({ name, text, ok: text === ANSWER || ALT.includes(text), hints })),
  };
}

/** 이게 뭐게 정답 공개(받은 쪽): 정답, 그림, 내 답과 받은 점수, 쓴 힌트, 누가 맞혔나. 서버에 연결되면 id 로 결과를 불러온다. */
export default function DrawResultScreen() {
  const { id } = useLocalSearchParams();
  const live = playLive() && Boolean(id);
  const res = usePlayItem(live ? id : null);
  const myId = useMyId();
  const view = live ? (res.data?.draw ? drawResultView(res.data, myId) : null) : mockView();
  if (!view) {
    return (
      <PlayScreen title="정답 공개" close>
        <LoadNote {...res} what="결과" />
      </PlayScreen>
    );
  }
  return <DrawResultBody view={view} />;
}

function DrawResultBody({ view }) {
  const router = useRouter();
  const { score } = view;
  const scoreDetail = `참여 +${score.join}${score.correct ? ` 정답 +${score.correct}` : ""}${score.hint ? ` 힌트 ${score.hint}` : ""}`;
  return (
    <PlayScreen
      title="정답 공개"
      close
      footer={<Button label="나도 그림 문제 내기" variant="secondary" onPress={() => router.push("/play/draw-create")} />}
    >
      <View style={styles.hero}>
        <Text style={styles.heroSub}>{view.maker}가 그린 그림</Text>
        <Text style={styles.heroBig}>{view.heroText}</Text>
      </View>
      {view.imageUrl ? (
        <AuthImage path={view.imageUrl} contentFit="contain" style={styles.canvas} accessibilityLabel={`${view.maker}가 그린 그림`} />
      ) : (
        <View style={styles.canvas}>
          <Svg width={200} height={170} viewBox="0 0 220 200" accessibilityLabel="아들이 그린 그림">
            <Path d="M55 80c0-35 25-55 55-55s55 20 55 55-20 80-55 80-55-45-55-80z" stroke={colors.text} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" fill="none" />
            <Circle cx={88} cy={85} r={5} stroke={colors.text} strokeWidth={4} fill="none" />
            <Circle cx={132} cy={85} r={5} stroke={colors.text} strokeWidth={4} fill="none" />
          </Svg>
        </View>
      )}
      {view.hasScore ? (
        <>
          <View style={styles.mine}>
            <View style={styles.mineCol}>
              <Text style={styles.mineLabel}>내가 쓴 답</Text>
              <Text style={styles.mineText}>{view.mineText}</Text>
            </View>
            {view.hint1 ? (
              <View style={styles.chips}>
                <Text style={styles.hint}>힌트 1: {view.hint1}</Text>
                {view.hint2 ? <Text style={styles.hint}>힌트 2: {view.hint2}</Text> : null}
              </View>
            ) : null}
          </View>
          <ScoreBox total={score.total} detail={scoreDetail} />
        </>
      ) : null}
      <Text style={styles.label}>가족이 낸 답</Text>
      <View style={styles.rows}>
        {view.rows.map((r) => (
          <AnswerRow key={r.name} name={r.name} answer={r.text} ok={r.ok} extra={r.hints ? `힌트 ${r.hints}개` : ""} />
        ))}
      </View>
    </PlayScreen>
  );
}

const styles = StyleSheet.create({
  hero: { padding: 18, borderRadius: radius.card, backgroundColor: colors.successSoft, gap: 4 },
  heroBig: { fontSize: 24, fontFamily: fonts.bold, color: "#2F4A3B" },
  heroSub: { ...font.caption, color: "#2F4A3B" },
  canvas: { height: 190, borderRadius: radius.card, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  mine: { padding: 14, borderRadius: radius.md, backgroundColor: colors.surfaceStrong, gap: 8 },
  mineCol: { gap: 4 },
  mineLabel: { ...font.caption, color: colors.textSub },
  mineText: { fontSize: 17, fontFamily: fonts.bold, color: colors.text },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  hint: { paddingVertical: 4, paddingHorizontal: 12, borderRadius: 999, overflow: "hidden", backgroundColor: colors.card, color: colors.text, fontSize: 12, fontFamily: fonts.bold },
  memo: { padding: 12, borderRadius: radius.md, backgroundColor: colors.surface },
  memoText: { ...font.caption, color: colors.textSub, lineHeight: 20 },
  label: { ...font.bodyStrong, color: colors.text },
  rows: { gap: 6 },
});
