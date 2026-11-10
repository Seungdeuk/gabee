import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import Svg, { Circle, Path } from "react-native-svg";

import AuthImage from "@/shared/components/AuthImage";
import Avatar from "@/shared/components/Avatar";
import Button from "@/shared/components/Button";
import ConfirmDialog from "@/shared/components/ConfirmDialog";
import { colors, font, fonts, radius } from "@/theme";

import { gameKey, quizResultView, revealLabel } from "../adapt";
import { useInvite } from "../components/InviteSheet";
import LoadNote from "../components/LoadNote";
import PhotoStage from "../components/PhotoStage";
import PlayIcon from "../components/PlayIcon";
import PlayScreen from "../components/PlayScreen";
import { GAMES, SCORE } from "../games";
import { playLive, usePlayItem } from "../hooks";
import RuleCard, { LIFE, SEC } from "../components/bomb/RuleCard";
import PlayerRow from "../components/bomb/PlayerRow";
import { bombRoom, closeRoom } from "../mock";

// 가족 현황 시안. state: done 완료 / wait 대기 (폭탄은 입장 / 대기)
const FAMILY = {
  draw: [
    { id: "mom", name: "엄마", state: "done", note: "오늘 오전 9:12" },
    { id: "dad", name: "아빠", state: "done", note: "오늘 오전 10:40" },
    { id: "daughter", name: "딸", state: "wait", note: "" },
  ],
  photo: [
    { id: "mom", name: "엄마", state: "done", note: "오늘 오전 9:12" },
    { id: "dad", name: "아빠", state: "wait", note: "" },
    { id: "daughter", name: "딸", state: "wait", note: "" },
  ],
  quiz: [
    { id: "mom", name: "엄마", state: "done", note: "오늘 오전 9:12" },
    { id: "dad", name: "아빠", state: "done", note: "오늘 오전 10:40" },
    { id: "daughter", name: "딸", state: "wait", note: "" },
  ],
  bomb: bombRoom("me").map((p) => ({ id: p.id, name: p.name, state: p.joined ? "in" : "wait", note: p.note })),
};
const TITLES = {
  draw: ["내가 낸 이게 뭐게", "내일 오전 11:00 공개", "내일 오전 11:00"],
  photo: ["내가 낸 찰칵! 탐정단", "내일 오후 2:10 공개", "내일 오후 2:10"],
  quiz: ["내가 낸 가족 골든벨", "내일 오후 2:10 공개", "내일 오후 2:10"],
  bomb: ["문장 폭탄 · 내가 연 방", "방이 열려 있어요 · 5명 입장"],
};
const ROW_H = 52; // 선수 한 줄 높이
const VISIBLE_PLAYERS = 4; // 나 포함 4명까지 보이고 나머지는 이 영역 안에서 스크롤
const QUESTIONS = [
  { kind: "OX", q: "엄마 생신은 12월이다", answer: "X" },
  { kind: "선택", q: "아빠가 제일 좋아하는 반찬은?", answer: "계란말이", options: ["계란말이", "멸치볶음", "김치찌개", "잡채"] },
  { kind: "선택", q: "우리 가족이 처음 같이 간 여행지는?", answer: "제주도", options: ["제주도", "강릉", "부산", "여수"] },
];
const PHOTO_OPTIONS = ["제주도 여행", "할머니 댁", "강릉 바다", "우리 집 거실"];

/** 내가 낸 문제 상세: 내 문제 내용, 가족별 현황(완료·대기), 공개 시각. kind = draw | photo | quiz | bomb */
export default function SentDetailScreen() {
  const { id } = useLocalSearchParams();
  return playLive() && id ? <LiveSentDetail id={id} /> : <MockSentDetail />;
}

