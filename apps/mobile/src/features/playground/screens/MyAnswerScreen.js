import { useLocalSearchParams } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import Svg, { Circle, Path } from "react-native-svg";

import { colors, font, fonts, radius } from "@/theme";

import PlayScreen from "../components/PlayScreen";
import ScoreBox from "../components/ScoreBox";
import { SCORE } from "../games";

// 시안 데이터: 내가 이미 답을 보냈지만 가족 전체 결과는 아직 안 열린 골든벨. 정답과 내가 고른 답을 같이 보여 준다.
const QUIZ = [
  { kind: "OX", q: "아빠 생일은 3월이다", mine: "O", answer: "O", options: ["O", "X"] },
  { kind: "선택", q: "엄마가 제일 좋아하는 꽃은?", mine: "장미", answer: "튤립", note: "엄마는 튤립만 보면 사진부터 찍어", options: ["장미", "튤립", "수국", "프리지아"] },
  { kind: "선택", q: "우리 집 막내는 누구?", mine: "딸", answer: "딸", options: ["아들", "딸", "강아지"] },
];
const PHOTO_OPTIONS = ["제주도 여행", "할머니 댁", "강릉 바다", "우리 집 거실"];
// 받는 가족 현황(문제를 낸 사람은 뺌). done 이 완료한 사람, 나는 이미 끝냈다.
const FAMILY = {
  quiz: { done: ["엄마"], pending: ["아들", "딸"] },
  draw: { done: ["아들"], pending: ["엄마", "아빠"] },
  photo: { done: ["아빠"], pending: ["아들", "딸"] },
};
const INFO = {
  quiz: { from: "아빠가 낸 가족 골든벨", end: "내일 오전 9:30" },
  draw: { from: "딸이 낸 이게 뭐게", end: "내일 오후 2:10" },
  photo: { from: "엄마가 낸 찰칵! 탐정단", end: "내일 오후 2:10" },
};

/** 공개 전에 내가 참여한 문제: 문제와 내가 낸 답만 보여 준다(정답·맞았는지·점수는 공개 뒤에). 답은 고칠 수 없다. kind = quiz | draw | photo */
export default function MyAnswerScreen() {
  // 푸는 화면에서 넘어오면 그 문제의 이름·정답·연 힌트로 보여 주고, 현황판에서 직접 들어오면 시안 값을 쓴다
  const { kind = "quiz", from: fromParam, maker, answer, alt, hint2, hints, tries, hit } = useLocalSearchParams();
  const k = INFO[kind] ? kind : "quiz";
  const from = fromParam || INFO[k].from;
  return (
    <PlayScreen title="내가 낸 답" close>
      {k === "draw" || k === "quiz" ? null : (
        <View style={styles.notice}>
          <Text style={styles.noticeTitle}>{from}</Text>
        </View>
      )}
      {k === "quiz" ? <Quiz from={from} /> : null}
      {k === "draw" ? <Draw maker={maker || "딸이"} answer={answer || "고양이"} alt={alt === undefined ? "야옹이" : alt} hint2={hint2 || "동물이야"} hints={hints === undefined ? 2 : Number(hints)} tries={tries ? JSON.parse(tries) : null} /> : null}
      {k === "photo" ? <Photo hit={hit === "1"} /> : null}
      <Family kind={k} end={INFO[k].end} />
      <Text style={styles.foot}>보낸 답은 고칠 수 없어요</Text>
    </PlayScreen>
  );
}

/** 누가 했는지: 두 줄. 윗줄은 "완료" 칩 + 한 가족, 아랫줄은 "대기" 칩 + 아직 안 한 가족. */
function Family({ kind, end }) {
  const f = FAMILY[kind];
  const done = ["나", ...f.done];
  return (
    <View style={styles.family}>
      <View style={styles.familyHead}>
        <Text style={styles.h2}>가족 현황</Text>
      </View>
      <View style={styles.lineRow}>
        <Text style={styles.status}>완료</Text>
        <Text style={styles.names}>{done.join("  ")}</Text>
      </View>
      {f.pending.length ? (
        <View style={styles.lineRow}>
          <Text style={[styles.status, styles.statusWait]}>대기</Text>
          <Text style={styles.names}>{f.pending.join("  ")}</Text>
        </View>
      ) : null}
      <Text style={styles.end}>{end}에 종료돼요</Text>
    </View>
  );
}

