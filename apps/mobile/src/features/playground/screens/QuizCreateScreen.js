import { useNavigation, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Pressable, StyleSheet, Switch, Text, TextInput, View } from "react-native";

import Button from "@/shared/components/Button";
import ConfirmDialog from "@/shared/components/ConfirmDialog";
import { colors, font, fonts } from "@/theme";

import PlayScreen from "../components/PlayScreen";
import { AudiencePicker, QuestionTabs, RevealNote, Toggle } from "../components/quiz/QuizParts";

const Q_MAX = 60; // 문제 글자 수
const OPT_MAX = 20; // 보기 글자 수
const NOTE_MAX = 100; // 정답 뒤 한마디
const MAX_Q = 5;

// 가비가 가족이 공유한 사진·일정·안부에서 만든 추천 문제 (시안 데이터)
const RECS = [
  { id: "r1", source: "앨범에서 · 선택", tone: "amber", kind: "choice", q: "작년 여름 가족 여행지는 어디였을까?", options: ["제주도", "강릉", "부산", "여수"], answer: 0 },
  { id: "r2", source: "일정에서 · OX", tone: "blue", kind: "ox", q: "엄마 생신은 12월이다", options: ["O", "X"], answer: 1 },
  { id: "r3", source: "안부 기록에서 · 선택", tone: "green", kind: "choice", q: "이번 주 아빠가 산책한 날은 며칠일까?", options: ["2일", "3일", "4일", "5일"], answer: 2 },
];
const TONES = { amber: ["#FFFCF7", "#8A5A2B"], blue: ["#E6F0F8", "#3A6E99"], green: ["#E4F0E8", "#2F4A3B"] };

// 문제 하나가 보낼 수 있는 상태인지 본다. 안 되면 이유 한 줄, 되면 null
function problemOf(q, i) {
  const n = i + 1;
  if (!q.q.trim()) return `문제 ${n}을 써 주세요`;
  if (q.kind === "ox") return q.answer == null ? `문제 ${n}의 정답을 골라 주세요` : null;
  if (q.options.filter((o) => o.trim()).length < 2) return `문제 ${n}의 보기를 2개 이상 써 주세요`;
  if (q.answer == null || !q.options[q.answer]?.trim()) return `문제 ${n}의 정답을 골라 주세요`;
  return null;
}

const blank = () => ({ kind: "choice", q: "", options: ["", "", ""], answer: null, withNote: false, note: "" });
const fromRec = (r) => ({ kind: r.kind, q: r.q, options: [...r.options], answer: r.answer, withNote: false, note: "", rec: r.id });

/**
 * 가족 골든벨 내기. 가비 추천 / 직접 내기, OX / 선택 을 한 화면 안에서 바꾼다(화면이 새로고침처럼 넘어가지 않게).
 * 추천의 "문제·보기 고치기"는 같은 내용 그대로 직접 내기 칸에 채워 주고, 뒤로가기/닫기는 추천으로 돌아간다.
 */
