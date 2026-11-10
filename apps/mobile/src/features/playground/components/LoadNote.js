import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, fonts, radius } from "@/theme";

/**
 * 서버에서 불러오는 동안·실패했을 때 보이는 안내. 불러오기가 끝나 data 가 있으면 null 을 돌려주므로 화면은 `if (note) return note` 로 쓴다.
 * @param {{ loading: boolean, error: string, data: unknown, reload: () => void, what?: string }} state useResource 결과
 */
export default function LoadNote({ loading, error, data, reload, what = "내용" }) {
  if (data) return null;
  if (loading && !error) {
    return (
      <View style={styles.box} accessibilityLiveRegion="polite">
        <Text style={styles.text}>불러오는 중이에요</Text>
      </View>
    );
  }
  return (
    <View style={styles.box} accessibilityRole="alert">
      <Text style={styles.text}>{what}을 불러오지 못했어요</Text>
      {error ? <Text style={styles.sub}>{error}</Text> : null}
      <Pressable onPress={reload} accessibilityRole="button" style={styles.retry}>
        <Text style={styles.retryText}>다시 불러오기</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { padding: 24, borderRadius: radius.lg, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, alignItems: "center", gap: 8 },
  text: { ...font.bodyStrong, color: colors.text, textAlign: "center" },
  sub: { ...font.caption, color: colors.textSub, textAlign: "center" },
  retry: { marginTop: 4, paddingVertical: 8, paddingHorizontal: 16, borderRadius: 999, backgroundColor: colors.surfaceStrong },
  retryText: { fontSize: 14, fontFamily: fonts.bold, color: colors.text },
});
