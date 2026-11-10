import { StyleSheet, Text, View } from "react-native";

import { colors, font, fonts, radius } from "@/theme";

/** 붉은 점수 칸: "점수 +30"만 굵고 조금 크게, 계산 내역은 작은 글씨로. detail 은 "(참여 +10 정답 +20)" 같은 괄호 글. */
export default function ScoreBox({ total, detail }) {
  return (
    <View style={styles.box}>
      <Text style={styles.text}>
        <Text style={styles.total}>{`점수 ${total >= 0 ? "+" : ""}${total}`}</Text>
        {detail ? ` (${detail})` : ""}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { padding: 14, borderRadius: radius.md, backgroundColor: colors.dangerSoft },
  text: { ...font.caption, color: colors.text },
  total: { fontSize: 16, fontFamily: fonts.bold },
});
