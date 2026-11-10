import { StyleSheet, Text, View } from "react-native";

import { colors, font, fonts } from "@/theme";

/** 섹션 제목 + 제목 옆 옅은 설명(note) + 오른쪽 개수/보조 글자(right). */
export default function SectionHead({ title, note, right }) {
  return (
    <View style={styles.row}>
      <Text style={styles.title}>
        {title}
        {note ? <Text style={styles.note}> {note}</Text> : null}
      </Text>
      {right ? <Text style={styles.right}>{right}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between" },
  title: { ...font.cardTitle, color: colors.text },
  note: { fontSize: 13, fontFamily: fonts.regular, color: colors.textSub },
  right: { ...font.caption, color: colors.textSub },
});
