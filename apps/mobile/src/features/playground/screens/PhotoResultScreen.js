import { useLocalSearchParams, useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, fonts, radius } from "@/theme";

import { photoResultView } from "../adapt";
import AnswerRow from "../components/AnswerRow";
import LoadNote from "../components/LoadNote";
import PhotoStage from "../components/PhotoStage";
import PlayScreen from "../components/PlayScreen";
import ScoreBox from "../components/ScoreBox";
import { SCORE } from "../games";
import { playLive, useMyId, usePlayItem } from "../hooks";

// 시안: 내가 "조금 줄여 보기"를 쓴 횟수(힌트와 같이 번마다 -5점)
const SHRINKS = 1;
// 가족이 낸 답(푼 시각은 정렬에만 쓴다)
const ROWS = [["아빠", "돌잔치", "13:50"], ["엄마", "제주도 여행", "09:12"]];

/** 시안 데이터를 서버 결과와 같은 모양으로 맞춘다(사진 없이 틀만 보인다). */
function mockView() {
  return {
    maker: "딸",
    imageUrl: null,
    question: "이 사진, 어디서 찍었을까?",
    answer: "제주도 여행",
    comment: "그날 비가 와서 협재 해변에서 우동을 먹었어요",
    box: null,
    hasScore: true,
    score: { total: SCORE.join + SCORE.correct - SCORE.hintCost * SHRINKS, join: SCORE.join, correct: SCORE.correct, hint: -SCORE.hintCost * SHRINKS },
    rows: [...ROWS].sort((a, b) => a[2].localeCompare(b[2])).map(([name, text]) => ({ name, text, ok: text === "제주도 여행" })),
  };
}

/** 찰칵! 탐정단 정답 공개: 정답, 원본 사진과 문제로 낸 부분, 낸 사람의 한마디, 누가 맞혔나. 서버에 연결되면 id 로 결과를 불러온다. */
export default function PhotoResultScreen() {
  const { id } = useLocalSearchParams();
  const live = playLive() && Boolean(id);
  const res = usePlayItem(live ? id : null);
  const myId = useMyId();
  const view = live ? (res.data?.photo ? photoResultView(res.data, myId) : null) : mockView();
  if (!view) {
    return (
      <PlayScreen title="정답 공개" close>
        <LoadNote {...res} what="결과" />
      </PlayScreen>
    );
  }
  return <PhotoResultBody view={view} />;
}

function PhotoResultBody({ view }) {
  const router = useRouter();
  const { score } = view;
  return (
    <PlayScreen
      title="정답 공개"
      close
      footer={
        <>
          <Button label="이 사진 얘기 가족방에서 나누기" onPress={() => router.push("/family-chat")} />
          <Button label="나도 사진 문제 내기" variant="secondary" onPress={() => router.push("/play/photo-create")} />
        </>
      }
    >
      <View style={styles.hero}>
        <Text style={styles.heroSub}>{view.question}</Text>
        <Text style={styles.heroBig}>{view.answer}</Text>
      </View>
      {view.imageUrl ? (
        <PhotoStage path={view.imageUrl} box={view.box} badge="원본 사진" note={view.box ? "네모가 문제로 낸 부분이에요" : undefined} label="원본 사진" />
      ) : (
        <View style={styles.stage}>
          <View style={styles.box} />
          <Text style={styles.badge}>원본 사진</Text>
          <Text style={styles.stageNote}>네모가 문제로 낸 부분이에요</Text>
        </View>
      )}
      {view.comment ? (
        <View style={styles.memo}>
          <Text style={styles.memoText}>{`${view.maker}의 한마디\n"${view.comment}"`}</Text>
        </View>
      ) : null}
      {view.hasScore ? <ScoreBox total={score.total} detail={`참여 +${score.join}${score.correct ? ` 정답 +${score.correct}` : ""}${score.hint ? ` 힌트 ${score.hint}` : ""}`} /> : null}
      <Text style={styles.label}>가족이 낸 답</Text>
      <View style={styles.rows}>
        {view.rows.map((r) => (
          <AnswerRow key={r.name} name={r.name} answer={r.text} ok={r.ok} />
        ))}
      </View>
    </PlayScreen>
  );
}

const styles = StyleSheet.create({
  hero: { padding: 18, borderRadius: radius.card, backgroundColor: colors.successSoft, gap: 4 },
  heroBig: { fontSize: 24, fontFamily: fonts.bold, color: "#2F4A3B" },
  heroSub: { ...font.caption, color: "#2F4A3B" },
  stage: { height: 260, borderRadius: radius.card, backgroundColor: "#CDB9A3", overflow: "hidden" },
  box: { position: "absolute", left: 130, top: 80, width: 110, height: 90, borderWidth: 3, borderColor: colors.background, borderRadius: 10, backgroundColor: "rgba(255,252,247,0.25)" },
  badge: { position: "absolute", left: 14, top: 12, paddingVertical: 4, paddingHorizontal: 10, borderRadius: 999, overflow: "hidden", backgroundColor: colors.background, fontSize: 13, fontFamily: fonts.bold, color: colors.text },
  stageNote: { position: "absolute", left: 0, right: 0, bottom: 12, textAlign: "center", fontSize: 13, color: "#3A2719" },
  memo: { padding: 12, borderRadius: radius.md, backgroundColor: colors.surface },
  memoText: { ...font.caption, color: colors.textSub },
  label: { ...font.bodyStrong, color: colors.text },
  rows: { gap: 6 },
});