/** 서버에 연결됐을 때: 내가 낸 골든벨·이게 뭐게·탐정단의 내용과 가족 현황. 닫힌 문제는 결과 화면으로 보낸다. */
function LiveSentDetail({ id }) {
  const router = useRouter();
  const res = usePlayItem(id);
  const item = res.data;
  useEffect(() => {
    if (item?.closed) router.replace(`/play/sent-result?id=${id}&kind=${gameKey(item.game)}`);
  }, [item?.closed, item?.game, id, router]);
  if (!item) {
    return (
      <PlayScreen title="내가 낸 문제">
        <LoadNote {...res} what="문제" />
      </PlayScreen>
    );
  }
  const k = gameKey(item.game);
  const reveal = revealLabel(item.close_at);
  const members = item.family_status ?? [];
  const doneCount = members.filter((m) => m.done).length;
  return (
    <PlayScreen title="내가 낸 문제">
      <View style={styles.summary}>
        <View style={styles.summaryIcon}>
          <PlayIcon icon={GAMES[k].icon} />
        </View>
        <View style={styles.flex}>
          <Text style={styles.summaryTitle}>내가 낸 {GAMES[k].name}</Text>
          <Text style={styles.summarySub}>{reveal} 공개</Text>
        </View>
      </View>
      {k === "draw" ? <LiveDraw item={item} /> : k === "photo" ? <LivePhoto item={item} /> : <LiveQuiz item={item} />}
      <View style={styles.family}>
        <View style={styles.familyHead}>
          <Text style={styles.h2}>가족 현황</Text>
          <Text style={styles.count}>
            {doneCount} / {members.length}명 완료
          </Text>
        </View>
        {members.map((m) => (
          <View key={m.player.id} style={styles.member}>
            <Avatar name={m.player.name} userId={m.player.id} size={36} />
            <View style={styles.memberText}>
              <Text style={styles.memberName}>{m.player.name}</Text>
              {m.done && m.answered_at ? <Text style={styles.memberNote}>{revealLabel(m.answered_at)}</Text> : null}
            </View>
            <Text style={[styles.chip, !m.done && styles.chipWait]}>{m.done ? "완료" : "대기"}</Text>
          </View>
        ))}
      </View>
      <Text style={styles.scoreNote}>결과는 {reveal}에 열려요</Text>
      <Text style={styles.note}>
        {doneCount > 0 ? `문제가 닫히면 문제 출제로 +${SCORE.make} 받아요` : `가족이 한 명이라도 풀면 문제 출제로 +${SCORE.make} 받아요`}
      </Text>
    </PlayScreen>
  );
}

function LiveDraw({ item }) {
  const d = item.draw;
  const alts = d?.alt_answers ?? [];
  return (
    <>
      <AuthImage path={item.image_url} contentFit="contain" style={styles.canvas} accessibilityLabel="내가 그린 그림" />
      <View style={styles.block}>
        <View style={styles.answerBox}>
          <Text style={styles.answer}>{d?.answer}</Text>
          {alts.length ? <Text style={styles.answerSub}>이것도 정답: {alts.join(", ")}</Text> : null}
        </View>
        <View style={styles.chips}>
          {d?.hint1 ? <Text style={styles.hint}>힌트 1: {d.hint1}</Text> : null}
          {d?.hint2 ? <Text style={[styles.hint, styles.hintOpen]}>힌트 2: {d.hint2}</Text> : null}
        </View>
      </View>
    </>
  );
}

function LivePhoto({ item }) {
  const p = item.photo;
  if (!p) return null;
  const answerIndex = p.answer ? p.answer.indexOf("1") : -1;
  return (
    <>
      <PhotoStage path={item.image_url} box={p.box_x == null ? null : { x: p.box_x, y: p.box_y, zoom: p.zoom }} badge={`${p.zoom}배 확대`} label="내가 고른 사진" />
      <View style={styles.question}>
        <Text style={styles.questionText}>{p.question}</Text>
      </View>
      <View style={styles.block}>
        <Text style={styles.h3}>보기</Text>
        {p.options.map((o, i) => (
          <View key={o} style={[styles.opt, i === answerIndex && styles.optAns]}>
            <View style={[styles.radio, i === answerIndex && styles.radioOn]}>{i === answerIndex ? <Text style={styles.radioMark}>✓</Text> : null}</View>
            <Text style={styles.optText}>{o}</Text>
          </View>
        ))}
      </View>
      {p.comment ? (
        <View style={styles.block}>
          <Text style={styles.h3}>한마디</Text>
          <Text style={styles.memo}>{p.comment}</Text>
        </View>
      ) : null}
    </>
  );
}

