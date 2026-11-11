import { useLocalSearchParams } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import Svg, { Circle, Path } from "react-native-svg";

import AuthImage from "@/shared/components/AuthImage";
import { colors, font, fonts, radius } from "@/theme";

import { drawResultView, gameKey, photoResultView, quizResultView } from "../adapt";
import AnswerRow, { bySolved } from "../components/AnswerRow";
import LoadNote from "../components/LoadNote";
import PhotoStage from "../components/PhotoStage";
import PlayScreen from "../components/PlayScreen";
import { MAKE_LIMIT, SCORE } from "../games";
import { playLive, usePlayItem } from "../hooks";

// 시안 데이터: 공개가 끝난 내가 낸 문제. 가족이 낸 답은 푼 순서(시각이 빠른 순)로 보여 준다.
// time 은 "시:분"(24시간). 정렬에만 쓴다.
const QUIZ = {
  title: "내가 낸 골든벨",
  items: [
    { q: "엄마 생신은 12월이다", kind: "OX", answer: "X", rows: [["딸", "O", "11:05"], ["엄마", "X", "09:12"], ["아빠", "X", "10:40"]] },
    { q: "아빠가 제일 좋아하는 반찬은?", kind: "선택", answer: "계란말이", note: "어릴 때부터 계란말이만 먹었대", rows: [["아빠", "계란말이", "10:40"], ["딸", "멸치볶음", "11:05"], ["엄마", "계란말이", "09:12"]] },
  ],
};
const DRAW = {
  title: "내가 낸 이게 뭐게",
  answer: "고양이",
  alt: "야옹이",
  rows: [
    ["아빠", "호랑이", "13:20", 2],
    ["딸", "고양이", "09:30", 0],
    ["엄마", "야옹이", "10:05", 1],
  ],
};
const PHOTO = {
  title: "내가 낸 찰칵! 탐정단",
  question: "이 사진, 어디서 찍었을까요?",
  answer: "제주도 여행",
  note: "그날 비가 와서 협재 해변에서 우동을 먹었어요",
  rows: [
    ["아빠", "돌잔치", "13:50"],
    ["엄마", "제주도 여행", "09:12"],
    ["딸", "제주도 여행", "10:41"],
  ],
};

// 푼 순서: 시각이 빠른 사람이 위(시각은 정렬에만 쓰고 화면에는 보이지 않는다)
const byTime = bySolved;

/** 내가 낸 문제 결과(공개 뒤): 문제별 정답과 가족이 낸 답(푼 순서). kind = quiz | draw | photo */
export default function SentResultScreen() {
  const { id } = useLocalSearchParams();
  return playLive() && id ? <LiveSentResult id={id} /> : <MockSentResult />;
}

// 문제를 낸 사람의 점수 안내: 닫힌 뒤 서버가 정산한 결과
const MAKER_NOTE = {
  paid: `문제 출제로 +${SCORE.make} 받았어요`,
  none_solved: "아무도 풀지 않아 문제 출제 점수는 없어요",
  daily_limit: `오늘 문제 출제 점수 ${MAKE_LIMIT}건을 넘어서 점수는 없어요`,
  pending: "결과가 열리면 점수가 정해져요",
};

/** 서버에 연결됐을 때: 닫힌 내가 낸 문제의 정답과 가족이 낸 답(푼 순서). */
function LiveSentResult({ id }) {
  const res = usePlayItem(id);
  const item = res.data;
  if (!item) {
    return (
      <PlayScreen title="정답 공개" close>
        <LoadNote {...res} what="결과" />
      </PlayScreen>
    );
  }
  const k = gameKey(item.game);
  const names = { quiz: "내가 낸 골든벨", draw: "내가 낸 이게 뭐게", photo: "내가 낸 찰칵! 탐정단" };
  const solved = (item.family_answers ?? []).filter((fa) => fa.answers.length).length;
  return (
    <PlayScreen title="정답 공개" close>
      <View style={styles.hero}>
        <Text style={styles.heroSub}>{names[k]}</Text>
        <Text style={styles.heroBig}>가족 {solved}명이 풀었어요</Text>
        <Text style={styles.heroSub}>{MAKER_NOTE[item.maker_score_state] ?? ""}</Text>
      </View>
      {k === "draw" ? <LiveDraw item={item} /> : k === "photo" ? <LivePhoto item={item} /> : <LiveQuiz item={item} />}
    </PlayScreen>
  );
}