export default function QuizCreateScreen({ initialMode = "rec" }) {
  const router = useRouter();
  const navigation = useNavigation();
  const leaving = useRef(false); // 문제를 보내서 나가는 중이면 뒤로가기를 막지 않는다
  const [mode, setMode] = useState(initialMode);
  const [qs, setQs] = useState([fromRec(RECS[0]), blank(), blank()]);
  const [active, setActive] = useState(0);
  const [target, setTarget] = useState([]);
  const [confirmRemove, setConfirmRemove] = useState(false); // 문제 삭제 확인 창
  const [tried, setTried] = useState(false); // 보내기를 한 번 눌러 본 뒤부터 안내를 보여 준다
  const problems = qs.map(problemOf);
  const firstBad = problems.findIndex(Boolean);
  const cur = qs[active];
  const patch = (p) => setQs((list) => list.map((x, i) => (i === active ? { ...x, ...p } : x)));

  const addQuestion = () => {
    if (qs.length >= MAX_Q) return;
    setQs((l) => [...l, blank()]);
    setActive(qs.length);
  };
  const pickRec = (r) => patch(fromRec(r));
  const removeQuestion = () => {
    setConfirmRemove(false);
    if (qs.length <= 1) return;
    setQs((l) => l.filter((_, i) => i !== active));
    setActive((a) => Math.max(0, Math.min(a, qs.length - 2)));
  };
  // 직접 내기에서 휴대폰 뒤로가기(밀어서 뒤로가기 포함)를 누르면 놀이터 메인으로 나가지 않고 가비 추천으로 돌아간다
  useEffect(() => {
    if (mode !== "manual") return undefined;
    return navigation.addListener("beforeRemove", (e) => {
      if (leaving.current) return;
      e.preventDefault();
      setMode("rec");
    });
  }, [mode, navigation]);

  const back = () => {
    if (mode === "manual") setMode("rec");
    else if (router.canGoBack()) router.back();
    else router.replace("/play");
  };

  return (
    <PlayScreen
      title="가족 골든벨 내기"
      footerInScroll
      close
      onBack={back}
      footer={
        <>
          {tried && firstBad >= 0 ? (
            <Text style={styles.error} accessibilityRole="alert">
              {problems[firstBad]}
            </Text>
          ) : (
            <RevealNote>내일 오후 2:10에 정답이 공개돼요 · 모두 답하면 바로 열려요</RevealNote>
          )}
          <Button
            label={`골든벨 ${qs.length}문제 보내기`}
            onPress={() => {
              if (firstBad >= 0) {
                setTried(true);
                setActive(firstBad);
                setMode("manual"); // 덜 채운 문제를 바로 고칠 수 있게
                return;
              }
              leaving.current = true;
              router.replace("/play/quiz-play");
            }}
          />
        </>
      }
    >
      <QuestionTabs count={qs.length} active={active} onSelect={setActive} onAdd={addQuestion} onRemove={() => setConfirmRemove(true)} flags={tried ? problems.map(Boolean) : []} max={MAX_Q} />
      <Toggle
        value={mode}
        onChange={setMode}
        options={[
          { key: "rec", label: "가비 추천" },
          { key: "manual", label: "직접 내기" },
        ]}
      />
      {mode === "rec" ? <Recommend active={active} cur={cur} onPick={pickRec} onEdit={() => setMode("manual")} /> : <Manual cur={cur} patch={patch} />}
      <AudiencePicker value={target} onChange={setTarget} />
      <ConfirmDialog
        visible={confirmRemove}
        title={`문제 ${active + 1}을 삭제할까요?`}
        message="쓴 내용이 사라져요."
        confirmLabel="삭제"
        onCancel={() => setConfirmRemove(false)}
        onConfirm={removeQuestion}
      />
    </PlayScreen>
  );
}

/** 가비 추천 목록: 고른 카드는 노랑, 나머지는 흰 카드. */
function Recommend({ active, cur, onPick, onEdit }) {
  return (
    <>
      <Text style={styles.note}>가족이 공유한 사진·일정에서 만든 문제예요 · 하나를 골라 문제 {active + 1}로 써요</Text>
      {RECS.map((r) => {
        const on = cur.rec === r.id;
        const [pillBg, pillFg] = TONES[r.tone];
        return (
          <Pressable key={r.id} onPress={() => onPick(r)} accessibilityRole="button" accessibilityState={{ selected: on }} style={[styles.card, on && styles.cardOn]}>
            <View style={styles.cardHead}>
              <Text style={[styles.pill, { backgroundColor: pillBg, color: pillFg }]}>{r.source}</Text>
              {on ? <Text style={styles.picked}>문제 {active + 1}로 선택됨</Text> : null}
            </View>
            <Text style={styles.recQ}>{r.q}</Text>
            {on && r.kind === "choice" ? (
              <View style={styles.optGrid}>
                {r.options.map((o, i) => (
                  <Text key={o} style={[styles.optCell, i === r.answer && styles.optCellAns]}>
                    {o}
                    {i === r.answer ? " (정답)" : ""}
                  </Text>
                ))}
              </View>
            ) : null}
            {on && r.kind === "ox" ? <Text style={styles.oxHint}>정답 {r.options[r.answer]}</Text> : null}
            {on ? (
              <Pressable onPress={onEdit} accessibilityRole="button" style={styles.editBtn}>
                <Text style={styles.editText}>문제·보기 고치기</Text>
              </Pressable>
            ) : null}
          </Pressable>
        );
      })}
    </>
  );
}