function LiveQuiz({ item }) {
  const view = quizResultView(item, null);
  return (
    <View style={styles.block}>
      {view.questions.map((q, i) => (
        <View key={q.q} style={styles.qCard}>
          <Text style={styles.qKind}>
            문제 {i + 1} {q.kind}
          </Text>
          <Text style={styles.qText}>{q.q}</Text>
          {q.kind === "OX" ? (
            <Text style={[styles.optChip, styles.optChipAns, styles.selfStart]}>정답 {q.answer}</Text>
          ) : (
            <View style={styles.chips}>
              {q.options.map((o) => (
                <Text key={o} style={[styles.optChip, o === q.answer && styles.optChipAns]}>
                  {o}
                  {o === q.answer ? " ✓" : ""}
                </Text>
              ))}
            </View>
          )}
        </View>
      ))}
    </View>
  );
}

function MockSentDetail() {
  const { kind = "draw" } = useLocalSearchParams();
  const router = useRouter();
  const [askClose, setAskClose] = useState(false);
  const { ask: askInvite, sheet: inviteSheet } = useInvite();
  const [life, setLife] = useState(LIFE.def);
  const [sec, setSec] = useState(SEC.def);
  const k = FAMILY[kind] ? kind : "draw";
  const members = FAMILY[k];
  const doneCount = members.filter((m) => m.state === "done" || m.state === "in").length;
  const [title, sub, reveal] = TITLES[k];
  return (
    <PlayScreen
      title="내가 낸 문제"
      fixed={k === "bomb"} // 폭탄 방은 화면을 고정하고 선수 목록만 스크롤한다
      footer={
        k === "bomb" ? (
          <>
            <Button label={`게임 시작 (${doneCount}명)`} disabled={doneCount < 2} onPress={() => router.push({ pathname: "/play/bomb-play", params: { life: String(life), sec: String(sec), host: "me" } })} />
            <Button label="방 닫기" variant="secondary" onPress={() => setAskClose(true)} />
            <Text style={styles.note}>{"2명부터 시작할 수 있어요\n아무도 시작하지 않으면 1시간 뒤 자동으로 닫혀요"}</Text>
          </>
        ) : undefined
      }
    >
      <View style={styles.summary}>
        <View style={styles.summaryIcon}>
          <PlayIcon icon={GAMES[k].icon} />
        </View>
        <View style={styles.flex}>
          <Text style={styles.summaryTitle}>{title}</Text>
          <Text style={styles.summarySub}>{sub}</Text>
        </View>
      </View>

      {k === "bomb" ? <RuleCard life={life} sec={sec} onLife={setLife} onSec={setSec} /> : null}
      {k === "draw" ? <Draw /> : null}
      {k === "photo" ? <Photo /> : null}
      {k === "quiz" ? <Quiz /> : null}

      <View style={styles.family}>
        <View style={styles.familyHead}>
          <Text style={styles.h2}>{k === "bomb" ? "선수 대기" : "가족 현황"}</Text>
          <Text style={styles.count}>{k === "bomb" ? `${doneCount}명 입장` : `${doneCount} / ${members.length}명 완료`}</Text>
        </View>
        {k === "bomb" ? (
          <ScrollView style={styles.playerList} nestedScrollEnabled showsVerticalScrollIndicator={members.length > VISIBLE_PLAYERS}>
            {members.map((m) => (
              <PlayerRow key={m.id} id={m.id} name={m.name} note={m.note} joined={m.state === "in"} onInvite={() => askInvite({ name: m.name, kind: "bomb" })} />
            ))}
          </ScrollView>
        ) : null}
        {k === "bomb" ? null : members.map((m) =>
          (
          <View key={m.id} style={styles.member}>
            <Avatar name={m.id === "me" ? "나" : m.name} userId={m.id} size={36} />
            <View style={styles.memberText}>
              <Text style={styles.memberName}>{m.name}</Text>
              {m.note ? <Text style={styles.memberNote}>{m.note}</Text> : null}
            </View>
            <Text style={[styles.chip, m.state === "wait" && styles.chipWait]}>{m.state === "in" ? "입장" : m.state === "done" ? "완료" : "대기"}</Text>
          </View>
          ),
        )}
      </View>

      {k === "bomb" ? (
        <ConfirmDialog
          visible={askClose}
          title="방을 닫을까요?"
          message="들어온 가족은 나가게 돼요."
          confirmLabel="닫기"
          onCancel={() => setAskClose(false)}
          onConfirm={() => {
            closeRoom("s4");
            setAskClose(false);
            router.replace("/play/board?tab=sent");
          }}
        />
      ) : (
        <>
          <Text style={styles.scoreNote}>결과는 {reveal}에 열려요</Text>
          <Text style={styles.note}>
            {doneCount > 0 ? `문제가 닫히면 문제 출제로 +${SCORE.make} 받아요` : `가족이 한 명이라도 풀면 문제 출제로 +${SCORE.make} 받아요`}
          </Text>
        </>
      )}
      {inviteSheet}
    </PlayScreen>
  );
}

