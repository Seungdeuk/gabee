import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import Svg, { Circle, Path } from "react-native-svg";

import Avatar from "@/shared/components/Avatar";
import { colors, font, fonts, radius } from "@/theme";

import PlayScreen from "../components/PlayScreen";
import { SCORE } from "../games";

const ANSWER = "강아지"; // 시안: 서버가 판정하게 되면 이 값은 화면에서 사라진다
const HINT2 = "동물이야";
const FIELD_H = 48; // 입력칸과 맞히기 버튼 높이를 같게

/** 이게 뭐게 맞히기: 그림, 힌트 1(글자 수)·힌트 2(둘 다 열 때마다 −5점), 정답 입력. 맞히면 입력칸을 치우고 결과만 보여 준다. */
export default function DrawGuessScreen() {
  const router = useRouter();
  const [guess, setGuess] = useState("");
  const [opened, setOpened] = useState(0); // 연 힌트 수(0~2). 열 때마다 −5점
  const [result, setResult] = useState(null); // null | "wrong" | "right"
  const submit = () => setResult(guess.trim() === ANSWER ? "right" : "wrong");
  const right = result === "right";
  return (
    <PlayScreen title="이게 뭐게" close>
      <View style={styles.from}>
        <Avatar name="아들" userId="son" size={36} />
        <View>
          <Text style={styles.fromTitle}>아들이 그린 그림</Text>
          <Text style={styles.fromSub}>오늘 오후 2:10</Text>
        </View>
      </View>
      <View style={styles.canvas}>
        <Svg width={200} height={180} viewBox="0 0 220 200" accessibilityLabel="아들이 그린 그림">
          <Path d="M55 80c0-35 25-55 55-55s55 20 55 55-20 80-55 80-55-45-55-80z" stroke={colors.text} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" fill="none" />
          <Circle cx={88} cy={85} r={5} stroke={colors.text} strokeWidth={4} fill="none" />
          <Circle cx={132} cy={85} r={5} stroke={colors.text} strokeWidth={4} fill="none" />
        </Svg>
      </View>
      <View style={styles.chipLines}>
        {/* 힌트 버튼은 힌트 칩이 나오는 줄 오른쪽에 둔다: 누르고 위아래로 오가지 않게 */}
        {opened > 0 || (!right && opened < 2) ? (
          <View style={styles.hintRow}>
            <View style={[styles.chips, styles.flex]}>
              {opened >= 1 ? <Text style={styles.hint}>힌트 1: 3글자</Text> : null}
              {opened >= 2 ? <Text style={[styles.hint, styles.hintOpen]}>힌트 2: {HINT2}</Text> : null}
            </View>
            {!right && opened < 2 ? (
              <Pressable onPress={() => setOpened(opened + 1)} accessibilityRole="button" accessibilityLabel={`힌트 ${opened + 1} 보기, 점수 ${SCORE.hintCost}점 줄어요`} style={styles.hintBtn}>
                <Text style={styles.hintBtnText}>
                  힌트 {opened + 1} 보기 (−{SCORE.hintCost}점)
                </Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}
        <View style={styles.chips}>
          <Text style={styles.chip}>엄마 맞힘</Text>
          <Text style={[styles.chip, styles.chipWait]}>아빠 아직</Text>
        </View>
      </View>
      {right ? (
        <View style={styles.done}>
          <Text style={styles.doneTitle}>정답이에요!</Text>
          <Text style={styles.doneSub}>
            정답 +{SCORE.correct}
            {opened ? ` (힌트 -${SCORE.hintCost * opened})` : ""}
          </Text>
        </View>
      ) : (
        <>
          <View style={styles.block}>
            <View style={styles.labelRow}>
              <Text style={styles.label}>정답 쓰기</Text>
              <Text style={styles.sub}>정확하게 입력해야 정답으로 처리돼요!</Text>
            </View>
            {result === "wrong" ? <Text style={styles.wrong}>아쉬워요, 다시 생각해 보세요</Text> : null}
            <View style={styles.row}>
              <TextInput value={guess} onChangeText={setGuess} style={styles.input} accessibilityLabel="정답 쓰기" onSubmitEditing={submit} />
              <Pressable onPress={submit} disabled={!guess.trim()} accessibilityRole="button" accessibilityLabel="맞히기" style={[styles.send, !guess.trim() && styles.sendOff]}>
                <Text style={styles.sendText}>맞히기</Text>
              </Pressable>
            </View>
          </View>
        </>
      )}
      <FieldButton label="나도 그림 문제 내기" icon="brush-outline" onPress={() => router.push("/play/draw-create")} />
    </PlayScreen>
  );
}

/** 입력칸·정답 표시와 같은 높이(48)의 버튼 */
function FieldButton({ label, onPress, icon }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label} style={styles.fieldBtn}>
      {icon ? <Ionicons name={icon} size={18} color={colors.textMuted} /> : null}
      <Text style={styles.fieldBtnText}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  fieldBtn: { height: FIELD_H, borderRadius: radius.button, backgroundColor: colors.honeySoft, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8 },
  flex: { flex: 1 },
  hintRow: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 8 },
  hintBtn: { height: 32, paddingHorizontal: 12, borderRadius: 16, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center", marginLeft: "auto" },
  hintBtnText: { fontSize: 13, fontFamily: fonts.bold, color: colors.text },
  fieldBtnText: { fontSize: 15, fontFamily: fonts.bold, color: colors.text },
  from: { flexDirection: "row", alignItems: "center", gap: 10 },
  fromTitle: { ...font.bodyStrong, color: colors.text },
  fromSub: { ...font.caption, color: colors.textSub },
  canvas: { height: 260, borderRadius: radius.card, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  chipLines: { gap: 6 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  hint: { paddingVertical: 3, paddingHorizontal: 10, borderRadius: 12, overflow: "hidden", backgroundColor: colors.surfaceStrong, color: colors.text, fontSize: 12, fontFamily: fonts.bold },
  hintOpen: { backgroundColor: colors.peachSoft },
  chip: { paddingVertical: 3, paddingHorizontal: 10, borderRadius: 12, overflow: "hidden", backgroundColor: colors.successSoft, color: "#2F4A3B", fontSize: 12, fontFamily: fonts.bold },
  chipWait: { backgroundColor: colors.surface, color: colors.textSub },
  block: { gap: 8 },
  labelRow: { flexDirection: "row", alignItems: "baseline", gap: 8 },
  label: { ...font.bodyStrong, color: colors.text },
  sub: { fontSize: 12, fontFamily: fonts.regular, color: colors.textSub, flexShrink: 1 },
  row: { flexDirection: "row", gap: 8, alignItems: "center" },
  input: { flex: 1, height: FIELD_H, paddingVertical: 0, paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: "#E3CFB0", backgroundColor: colors.card, color: colors.text, fontSize: 16, fontFamily: fonts.regular },
  send: { height: FIELD_H, minWidth: 76, paddingHorizontal: 14, borderRadius: 12, backgroundColor: colors.peach, alignItems: "center", justifyContent: "center" },
  sendOff: { backgroundColor: colors.honeySoft },
  sendText: { fontSize: 15, fontFamily: fonts.bold, color: colors.text },
  wrong: { ...font.caption, color: colors.danger, fontFamily: fonts.bold },
  done: { height: 48, paddingHorizontal: 16, borderRadius: radius.button, backgroundColor: colors.successSoft, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8 },
  doneTitle: { fontSize: 16, fontFamily: fonts.bold, color: "#2F4A3B" },
  doneSub: { fontSize: 16, fontFamily: fonts.bold, color: "#2F4A3B" },
});