/** 직접 내기: OX/선택 전환, 문제, 보기(정답 동그라미·삭제), 정답 뒤 한마디. */
function Manual({ cur, patch }) {
  const isOx = cur.kind === "ox";
  const setKind = (k) => {
    if (k === cur.kind) return;
    patch(k === "ox" ? { kind: "ox", options: ["O", "X"], answer: null, rec: undefined } : { kind: "choice", options: ["", "", ""], answer: null, rec: undefined });
  };
  const setOpt = (i, v) => patch({ options: cur.options.map((x, j) => (j === i ? v.slice(0, OPT_MAX) : x)) });
  const removeOpt = (i) => patch({ options: cur.options.filter((_, j) => j !== i), answer: cur.answer === i ? null : cur.answer != null && cur.answer > i ? cur.answer - 1 : cur.answer });
  return (
    <>
      <Toggle
        value={cur.kind}
        onChange={setKind}
        options={[
          { key: "ox", label: "OX" },
          { key: "choice", label: "선택" },
        ]}
      />
      <View style={styles.block}>
        <View style={styles.labelRow}>
          <Text style={styles.label}>문제</Text>
          <Text style={styles.counter}>
            {cur.q.length}/{Q_MAX}
          </Text>
        </View>
        <TextInput value={cur.q} onChangeText={(v) => patch({ q: v.slice(0, Q_MAX) })} placeholder="문제를 써 주세요" placeholderTextColor={colors.placeholder} style={styles.input} accessibilityLabel="문제" />
      </View>
      {isOx ? (
        <View style={styles.block}>
          <Text style={styles.label}>
            정답 <Text style={styles.hint}>(눌러서 표시해요)</Text>
          </Text>
          <View style={styles.oxRow}>
            {["O", "X"].map((v, i) => (
              <Pressable key={v} onPress={() => patch({ answer: i })} accessibilityRole="button" accessibilityState={{ selected: cur.answer === i }} accessibilityLabel={cur.answer === i ? `${v}, 정답` : v} style={[styles.ox, cur.answer === i && styles.oxOn]}>
                <Text style={[styles.oxText, cur.answer === i && styles.oxTextOn]}>{v}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      ) : (
        <View style={styles.block}>
          <Text style={styles.label}>
            보기 <Text style={styles.hint}>(동그라미를 눌러 정답을 표시해요)</Text>
          </Text>
          {cur.options.map((o, i) => {
            const isAns = cur.answer === i;
            return (
              <View key={i} style={[styles.opt, isAns && styles.optAns]}>
                <Pressable onPress={() => patch({ answer: i })} accessibilityRole="button" accessibilityState={{ selected: isAns }} accessibilityLabel={isAns ? `보기 ${i + 1} 정답으로 표시됨` : `보기 ${i + 1} 정답으로 표시`} hitSlop={6} style={[styles.radio, isAns && styles.radioOn]}>
                  {isAns ? <Text style={styles.radioMark}>✓</Text> : null}
                </Pressable>
                <TextInput value={o} onChangeText={(v) => setOpt(i, v)} placeholder={`보기 ${i + 1}`} placeholderTextColor={colors.placeholder} accessibilityLabel={`보기 ${i + 1}`} style={styles.optInput} />
                {cur.options.length > 2 ? (
                  <Pressable onPress={() => removeOpt(i)} accessibilityRole="button" accessibilityLabel={`보기 ${i + 1} 빼기`} hitSlop={8} style={styles.optDel}>
                    <Text style={styles.optDelText}>✕</Text>
                  </Pressable>
                ) : null}
              </View>
            );
          })}
          {cur.options.length < 4 ? (
            <Pressable onPress={() => patch({ options: [...cur.options, ""] })} accessibilityRole="button" style={styles.addOpt}>
              <Text style={styles.addOptText}>+ 보기 추가 (최대 4개)</Text>
            </Pressable>
          ) : null}
        </View>
      )}
      <View style={styles.noteRow}>
        <Text style={styles.noteLabel}>한마디 남기기 (선택)</Text>
        <Switch value={cur.withNote} onValueChange={(v) => patch({ withNote: v })} trackColor={{ false: "#E0D6CB", true: colors.success }} thumbColor="#FFFFFF" />
      </View>
      {cur.withNote ? (
        <View style={styles.block}>
          <TextInput value={cur.note} onChangeText={(v) => patch({ note: v.slice(0, NOTE_MAX) })} placeholder="정답 공개될 때 같이 보여요" placeholderTextColor={colors.placeholder} style={styles.input} accessibilityLabel="한마디" />
          <Text style={styles.counterRight}>
            {cur.note.length}/{NOTE_MAX}
          </Text>
        </View>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  note: { ...font.caption, color: colors.textSub },
  error: { ...font.caption, color: colors.danger, textAlign: "center", fontFamily: fonts.bold },
  card: { padding: 16, borderRadius: 18, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, gap: 10 },
  cardOn: { backgroundColor: colors.surfaceStrong, borderColor: colors.surfaceStrong },
  cardHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  pill: { paddingVertical: 4, paddingHorizontal: 10, borderRadius: 999, overflow: "hidden", fontSize: 12, fontFamily: fonts.bold },
  picked: { fontSize: 13, fontFamily: fonts.bold, color: "#8A5A2B" },
  recQ: { fontSize: 17, lineHeight: 25, fontFamily: fonts.bold, color: colors.text },
  optGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  optCell: { width: "48%", flexGrow: 1, height: 44, borderRadius: 12, overflow: "hidden", textAlign: "center", textAlignVertical: "center", backgroundColor: "#FFFCF7", fontSize: 15, fontFamily: fonts.regular, color: colors.text },
  optCellAns: { backgroundColor: colors.successSoft, color: "#2F4A3B", fontFamily: fonts.bold },
  oxHint: { fontSize: 14, fontFamily: fonts.bold, color: "#2F4A3B" },
  editBtn: { alignSelf: "flex-start", minHeight: 40, justifyContent: "center", paddingHorizontal: 4 },
  editText: { fontSize: 14, fontFamily: fonts.medium, color: "#8A5A2B" },
  block: { gap: 8 },
  labelRow: { flexDirection: "row", alignItems: "baseline", gap: 8 },
  label: { ...font.bodyStrong, color: colors.text },
  hint: { fontSize: 13, fontFamily: fonts.regular, color: colors.textSub },
  counter: { fontSize: 13, fontFamily: fonts.regular, color: colors.textSub },
  counterRight: { fontSize: 13, fontFamily: fonts.regular, color: colors.textSub, textAlign: "right" },
  input: { height: 44, paddingHorizontal: 14, paddingVertical: 0, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, color: colors.text, fontSize: 15, fontFamily: fonts.regular },
  oxRow: { flexDirection: "row", gap: 10 },
  ox: { flex: 1, height: 64, borderRadius: 16, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  oxOn: { backgroundColor: colors.successSoft, borderColor: colors.success },
  oxText: { fontSize: 26, fontFamily: fonts.bold, color: colors.textSub },
  oxTextOn: { color: "#2F4A3B" },
  opt: { height: 48, paddingLeft: 10, paddingRight: 6, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, flexDirection: "row", alignItems: "center", gap: 8 },
  optAns: { backgroundColor: "#F2F8F4", borderColor: colors.success },
  radio: { width: 26, height: 26, borderRadius: 13, borderWidth: 1.5, borderColor: "#D9C7B4", alignItems: "center", justifyContent: "center" },
  radioOn: { backgroundColor: colors.success, borderColor: colors.success },
  radioMark: { fontSize: 14, lineHeight: 18, color: "#FFFFFF", fontFamily: fonts.bold },
  optInput: { flex: 1, height: 44, paddingVertical: 0, fontSize: 15, fontFamily: fonts.regular, color: colors.text },
  optDel: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  optDelText: { fontSize: 14, color: colors.textSub },
  addOpt: { height: 40, borderRadius: 12, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center", backgroundColor: colors.card },
  addOptText: { fontSize: 14, fontFamily: fonts.medium, color: colors.textSub },
  noteRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 44 },
  noteLabel: { ...font.body, color: colors.text },
});