function Draw() {
  return (
    <>
      <View style={styles.canvas}>
        <Svg width={200} height={150} viewBox="0 0 220 200" accessibilityLabel="내가 그린 강아지 그림">
          <Path d="M55 80c0-35 25-55 55-55s55 20 55 55-20 80-55 80-55-45-55-80z" stroke={colors.text} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" fill="none" />
          <Circle cx={88} cy={85} r={5} stroke={colors.text} strokeWidth={4} fill="none" />
          <Circle cx={132} cy={85} r={5} stroke={colors.text} strokeWidth={4} fill="none" />
        </Svg>
      </View>
      <View style={styles.block}>
        <View style={styles.answerBox}>
          <Text style={styles.answer}>강아지</Text>
          <Text style={styles.answerSub}>이것도 정답: 멍멍이, 개</Text>
        </View>
        <View style={styles.chips}>
          <Text style={styles.hint}>힌트 1: 3글자</Text>
          <Text style={[styles.hint, styles.hintOpen]}>힌트 2: 동물이야</Text>
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
        <Text style={[styles.badge, styles.badgeLeft]}>가족 앨범 · 제주도 여행</Text>
        <Text style={[styles.badge, styles.badgeRight]}>4배 확대</Text>
      </View>
      <View style={styles.question}>
        <Text style={styles.questionText}>이 사진, 어디서 누구랑 찍었을까요?</Text>
      </View>
      <View style={styles.block}>
        <Text style={styles.h3}>보기</Text>
        {PHOTO_OPTIONS.map((o, i) => (
          <View key={o} style={[styles.opt, i === 0 && styles.optAns]}>
            <View style={[styles.radio, i === 0 && styles.radioOn]}>{i === 0 ? <Text style={styles.radioMark}>✓</Text> : null}</View>
            <Text style={styles.optText}>{o}</Text>
          </View>
        ))}
      </View>
      <View style={styles.block}>
        <Text style={styles.h3}>한마디</Text>
        <Text style={styles.memo}>그날 비가 와서 협재 해변에서 우동을 먹었어요. 언제 어디서 찍었는지 기억나는 사람?</Text>
      </View>
    </>
  );
}