function Quiz({ from }) {
  const right = QUIZ.filter((r) => r.mine === r.answer).length;
  // 정답 점수는 세트 전체 20점을 맞힌 비율로 나눈다(정답 공개 화면과 같은 계산)
  const quizPoints = Math.round((SCORE.correct * right) / QUIZ.length);
  return (
    <>
      <View style={styles.hero}>
        <Text style={styles.heroSub}>{from}</Text>
        <Text style={styles.heroBig}>
          {right}/{QUIZ.length} 맞혔어요
        </Text>
        <Text style={styles.heroSub}>
          <Text style={styles.heroScore}>{`점수 +${SCORE.join + quizPoints}`}</Text>
          {` (참여 +${SCORE.join} 정답 +${quizPoints})`}
        </Text>
      </View>
      {QUIZ.map((r, i) => {
        const hit = r.mine === r.answer;
        return (
          <View key={r.q} style={styles.card}>
            <Text style={styles.tag}>문제 {i + 1}</Text>
            <Text style={styles.q}>{r.q}</Text>
            {r.options.map((o) => (
              <View key={o} style={[styles.row, o === r.mine && styles.rowMine, o === r.answer && styles.rowAnswer, hit && o === r.answer && styles.rowHit]}>
                <Text style={[styles.rowText, (o === r.mine || o === r.answer) && styles.rowTextMine]}>{o}</Text>
                {hit ? null : <Text style={styles.mineTag}>{o === r.answer ? "정답" : o === r.mine ? "내 답" : ""}</Text>}
              </View>
            ))}
            {r.note ? (
              <View style={styles.memo}>
                <Text style={styles.memoText}>{`엄마의 한마디
"${r.note}"`}</Text>
              </View>
            ) : null}
          </View>
        );
      })}
    </>
  );
}

function Draw({ maker, answer, alt, hint2, hints, tries }) {
  const solved = !tries; // 10번 다 틀려서 온 경우(tries 있음)는 못 맞힌 것
  const shown = alt ? `${answer} (${alt})` : answer;
  const letters = answer.replace(/\s/g, "").length;
  return (
    <>
      <View style={styles.hero}>
        <Text style={styles.heroSub}>{maker} 그린 그림</Text>
        <Text style={styles.heroBig}>{shown}</Text>
      </View>
      <View style={styles.canvas}>
        <Svg width={200} height={170} viewBox="0 0 220 200" accessibilityLabel="그린 그림">
          <Path d="M55 80c0-35 25-55 55-55s55 20 55 55-20 80-55 80-55-45-55-80z" stroke={colors.text} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" fill="none" />
          <Circle cx={88} cy={85} r={5} stroke={colors.text} strokeWidth={4} fill="none" />
          <Circle cx={132} cy={85} r={5} stroke={colors.text} strokeWidth={4} fill="none" />
        </Svg>
      </View>
      <View style={styles.mine}>
        <View style={styles.mineCol}>
          <Text style={styles.mineLabel}>내가 쓴 답</Text>
          <Text style={styles.mineText}>{solved ? (alt ? alt.split(",")[0].trim() : answer) : tries.join(" · ")}</Text>
        </View>
        {hints > 0 ? (
          <View style={styles.chips}>
            <Text style={styles.hint}>힌트 1: {letters}글자</Text>
            {hints >= 2 ? <Text style={styles.hint}>힌트 2: {hint2}</Text> : null}
          </View>
        ) : null}
      </View>
      <ScoreBox total={solved ? SCORE.join + SCORE.correct - SCORE.hintCost * hints : SCORE.join - SCORE.hintCost * hints} detail={solved ? `참여 +${SCORE.join} 정답 +${SCORE.correct}${hints ? ` 힌트 -${SCORE.hintCost * hints}` : ""}` : `참여 +${SCORE.join}${hints ? ` 힌트 -${SCORE.hintCost * hints}` : ""}`} />
    </>
  );
}

// 시안: 기본은 정답 제주도 여행·내 답 할머니 댁(틀린 경우), hit=1 이면 정답과 내 답이 모두 강릉 바다(맞힌 경우)

