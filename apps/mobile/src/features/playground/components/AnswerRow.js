import { StyleSheet, Text, View } from "react-native";

import { colors, fonts } from "@/theme";

/** 가족이 낸 답 한 줄: 이름, 낸 답(힌트 쓴 횟수), 정답/오답 칩. 줄 순서는 푼 순서로 호출하는 쪽이 정한다. */
export default function AnswerRow({ name, answer, ok, extra }) {
  return (
    <View style={styles.row}>
      <Text style={styles.name}>{name}</Text>
      <Text style={styles.answer}>
        {answer}
        {extra ? <Text style={styles.extra}>{`  ${extra}`}</Text> : null}
      </Text>
      <Text style={[styles.chip, !ok && styles.chipNo]}>{ok ? "정답" : "오답"}</Text>
    </View>
  );
}

/** 시각이 빠른 사람이 위로 오게 정렬한다(시각은 "시:분" 24시간 글자, 화면에는 보이지 않는다). */
export const bySolved = (rows, at) => [...rows].sort((a, b) => a[at].localeCompare(b[at]));

const styles = StyleSheet.create({
  row: { minHeight: 40, flexDirection: "row", alignItems: "center", gap: 10 },
  name: { width: 44, fontSize: 14, fontFamily: fonts.bold, color: colors.text },
  answer: { flex: 1, fontSize: 14, fontFamily: fonts.regular, color: colors.text },
  extra: { fontSize: 12, color: colors.textSub },
  chip: { paddingVertical: 3, paddingHorizontal: 10, borderRadius: 12, overflow: "hidden", backgroundColor: colors.successSoft, color: "#2F4A3B", fontSize: 12, fontFamily: fonts.bold },
  chipNo: { backgroundColor: colors.dangerSoft, color: colors.danger },
});
