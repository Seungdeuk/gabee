import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useRef, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, useWindowDimensions, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, fonts, spacing } from "@/theme";

import { strokesFromRec } from "../adapt";
import { createDraw } from "../api";
import DrawingCanvas from "../components/draw/DrawingCanvas";
import DrawRecommend from "../components/draw/DrawRecommend";
import PlayScreen from "../components/PlayScreen";
import { AudiencePicker, RevealNote, MakeQuotaNote, Toggle } from "../components/quiz/QuizParts";
import { SCORE } from "../games";
import { playLive, useDrawRecs } from "../hooks";
import { recordMade } from "../mock";
import { pngAssetFromBase64 } from "../upload";

const PALETTE = [
  { name: "검정", value: colors.text },
  { name: "분홍", value: colors.peach },
  { name: "파랑", value: "#3A6E99" },
  { name: "초록", value: colors.success },
];
const HINT_MAX = 20; // 맞히는 화면에서 힌트 칩이 두 줄로 넘어가지 않는 길이
const CANVAS_HEIGHT = 280; // DrawingCanvas 기본 높이

/** 이게 뭐게 문제 내기: 가비 추천 / 직접 그리기. 직접 그리기는 정답(+비슷한 정답), 그림판, 힌트 1(글자 수 자동)·힌트 2(직접), 대상. 추천을 고르면 직접 그리기 칸에 채워져 고칠 수 있다. */
export default function DrawCreateScreen() {
  const router = useRouter();
  const [mode, setMode] = useState("rec"); // "rec" 가비 추천 | "manual" 직접 그리기
  const recs = useDrawRecs();
  const [recIndex, setRecIndex] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [pickedId, setPickedId] = useState(null); // 마지막으로 "이 그림으로 쓰기"를 누른 추천
  const { width: windowWidth } = useWindowDimensions();
  const canvasWidth = windowWidth - spacing.xl * 2; // 그림판 칸 너비(화면 좌우 여백을 뺀 값)
  const [answer, setAnswer] = useState("");
  const [alt, setAlt] = useState("");
  const [hint2, setHint2] = useState("");
  const [strokes, setStrokes] = useState([]);
  const [color, setColor] = useState(PALETTE[0].value);
  const [eraser, setEraser] = useState(false);
  const [target, setTarget] = useState([]);
  const svgRef = useRef(null); // 그림판 SVG: 보낼 때 PNG 로 바꾼다
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  const [paint, setPaint] = useState(false); // 그리기 모드: 켜져 있는 동안 화면 스크롤을 잠근다. 완료를 누르면 풀린다
  const letters = answer.replace(/\s/g, "").length;
  const [tried, setTried] = useState(false);
  const problem = !answer.trim() ? (mode === "rec" ? "가비 추천에서 그림을 골라 주세요" : "정답을 써 주세요") : strokes.length === 0 ? "그림을 그려 주세요" : null;
  const refreshRecs = async () => {
    setRefreshing(true);
    await recs.reload();
    setRefreshing(false);
  };
  // 추천을 고르면 정답 칸·비슷한 정답 칸·그림판을 채우고 직접 그리기로 넘어가 고칠 수 있게 한다
  const pickRec = (item) => {
    setAnswer(item.word);
    setAlt((item.alt_answers ?? []).join(", "));
    setStrokes(strokesFromRec(item, canvasWidth, CANVAS_HEIGHT, PALETTE[0].value));
    setEraser(false);
    setColor(PALETTE[0].value);
    setPickedId(item.id);
    setMode("manual");
  };

  return (
    <PlayScreen
      title="그림 문제 내기"
      footerInScroll
      close
      scrollEnabled={!paint}
      footer={
        <>
          {sendError || (tried && problem) ? (
            <Text style={styles.error} accessibilityRole="alert">
              {sendError || problem}
            </Text>
          ) : (
            <RevealNote>내일 오후 2:10에 정답이 공개돼요, 모두 답하면 바로 열려요</RevealNote>
          )}
          <MakeQuotaNote />
          <Button
            label="그림 문제 보내기"
            disabled={sending}
            onPress={async () => {
              if (problem) {
                setTried(true);
                return;
              }
              if (playLive()) {
                setSending(true);
                setSendError("");
                try {
                  const base64 = await new Promise((resolve, reject) => {
                    if (!svgRef.current?.toDataURL) reject(new Error("그림을 저장하지 못했어요"));
                    else svgRef.current.toDataURL(resolve);
                  });
                  const item = await createDraw({
                    image: await pngAssetFromBase64(base64),
                    answer: answer.trim(),
                    alts: alt.split(",").map((a) => a.trim()).filter(Boolean),
                    hint2: hint2.trim(),
                    playerIds: target,
                  });
                  router.replace(`/play/sent-detail?id=${item.id}&kind=draw`);
                } catch (e) {
                  setSendError(e.message || "보내지 못했어요. 잠시 뒤 다시 해 주세요");
                } finally {
                  setSending(false);
                }
                return;
              }
              recordMade();
              router.replace("/play/draw-guess");
            }}
          />
        </>
      }
    >
      <Toggle
        value={mode}
        onChange={setMode}
        options={[
          { key: "rec", label: "가비 추천" },
          { key: "manual", label: "직접 그리기" },
        ]}
      />
      {mode === "rec" ? (
        <DrawRecommend recs={recs} index={recIndex} onIndex={setRecIndex} pickedId={pickedId} onPick={pickRec} refreshing={refreshing} onRefresh={refreshRecs} />
      ) : null}
      {mode === "manual" ? (
        <>
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
              <DrawingCanvas strokes={strokes} onChange={setStrokes} color={color} eraser={eraser} svgRef={svgRef} />
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
        </>
      ) : null}
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
  input: { height: 44, paddingVertical: 0, paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, color: colors.text, fontSize: 15, lineHeight: 18, includeFontPadding: false, textAlignVertical: "center", fontFamily: fonts.regular },
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