function Quiz() {
  return (
    <View style={styles.block}>
      {QUESTIONS.map((q, i) => (
        <View key={q.q} style={styles.qCard}>
          <Text style={styles.qKind}>
            문제 {i + 1} {q.kind}
          </Text>
          <Text style={styles.qText}>{q.q}</Text>
          {q.options ? (
            <View style={styles.chips}>
              {q.options.map((o) => (
                <Text key={o} style={[styles.optChip, o === q.answer && styles.optChipAns]}>
                  {o}
                  {o === q.answer ? " ✓" : ""}
                </Text>
              ))}
            </View>
          ) : (
            <Text style={[styles.optChip, styles.optChipAns, styles.selfStart]}>정답 {q.answer}</Text>
          )}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  summary: { padding: 14, borderRadius: radius.lg, backgroundColor: colors.surface, flexDirection: "row", alignItems: "center", gap: 12 },
  summaryIcon: { width: 44, height: 44, borderRadius: 12, backgroundColor: colors.surfaceStrong, alignItems: "center", justifyContent: "center" },
  summaryTitle: { ...font.bodyStrong, color: colors.text },
  summarySub: { ...font.caption, color: colors.textSub },
  canvas: { height: 180, borderRadius: radius.card, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  block: { gap: 8 },
  h2: { ...font.cardTitle, color: colors.text },
  h3: { ...font.bodyStrong, color: colors.text },
  count: { ...font.caption, color: colors.textSub },
  answerBox: { padding: 12, borderRadius: radius.md, backgroundColor: colors.successSoft, gap: 2 },
  answer: { fontSize: 16, fontFamily: fonts.bold, color: "#2F4A3B" },
  answerSub: { ...font.caption, color: "#2F4A3B" },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6, alignItems: "flex-start", alignContent: "flex-start" }, // 칩이 줄 높이만큼 늘어나지 않게
  hint: { paddingVertical: 3, paddingHorizontal: 10, borderRadius: 12, overflow: "hidden", backgroundColor: colors.surfaceStrong, color: colors.text, fontSize: 12, fontFamily: fonts.bold },
  hintOpen: { backgroundColor: colors.peachSoft },
  stage: { height: 200, borderRadius: radius.card, backgroundColor: "#CDB9A3", overflow: "hidden" },
  box: { position: "absolute", left: 130, top: 70, width: 88, height: 65, borderWidth: 3, borderColor: colors.background, borderRadius: 10, backgroundColor: "rgba(255,252,247,0.25)" },
  badge: { position: "absolute", paddingVertical: 3, paddingHorizontal: 9, borderRadius: 999, overflow: "hidden", backgroundColor: colors.background, fontSize: 12, fontFamily: fonts.bold, color: colors.text },
  badgeLeft: { left: 12, top: 10 },
  badgeRight: { right: 12, bottom: 10 },
  question: { padding: 14, borderRadius: radius.lg, backgroundColor: colors.surface, flexDirection: "row", alignItems: "center", gap: 10 },
  questionText: { flex: 1, fontSize: 16, fontFamily: fonts.bold, color: colors.text },
  opt: { height: 44, paddingHorizontal: 12, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, flexDirection: "row", alignItems: "center", gap: 8 },
  optAns: { backgroundColor: "#F2F8F4", borderColor: colors.success },
  optText: { flex: 1, fontSize: 15, fontFamily: fonts.regular, color: colors.text },
  radio: { width: 22, height: 22, borderRadius: 11, borderWidth: 1.5, borderColor: "#D9C7B4", alignItems: "center", justifyContent: "center" },
  radioOn: { backgroundColor: colors.success, borderColor: colors.success },
  radioMark: { fontSize: 12, lineHeight: 16, color: "#FFFFFF", fontFamily: fonts.bold },
  memo: { padding: 12, borderRadius: radius.md, overflow: "hidden", backgroundColor: "#F7F0E6", fontSize: 13, lineHeight: 20, fontFamily: fonts.regular, color: colors.textSub },
  qCard: { padding: 14, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, gap: 8 },
  qKind: { fontSize: 12, fontFamily: fonts.bold, color: "#8A5A2B" },
  qText: { fontSize: 15, lineHeight: 22, fontFamily: fonts.bold, color: colors.text },
  optChip: { alignSelf: "flex-start", paddingVertical: 3, paddingHorizontal: 10, borderRadius: 12, overflow: "hidden", backgroundColor: "#F7F0E6", color: colors.textSub, fontSize: 12, fontFamily: fonts.regular },
  optChipAns: { backgroundColor: colors.successSoft, color: "#2F4A3B", fontFamily: fonts.bold },
  selfStart: { alignSelf: "flex-start" },
  family: { gap: 4, flexShrink: 1 },
  familyHead: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between" },
  playerList: { flexGrow: 0, flexShrink: 1, maxHeight: ROW_H * VISIBLE_PLAYERS },
  member: { minHeight: 52, flexDirection: "row", alignItems: "center", gap: 12 },
  memberText: { flex: 1, flexDirection: "row", alignItems: "baseline", gap: 8 },
  memberName: { ...font.bodyStrong, color: colors.text },
  memberNote: { ...font.caption, color: colors.textSub },
  chip: { paddingVertical: 3, paddingHorizontal: 10, borderRadius: 12, overflow: "hidden", backgroundColor: colors.successSoft, color: "#2F4A3B", fontSize: 12, fontFamily: fonts.bold },
  chipWait: { backgroundColor: "#F7F0E6", color: colors.textSub },
  note: { ...font.caption, color: colors.textSub, textAlign: "center" },
  scoreNote: { padding: 12, borderRadius: radius.md, overflow: "hidden", backgroundColor: colors.surface, ...font.caption, color: colors.text, textAlign: "center" },
});