function LiveQuiz({ item }) {
  const v = quizResultView(item, null);
  return (
    <>
      {v.questions.map((r, i) => (
        <View key={r.q} style={styles.card}>
          <Text style={styles.tag}>
            문제 {i + 1} {r.kind}
          </Text>
          <Text style={styles.q}>{r.q}</Text>
          <Text style={styles.ans}>
            정답 <Text style={styles.bold}>{r.answer}</Text>
          </Text>
          {r.note ? <Text style={styles.memo}>{`내가 쓴 한마디\n"${r.note}"`}</Text> : null}
          <View style={styles.rows}>
            {r.rows.map((row) => (
              <AnswerRow key={row.name} name={row.name} answer={row.text} ok={row.ok} />
            ))}
          </View>
        </View>
      ))}
    </>
  );
}

function LiveDraw({ item }) {
  const v = drawResultView(item, null);
  return (
    <>
      <AuthImage path={v.imageUrl} contentFit="contain" style={styles.canvas} accessibilityLabel="내가 그린 그림" />
      <View style={styles.card}>
        <Text style={styles.ans}>
          정답 <Text style={styles.bold}>{v.answer}</Text>
        </Text>
        {v.alts.length ? <Text style={styles.sub}>이것도 정답: {v.alts.join(", ")}</Text> : null}
        <View style={styles.rows}>
          {v.rows.map((r) => (
            <AnswerRow key={r.name} name={r.name} answer={r.text} ok={r.ok} extra={r.hints ? `힌트 ${r.hints}개` : ""} />
          ))}
        </View>
      </View>
    </>
  );
}

function LivePhoto({ item }) {
  const v = photoResultView(item, null);
  return (
    <>
      <PhotoStage path={v.imageUrl} box={v.box} badge="원본 사진" note={v.box ? "네모가 문제로 낸 부분이에요" : undefined} label="원본 사진" />
      <View style={styles.card}>
        <Text style={styles.q}>{v.question}</Text>
        <Text style={styles.ans}>
          정답 <Text style={styles.bold}>{v.answer}</Text>
        </Text>
        {v.comment ? <Text style={styles.memo}>{`내가 쓴 한마디\n"${v.comment}"`}</Text> : null}
        <View style={styles.rows}>
          {v.rows.map((r) => (
            <AnswerRow key={r.name} name={r.name} answer={r.text} ok={r.ok} />
          ))}
        </View>
      </View>
    </>
  );
}

function MockSentResult() {
  const { kind = "quiz" } = useLocalSearchParams();
  const k = kind === "draw" || kind === "photo" ? kind : "quiz";
  const info = { quiz: QUIZ, draw: DRAW, photo: PHOTO }[k];
  const who = k === "quiz" ? QUIZ.items[0].rows.length : info.rows.length;
  return (
    <PlayScreen title="정답 공개" close>
      <View style={styles.hero}>
        <Text style={styles.heroSub}>{info.title}</Text>
        <Text style={styles.heroBig}>가족 {who}명이 풀었어요</Text>
        <Text style={styles.heroSub}>{`문제 출제로 +${SCORE.make} 받았어요`}</Text>
      </View>
      {k === "draw" ? <Draw /> : k === "photo" ? <Photo /> : <Quiz />}
    </PlayScreen>
  );
}

function Quiz() {
  return (
    <>
      {QUIZ.items.map((r, i) => (
        <View key={r.q} style={styles.card}>
          <Text style={styles.tag}>
            문제 {i + 1} {r.kind}
          </Text>
          <Text style={styles.q}>{r.q}</Text>
          <Text style={styles.ans}>
            정답 <Text style={styles.bold}>{r.answer}</Text>
          </Text>
          {r.note ? <Text style={styles.memo}>{`내가 쓴 한마디\n"${r.note}"`}</Text> : null}
          <View style={styles.rows}>
            {byTime(r.rows, 2).map(([name, a]) => (
              <AnswerRow key={name} name={name} answer={a} ok={a === r.answer} />
            ))}
          </View>
        </View>
      ))}
    </>
  );
}

