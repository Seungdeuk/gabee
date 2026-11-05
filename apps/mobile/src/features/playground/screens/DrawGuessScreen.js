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
const MAX_TRIES = 10; // 정답 시도 횟수. 다 틀리면 내가 낸 답 화면으로 간다
const FIELD_H = 48; // 입력칸과 맞히기 버튼 높이를 같게

/** 이게 뭐게 맞히기: 그림, 힌트 1(글자 수)·힌트 2(둘 다 열 때마다 −5점), 정답 입력. 맞히면 입력칸을 치우고 결과만 보여 준다. 틀리면 10번까지 다시 쓸 수 있고, 다 틀리면 내가 낸 답 화면으로 간다. */
export default function DrawGuessScreen() {
  const router = useRouter();
  const [guess, setGuess] = useState("");
  const [opened, setOpened] = useState(0); // 연 힌트 수(0~2). 열 때마다 −5점
  const [result, setResult] = useState(null); // null | "wrong" | "right"
  const [tries, setTries] = useState(0); // 지금까지 쓴 시도 횟수(맞힌 시도 포함)
  const [failed, setFailed] = useState([]); // 틀린 답 목록(10번 다 틀리면 내가 낸 답 화면에 보여 준다)
  const submit = () => {
    if (!guess.trim()) return;
    const used = tries + 1;
    setTries(used);
    if (guess.trim() === ANSWER) setResult("right");
    else if (used >= MAX_TRIES) router.replace({ pathname: "/play/my-answer", params: { kind: "draw", from: "아들이 낸 이게 뭐게", maker: "아들이", answer: ANSWER, alt: "멍멍이, 개", hint2: HINT2, hints: String(opened), tries: JSON.stringify([...failed, guess.trim()]) } }); // 10번 다 틀리면 내가 낸 답 화면
    else {
      setFailed((f) => [...f, guess.trim()]);
      setResult("wrong");
      setGuess("");
    }
  };
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
      {opened > 0 ? (
        <View style={styles.chips}>
          {opened >= 1 ? <Text style={styles.hint}>힌트 1: 3글자</Text> : null}
          {opened >= 2 ? <Text style={[styles.hint, styles.hintOpen]}>힌트 2: {HINT2}</Text> : null}
        </View>
      ) : null}
      {right ? (
        <View style={styles.done}>
          <Text style={styles.doneTitle}>정답이에요!</Text>
          <Text style={styles.doneSub}>
            {`+${SCORE.join + SCORE.correct - SCORE.hintCost * opened} (참여 +${SCORE.join} 정답 +${SCORE.correct}${opened ? ` 힌트 -${SCORE.hintCost * opened}` : ""})`}
          </Text>
        </View>
      ) : (
        <View style={styles.block}>
          <View style={styles.labelRow}>
            <Text style={styles.label}>
              정답 쓰기 <Text style={styles.sub}>({tries}/{MAX_TRIES})</Text>
            </Text>
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
      )}
      {right ? (
        <FieldButton label="나도 그림 문제 내기" icon="brush-outline" onPress={() => router.push("/play/draw-create")} />
      ) : opened < 2 ? (
        <FieldButton label={`힌트 ${opened + 1} 보기 (−${SCORE.hintCost}점)`} icon="bulb-outline" onPress={() => setOpened(opened + 1)} />
      ) : null}
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
  fieldBtnText: { fontSize: 15, fontFamily: fonts.bold, color: colors.text },
  from: { flexDirection: "row", alignItems: "center", gap: 10 },
  fromTitle: { ...font.bodyStrong, color: colors.text },
  fromSub: { ...font.caption, color: colors.textSub },
  canvas: { height: 260, borderRadius: radius.card, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  hint: { paddingVertical: 3, paddingHorizontal: 10, borderRadius: 12, overflow: "hidden", backgroundColor: colors.surfaceStrong, color: colors.text, fontSize: 12, fontFamily: fonts.bold },
  hintOpen: { backgroundColor: colors.peachSoft },
  block: { gap: 8 },
  labelRow: { flexDirection: "row", alignItems: "baseline", gap: 8 },
  label: { ...font.bodyStrong, color: colors.text },
  sub: { fontSize: 12, fontFamily: fonts.regular, color: colors.textSub, flexShrink: 1 },
  row: { flexDirection: "row", gap: 8, alignItems: "center" },
  input: { flex: 1, height: FIELD_H, paddingVertical: 0, paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: "#E3CFB0", backgroundColor: colors.card, color: colors.text, fontSize: 15, lineHeight: 18, includeFontPadding: false, textAlignVertical: "center", fontFamily: fonts.regular },
  send: { height: FIELD_H, minWidth: 76, paddingHorizontal: 14, borderRadius: 12, backgroundColor: colors.peach, alignItems: "center", justifyContent: "center" },
  sendOff: { backgroundColor: colors.honeySoft },
  sendText: { fontSize: 15, fontFamily: fonts.bold, color: colors.text },
  wrong: { ...font.caption, color: colors.danger, fontFamily: fonts.bold },
  done: { minHeight: 48, paddingVertical: 8, paddingHorizontal: 16, flexWrap: "wrap", borderRadius: radius.button, backgroundColor: colors.successSoft, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8 },
  doneTitle: { fontSize: 16, fontFamily: fonts.bold, color: "#2F4A3B" },
  doneSub: { fontSize: 14, fontFamily: fonts.bold, color: "#2F4A3B" },
});
