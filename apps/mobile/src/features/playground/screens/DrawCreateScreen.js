import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, fonts } from "@/theme";

import DrawingCanvas from "../components/draw/DrawingCanvas";
import PlayScreen from "../components/PlayScreen";
import { AudiencePicker, RevealNote } from "../components/quiz/QuizParts";
import { SCORE } from "../games";

const PALETTE = [
  { name: "검정", value: colors.text },
  { name: "분홍", value: colors.peach },
  { name: "파랑", value: "#3A6E99" },
  { name: "초록", value: colors.success },
];
const HINT_MAX = 20; // 맞히는 화면에서 힌트 칩이 두 줄로 넘어가지 않는 길이

/** 이게 뭐게 문제 내기: 정답(+비슷한 정답), 그림판, 힌트 1(글자 수 자동)·힌트 2(직접), 대상. */
export default function DrawCreateScreen() {
  const router = useRouter();
  const [answer, setAnswer] = useState("강아지");
  const [alt, setAlt] = useState("멍멍이, 개");
  const [hint2, setHint2] = useState("동물이야");
  const [strokes, setStrokes] = useState([]);
  const [color, setColor] = useState(PALETTE[0].value);
  const [eraser, setEraser] = useState(false);
  const [target, setTarget] = useState([]);
  const [paint, setPaint] = useState(false); // 그리기 모드: 켜져 있는 동안 화면 스크롤을 잠근다. 완료를 누르면 풀린다
  const letters = answer.replace(/\s/g, "").length;
  const [tried, setTried] = useState(false);
  const problem = !answer.trim() ? "정답을 써 주세요" : strokes.length === 0 ? "그림을 그려 주세요" : null;

  return (
    <PlayScreen
      title="그림 문제 내기"
      footerInScroll
      close
      scrollEnabled={!paint}
      footer={
        <>
          {tried && problem ? (
            <Text style={styles.error} accessibilityRole="alert">
              {problem}
            </Text>
          ) : (
            <RevealNote>내일 오후 2:10에 정답이 공개돼요 · 모두 답하면 바로 열려요</RevealNote>
          )}
          <Button
            label="그림 문제 보내기"
            onPress={() => {
              if (problem) {
                setTried(true);
                return;
              }
              router.replace("/play/draw-guess");
            }}
          />
        </>
      }
    >
      <View style={styles.block}>
        <View style={styles.labelRow}>
          <Text style={styles.label}>정답</Text>
          <Text style={styles.sub}>정확하게 입력해야 정답으로 처리돼요!</Text>
        </View>
        <TextInput value={answer} onChangeText={setAnswer} style={[styles.input, styles.inputMain]} accessibilityLabel="정답" />
        <Text style={styles.sub}>이것도 정답으로 해요, 쉼표로 구분</Text>
        <TextInput value={alt} onChangeText={setAlt} style={styles.input} accessibilityLabel="비슷한 정답" />
      </View>
      <View>
        <View pointerEvents={paint ? "auto" : "none"}>
          <DrawingCanvas strokes={strokes} onChange={setStrokes} color={color} eraser={eraser} />
        </View>
        {paint ? (
          <>
            <Pressable onPress={() => setPaint(false)} accessibilityRole="button" accessibilityLabel="그리기 끝내기" hitSlop={6} style={styles.doneBtn}>
              <Text style={styles.doneText}>완료</Text>
            </Pressable>
            <Text style={styles.paintNote}>그리는 동안은 화면이 움직이지 않아요</Text>
          </>
        ) : (
          <Pressable onPress={() => setPaint(true)} accessibilityRole="button" accessibilityLabel={strokes.length ? "그림 이어서 그리기" : "그리기 시작"} style={styles.startLayer}>
            <Text style={styles.startPill}>{strokes.length ? "눌러서 이어 그리기" : "눌러서 그리기 시작"}</Text>
          </Pressable>
        )}
      </View>
      <View style={styles.tools}>
        <View style={styles.colors}>
          {PALETTE.map((p) => (
            <Pressable
              key={p.name}
              onPress={() => {
                setColor(p.value);
                setEraser(false);
              }}
              accessibilityRole="button"
              accessibilityLabel={p.name}
              accessibilityState={{ selected: !eraser && color === p.value }}
              style={[styles.swatch, { backgroundColor: p.value }, !eraser && color === p.value && styles.swatchOn]}
            />
          ))}
        </View>
        <View style={styles.colors}>
          <Tool label="지우개" on={eraser} onPress={() => setEraser((v) => !v)} icon={<MaterialCommunityIcons name="eraser" size={22} color={colors.text} />} />
          <Tool label="되돌리기" onPress={() => setStrokes((s) => s.slice(0, -1))} icon={<Ionicons name="arrow-undo-outline" size={22} color={colors.text} />} />
          <Tool label="전체 지우기" onPress={() => setStrokes([])} icon={<Ionicons name="trash-outline" size={22} color={colors.text} />} />
        </View>
      </View>
      <View style={styles.block}>
        <Text style={styles.label}>
          힌트 <Text style={styles.sub}>(힌트를 열 때마다 맞힌 사람의 점수가 {SCORE.hintCost}점씩 줄어요)</Text>
        </Text>
        <View style={styles.hintRow}>
          <Text style={styles.hintTitle}>힌트 1</Text>
          <Text style={styles.hintValue}>글자 수 {letters}글자 (자동)</Text>
        </View>
        <View style={styles.hintBox}>
          <Text style={styles.hintTitle}>
            힌트 2 <Text style={styles.sub}>({hint2.length}/{HINT_MAX})</Text>
          </Text>
          <TextInput value={hint2} onChangeText={(v) => setHint2(v.slice(0, HINT_MAX))} maxLength={HINT_MAX} style={styles.input} accessibilityLabel="힌트 2" />
        </View>
      </View>
      <AudiencePicker value={target} onChange={setTarget} />
    </PlayScreen>
  );
}