function Draw() {
  return (
    <>
      <View style={styles.canvas}>
        <Svg width={200} height={160} viewBox="0 0 220 200" accessibilityLabel="내가 그린 그림">
          <Path d="M55 80c0-35 25-55 55-55s55 20 55 55-20 80-55 80-55-45-55-80z" stroke={colors.text} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" fill="none" />
          <Circle cx={88} cy={85} r={5} stroke={colors.text} strokeWidth={4} fill="none" />
          <Circle cx={132} cy={85} r={5} stroke={colors.text} strokeWidth={4} fill="none" />
        </Svg>
      </View>
      <View style={styles.card}>
        <Text style={styles.ans}>
          정답 <Text style={styles.bold}>{DRAW.answer}</Text>
        </Text>
        <Text style={styles.sub}>이것도 정답: {DRAW.alt}</Text>
        <View style={styles.rows}>
          {byTime(DRAW.rows, 2).map(([name, a, , hints]) => (
            <AnswerRow key={name} name={name} answer={a} ok={a === DRAW.answer || a === DRAW.alt} extra={hints ? `힌트 ${hints}개` : ""} />
          ))}
        </View>
      </View>
    </>
  );
}

function Photo() {
  return (
    <>
      <View style={styles.stage}>
        <View style={styles.box} />
        <Text style={styles.badge}>원본 사진</Text>
        <Text style={styles.stageNote}>네모가 문제로 낸 부분이에요</Text>
      </View>
      <View style={styles.card}>
        <Text style={styles.q}>{PHOTO.question}</Text>
        <Text style={styles.ans}>
          정답 <Text style={styles.bold}>{PHOTO.answer}</Text>
        </Text>
        <Text style={styles.memo}>{`내가 쓴 한마디\n"${PHOTO.note}"`}</Text>
        <View style={styles.rows}>
          {byTime(PHOTO.rows, 2).map(([name, a]) => (
            <AnswerRow key={name} name={name} answer={a} ok={a === PHOTO.answer} />
          ))}
        </View>
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  hero: { padding: 18, borderRadius: radius.card, backgroundColor: colors.successSoft, gap: 4 },
  heroBig: { fontSize: 22, fontFamily: fonts.bold, color: "#2F4A3B" },
  heroSub: { ...font.caption, color: "#2F4A3B" },
  card: { padding: 16, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, gap: 8 },
  tag: { fontSize: 12, fontFamily: fonts.bold, color: "#8A5A2B" },
  q: { ...font.bodyStrong, color: colors.text },
  ans: { ...font.body, color: colors.textSub },
  bold: { fontFamily: fonts.bold, color: colors.text },
  sub: { ...font.caption, color: colors.textSub },
  memo: { padding: 10, borderRadius: radius.md, overflow: "hidden", backgroundColor: colors.surface, ...font.caption, color: colors.textSub },
  canvas: { height: 180, borderRadius: radius.card, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  stage: { height: 220, borderRadius: radius.card, backgroundColor: "#CDB9A3", overflow: "hidden" },
  box: { position: "absolute", left: 130, top: 70, width: 100, height: 76, borderWidth: 3, borderColor: colors.background, borderRadius: 10, backgroundColor: "rgba(255,252,247,0.25)" },
  badge: { position: "absolute", left: 14, top: 12, paddingVertical: 4, paddingHorizontal: 10, borderRadius: 999, overflow: "hidden", backgroundColor: colors.background, fontSize: 13, fontFamily: fonts.bold, color: colors.text },
  stageNote: { position: "absolute", left: 0, right: 0, bottom: 12, textAlign: "center", fontSize: 13, color: "#3A2719" },
  rows: { gap: 6 },
});