function Photo({ hit }) {
  const answerIdx = hit ? 2 : 0;
  const mine = hit ? 2 : 1;
  return (
    <>
      <View style={styles.stage}>
        <View style={styles.box} />
        <Text style={styles.badge}>4배 확대</Text>
      </View>
      <View style={styles.memo}>
        <Text style={styles.memoText}>{`엄마의 한마디
"그날 비가 와서 협재 해변에서 우동을 먹었어요"`}</Text>
      </View>
      <View style={styles.card}>
        <Text style={styles.q}>이 사진, 어디서 누구랑 찍었을까요?</Text>
        {PHOTO_OPTIONS.map((o, i) => (
          <View key={o} style={[styles.row, i === mine && styles.rowMine, i === answerIdx && styles.rowAnswer, hit && i === answerIdx && styles.rowHit]}>
            <Text style={[styles.rowText, (i === mine || i === answerIdx) && styles.rowTextMine]}>{o}</Text>
            {hit ? null : <Text style={styles.mineTag}>{i === answerIdx ? "정답" : i === mine ? "내 답" : ""}</Text>}
          </View>
        ))}
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  notice: { padding: 16, borderRadius: radius.card, backgroundColor: colors.surface, gap: 4 },
  noticeTitle: { ...font.bodyStrong, color: colors.text },
  card: { padding: 16, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, gap: 8 },
  tag: { fontSize: 12, fontFamily: fonts.bold, color: "#8A5A2B" },
  q: { ...font.bodyStrong, color: colors.text },
  big: { fontSize: 22, fontFamily: fonts.bold, color: colors.text },
  sub: { ...font.caption, color: colors.textSub },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6, alignItems: "flex-start" },
  opt: { paddingVertical: 4, paddingHorizontal: 10, borderRadius: 12, overflow: "hidden", backgroundColor: "#F7F0E6", color: colors.textSub, fontSize: 13, fontFamily: fonts.regular },
  optMine: { backgroundColor: colors.surfaceStrong, color: colors.text, fontFamily: fonts.bold },
  selfStart: { alignSelf: "flex-start" },
  hint: { paddingVertical: 3, paddingHorizontal: 10, borderRadius: 12, overflow: "hidden", backgroundColor: colors.card, color: colors.text, fontSize: 12, fontFamily: fonts.bold },
  canvas: { height: 190, borderRadius: radius.card, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  stage: { height: 220, borderRadius: radius.card, backgroundColor: "#CDB9A3", overflow: "hidden" },
  box: { position: "absolute", left: 130, top: 70, width: 98, height: 74, borderWidth: 3, borderColor: colors.background, borderRadius: 10, backgroundColor: "rgba(255,252,247,0.25)" },
  badge: { position: "absolute", right: 12, bottom: 10, paddingVertical: 3, paddingHorizontal: 9, borderRadius: 999, overflow: "hidden", backgroundColor: colors.background, fontSize: 12, fontFamily: fonts.bold, color: colors.text },
  row: { height: 44, paddingHorizontal: 12, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  rowMine: { backgroundColor: colors.surfaceStrong, borderColor: colors.surfaceStrong },
  rowText: { fontSize: 15, fontFamily: fonts.regular, color: colors.text },
  rowTextMine: { fontFamily: fonts.bold },
  rowHit: { backgroundColor: colors.successSoft, borderColor: colors.success }, // 맞힌 경우만: 초록 배경과 굵은 초록 테두리(글자 없음)
  mineTag: { fontSize: 12, fontFamily: fonts.bold, color: colors.text },
  rowAnswer: { borderWidth: 2, borderColor: "#B98A45", paddingHorizontal: 11 }, // 정답: 굵은 진한 테두리(내가 고른 보기의 노란 배경과 같이 쓸 수 있다)
  memo: { padding: 12, borderRadius: radius.md, backgroundColor: colors.surface },
  memoText: { ...font.caption, color: colors.textSub, lineHeight: 20 },
  hero: { padding: 18, borderRadius: radius.card, backgroundColor: colors.successSoft, gap: 4 },
  heroBig: { fontSize: 24, fontFamily: fonts.bold, color: "#2F4A3B" },
  heroScore: { fontSize: 16, fontFamily: fonts.bold },
  heroSub: { ...font.caption, color: "#2F4A3B" },
  mineCol: { gap: 4 },
  mine: { padding: 14, borderRadius: radius.md, backgroundColor: colors.surfaceStrong, gap: 8 },
  mineLabel: { ...font.caption, color: colors.textSub },
  mineText: { fontSize: 16, fontFamily: fonts.bold, color: colors.text },
  family: { gap: 4 },
  familyHead: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between" },
  h2: { ...font.cardTitle, color: colors.text },
  end: { ...font.caption, color: colors.textSub, marginTop: 4 },
  lineRow: { minHeight: 36, flexDirection: "row", alignItems: "center", gap: 10 },
  names: { flex: 1, ...font.bodyStrong, color: colors.text },
  status: { paddingVertical: 4, paddingHorizontal: 14, borderRadius: 999, overflow: "hidden", backgroundColor: colors.successSoft, color: "#2F4A3B", fontSize: 12, fontFamily: fonts.bold },
  statusWait: { backgroundColor: "#F7F0E6", color: colors.textSub },
  foot: { ...font.caption, color: colors.textSub, textAlign: "center" },
});