function Tool({ label, onPress, icon, on = false }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label} accessibilityState={{ selected: on }} style={[styles.tool, on && styles.toolOn]}>
      {icon}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  error: { ...font.caption, color: colors.danger, textAlign: "center", fontFamily: fonts.bold },
  block: { gap: 8 },
  labelRow: { flexDirection: "row", alignItems: "baseline", gap: 8 },
  label: { ...font.bodyStrong, color: colors.text },
  sub: { fontSize: 13, fontFamily: fonts.regular, color: colors.textSub },
  input: { height: 44, paddingVertical: 0, paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, color: colors.text, fontSize: 15, fontFamily: fonts.regular },
  inputMain: { fontSize: 15 },
  doneBtn: { position: "absolute", right: 10, top: 10, minHeight: 36, paddingHorizontal: 16, borderRadius: 18, backgroundColor: colors.dark, alignItems: "center", justifyContent: "center" },
  doneText: { fontSize: 14, fontFamily: fonts.bold, color: colors.background },
  paintNote: { position: "absolute", left: 0, right: 0, bottom: 10, textAlign: "center", fontSize: 12, color: colors.textSub },
  startLayer: { position: "absolute", left: 0, right: 0, top: 0, bottom: 0, alignItems: "center", justifyContent: "center" },
  startPill: { paddingVertical: 10, paddingHorizontal: 18, borderRadius: 20, overflow: "hidden", backgroundColor: colors.surfaceStrong, color: colors.text, fontSize: 14, fontFamily: fonts.bold },
  tools: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  colors: { flexDirection: "row", gap: 8, alignItems: "center" },
  swatch: { width: 40, height: 40, borderRadius: 20, borderWidth: 1, borderColor: colors.border },
  swatchOn: { borderWidth: 3, borderColor: colors.dark },
  tool: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" }, // 배경·테두리 없이 아이콘만
  toolOn: { backgroundColor: colors.surfaceStrong }, // 지우개가 켜진 동안만 옅은 노랑
  hintRow: { padding: 12, borderRadius: 14, backgroundColor: colors.surface, flexDirection: "row", alignItems: "baseline", gap: 8 },
  hintBox: { padding: 12, borderRadius: 14, backgroundColor: colors.surface, gap: 8 },
  hintTitle: { ...font.bodyStrong, color: colors.text },
  hintValue: { ...font.body, color: colors.text },
});
